from vyper import ast as vy_ast
from vyper.codegen.return_ import gen_tuple_return, make_return_stmt
from vyper.exceptions import (
    CompilerPanic,
    ConstancyViolation,
    EventDeclarationException,
    InvalidLiteral,
    StructureException,
    TypeMismatch,
    VariableDeclarationException,
)
from vyper.functions import DISPATCH_TABLE, STMT_DISPATCH_TABLE
from vyper.parser import external_call, self_call
from vyper.parser.events import pack_logging_data, pack_logging_topics
from vyper.parser.expr import Expr
from vyper.parser.parser_utils import (
    LLLnode,
    base_type_conversion,
    getpos,
    make_byte_array_copier,
    make_setter,
    unwrap_location,
    zero_pad,
)
from vyper.types import (
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    ContractType,
    ListType,
    NodeType,
    StructType,
    TupleType,
    get_size_of_type,
    is_base_type,
    parse_type,
)
from vyper.utils import SizeLimits, bytes_to_int, fourbytes_to_int, keccak256


class Stmt(object):
    # TODO: Once other refactors are made reevaluate all inline imports
    def __init__(self, stmt, context):
        self.stmt = stmt
        self.context = context
        self.stmt_table = {
            vy_ast.Expr: self.expr,
            vy_ast.Pass: self.parse_pass,
            vy_ast.AnnAssign: self.ann_assign,
            vy_ast.Assign: self.assign,
            vy_ast.If: self.parse_if,
            vy_ast.Call: self.call,
            vy_ast.Assert: self.parse_assert,
            vy_ast.For: self.parse_for,
            vy_ast.AugAssign: self.aug_assign,
            vy_ast.Break: self.parse_break,
            vy_ast.Continue: self.parse_continue,
            vy_ast.Return: self.parse_return,
            vy_ast.Name: self.parse_name,
            vy_ast.Raise: self.parse_raise,
        }
        stmt_type = self.stmt.__class__
        if stmt_type in self.stmt_table:
            self.lll_node = self.stmt_table[stmt_type]()
        else:
            raise StructureException(f"Unsupported statement type: {type(stmt).__name__}", stmt)

    def expr(self):
        return Stmt(self.stmt.value, self.context).lll_node

    def parse_pass(self):
        return LLLnode.from_list('pass', typ=None, pos=getpos(self.stmt))

    def parse_name(self):
        if self.stmt.id == "vdb":
            return LLLnode('debugger', typ=None, pos=getpos(self.stmt))
        else:
            raise StructureException(f"Unsupported statement type: {type(self.stmt)}", self.stmt)

    def parse_raise(self):
        if self.stmt.exc is None:
            raise StructureException('Raise must have a reason', self.stmt)
        return self._assert_reason(0, self.stmt.exc)

    def _check_valid_assign(self, sub):
        if (
            isinstance(self.stmt.annotation, vy_ast.Name) and
            self.stmt.annotation.id == 'bytes32'
        ):
            # CMC 04/07/2020 this check could be much clearer, more like:
            # if isinstance(ByteArrayLike) and maxlen == 32
            #   or isinstance(BaseType) and typ.typ == 'bytes32'
            #   then GOOD
            #   else RAISE
            if isinstance(sub.typ, ByteArrayLike):
                if sub.typ.maxlen != 32:
                    raise TypeMismatch(
                        'Invalid type, expected: bytes32. String is incorrect length.', self.stmt
                    )
                return
            elif isinstance(sub.typ, BaseType):
                if sub.typ.typ != 'bytes32':
                    raise TypeMismatch('Invalid type, expected: bytes32', self.stmt)
                return
            else:
                raise TypeMismatch("Invalid type, expected: bytes32", self.stmt)
        elif isinstance(self.stmt.annotation, vy_ast.Subscript):
            # check list assign:
            if not isinstance(sub.typ, (ListType, ByteArrayLike)):
                raise TypeMismatch(
                    f'Invalid type, expected: {self.stmt.annotation.value.id},'
                    f' got: {sub.typ}', self.stmt
                )
        elif sub.typ is None:
            # Check that the object to be assigned is not of NoneType
            raise TypeMismatch(
                f"Invalid type, expected {self.stmt.annotation.id}", self.stmt
            )
        elif isinstance(sub.typ, StructType):
            # This needs to get more sophisticated in the presence of
            # foreign structs.
            if not sub.typ.name == self.stmt.annotation.id:
                raise TypeMismatch(
                    f"Invalid type, expected {self.stmt.annotation.id}", self.stmt
                )
        # Check that the integer literal, can be assigned to uint256 if necessary.
        elif (self.stmt.annotation.id, sub.typ.typ) == ('uint256', 'int128') and sub.typ.is_literal:
            if not SizeLimits.in_bounds('uint256', sub.value):
                raise InvalidLiteral(
                    'Invalid uint256 assignment, value not in uint256 range.', self.stmt
                )
        elif self.stmt.annotation.id != sub.typ.typ:
            raise TypeMismatch(
                f'Invalid type {sub.typ.typ}, expected: {self.stmt.annotation.id}',
                self.stmt,
            )
        else:
            return True

    def _check_same_variable_assign(self, sub):
        lhs_var_name = self.stmt.target.id
        rhs_names = self._check_rhs_var_assn_recur(self.stmt.value)
        if lhs_var_name in rhs_names:
            raise VariableDeclarationException((
                'Invalid variable assignment, same variable not allowed on '
                f'LHS and RHS: {lhs_var_name}'
            ))
        else:
            return True

    def _check_rhs_var_assn_recur(self, val):
        names = ()
        if isinstance(val, (vy_ast.BinOp, vy_ast.Compare)):
            right_node = val.right
            left_node = val.left
            names = names + self._check_rhs_var_assn_recur(right_node)
            names = names + self._check_rhs_var_assn_recur(left_node)
        elif isinstance(val, vy_ast.UnaryOp):
            operand_node = val.operand
            names = names + self._check_rhs_var_assn_recur(operand_node)
        elif isinstance(val, vy_ast.BoolOp):
            for bool_val in val.values:
                names = names + self._check_rhs_var_assn_recur(bool_val)
        elif isinstance(val, vy_ast.Name):
            name = val.id
            names = names + (name, )
        return names

    def ann_assign(self):
        with self.context.assignment_scope():
            typ = parse_type(
                self.stmt.annotation,
                location='memory',
                custom_structs=self.context.structs,
                constants=self.context.constants,
            )
            if isinstance(self.stmt.target, vy_ast.Attribute):
                raise TypeMismatch(
                    f'May not set type for field {self.stmt.target.attr}',
                    self.stmt,
                )
            varname = self.stmt.target.id
            pos = self.context.new_variable(varname, typ)
            if self.stmt.value is None:
                raise StructureException(
                    'New variables must be initialized explicitly',
                    self.stmt)

            sub = Expr(self.stmt.value, self.context).lll_node

            is_literal_bytes32_assign = (
                isinstance(sub.typ, ByteArrayType)
                and sub.typ.maxlen == 32
                and isinstance(typ, BaseType)
                and typ.typ == 'bytes32'
                and sub.typ.is_literal
            )

            # If bytes[32] to bytes32 assignment rewrite sub as bytes32.
            if is_literal_bytes32_assign:
                sub = LLLnode(
                    bytes_to_int(self.stmt.value.s),
                    typ=BaseType('bytes32'),
                    pos=getpos(self.stmt),
                )

            self._check_valid_assign(sub)
            self._check_same_variable_assign(sub)
            variable_loc = LLLnode.from_list(
                pos,
                typ=typ,
                location='memory',
                pos=getpos(self.stmt),
            )
            o = make_setter(variable_loc, sub, 'memory', pos=getpos(self.stmt))

            return o

    def _check_implicit_conversion(self, var_id, sub):
        target_typ = self.context.vars[var_id].typ
        assign_typ = sub.typ
        if isinstance(target_typ, BaseType) and isinstance(assign_typ, BaseType):
            if not assign_typ.is_literal and assign_typ.typ != target_typ.typ:
                raise TypeMismatch(
                    f'Invalid type {assign_typ.typ}, expected: {target_typ.typ}',
                    self.stmt
                )

    def assign(self):
        # Assignment (e.g. x[4] = y)

        with self.context.assignment_scope():
            sub = Expr(self.stmt.value, self.context).lll_node

            # Error check when assigning to declared variable
            if isinstance(self.stmt.target, vy_ast.Name):
                # Do not allow assignment to undefined variables without annotation
                if self.stmt.target.id not in self.context.vars:
                    raise VariableDeclarationException("Variable type not defined", self.stmt)

                # Check against implicit conversion
                self._check_implicit_conversion(self.stmt.target.id, sub)

            is_valid_tuple_assign = (
                isinstance(self.stmt.target, vy_ast.Tuple)
            ) and isinstance(self.stmt.value, vy_ast.Tuple)

            # Do no allow tuple-to-tuple assignment
            if is_valid_tuple_assign:
                raise VariableDeclarationException(
                    "Tuple to tuple assignment not supported",
                    self.stmt,
                )

            # Checks to see if assignment is valid
            target = self.get_target(self.stmt.target)
            if isinstance(target.typ, ContractType) and not isinstance(sub.typ, ContractType):
                raise TypeMismatch(
                    'Contract assignment expects casted address: '
                    f'{target.typ}(<address_var>)',
                    self.stmt
                )
            o = make_setter(target, sub, target.location, pos=getpos(self.stmt))

            o.pos = getpos(self.stmt)

        return o

    def is_bool_expr(self, test_expr):
        if not isinstance(test_expr.typ, BaseType):
            return False
        if not test_expr.typ.typ == 'bool':
            return False
        return True

    def parse_if(self):
        if self.stmt.orelse:
            block_scope_id = id(self.stmt.orelse)
            with self.context.make_blockscope(block_scope_id):
                add_on = [parse_body(self.stmt.orelse, self.context)]
        else:
            add_on = []

        block_scope_id = id(self.stmt)
        with self.context.make_blockscope(block_scope_id):
            test_expr = Expr.parse_value_expr(self.stmt.test, self.context)

            if not self.is_bool_expr(test_expr):
                raise TypeMismatch('Only boolean expressions allowed', self.stmt.test)
            body = ['if', test_expr,
                    parse_body(self.stmt.body, self.context)] + add_on
            o = LLLnode.from_list(
                body,
                typ=None, pos=getpos(self.stmt)
            )
        return o

    def call(self):
        is_self_function = (
            isinstance(self.stmt.func, vy_ast.Attribute)
        ) and isinstance(self.stmt.func.value, vy_ast.Name) and self.stmt.func.value.id == "self"

        is_log_call = (
            isinstance(self.stmt.func, vy_ast.Attribute)
        ) and isinstance(self.stmt.func.value, vy_ast.Name) and self.stmt.func.value.id == 'log'

        if isinstance(self.stmt.func, vy_ast.Name):
            funcname = self.stmt.func.id
            if funcname in STMT_DISPATCH_TABLE:
                return STMT_DISPATCH_TABLE[funcname].build_LLL(self.stmt, self.context)
            elif funcname in DISPATCH_TABLE:
                raise StructureException(
                    f"Function {funcname} can not be called without being used.",
                    self.stmt,
                )
            else:
                raise StructureException(
                    f"Unknown function: '{self.stmt.func.id}'.",
                    self.stmt,
                )
        elif is_self_function:
            return self_call.make_call(self.stmt, self.context)
        elif is_log_call:
            if self.stmt.func.attr not in self.context.sigs['self']:
                raise EventDeclarationException(f"Event not declared yet: {self.stmt.func.attr}")
            event = self.context.sigs['self'][self.stmt.func.attr]
            if len(event.indexed_list) != len(self.stmt.args):
                raise EventDeclarationException(
                    f"{event.name} received {len(self.stmt.args)} arguments but "
                    f"expected {len(event.indexed_list)}"
                )
            expected_topics, topics = [], []
            expected_data, data = [], []
            for pos, is_indexed in enumerate(event.indexed_list):
                if is_indexed:
                    expected_topics.append(event.args[pos])
                    topics.append(self.stmt.args[pos])
                else:
                    expected_data.append(event.args[pos])
                    data.append(self.stmt.args[pos])
            topics = pack_logging_topics(
                event.event_id,
                topics,
                expected_topics,
                self.context,
                pos=getpos(self.stmt),
            )
            inargs, inargsize, inargsize_node, inarg_start = pack_logging_data(
                expected_data,
                data,
                self.context,
                pos=getpos(self.stmt),
            )

            if inargsize_node is None:
                sz = inargsize
            else:
                sz = ['mload', inargsize_node]

            return LLLnode.from_list([
                'seq', inargs, LLLnode.from_list(
                    ["log" + str(len(topics)), inarg_start, sz] + topics,
                    add_gas_estimate=inargsize * 10,
                )
            ], typ=None, pos=getpos(self.stmt))
        else:
            return external_call.make_external_call(self.stmt, self.context)

    @staticmethod
    def _assert_unreachable(test_expr, msg):
        return LLLnode.from_list(['assert_unreachable', test_expr], typ=None, pos=getpos(msg))

    def _assert_reason(self, test_expr, msg):
        if isinstance(msg, vy_ast.Name) and msg.id == 'UNREACHABLE':
            return self._assert_unreachable(test_expr, msg)

        if not isinstance(msg, vy_ast.Str):
            raise StructureException(
                'Reason parameter of assert needs to be a literal string '
                '(or UNREACHABLE constant).',
                msg
            )
        if len(msg.s.strip()) == 0:
            raise StructureException(
                'Empty reason string not allowed.', self.stmt
            )
        reason_str = msg.s.strip()
        sig_placeholder = self.context.new_placeholder(BaseType(32))
        arg_placeholder = self.context.new_placeholder(BaseType(32))
        reason_str_type = ByteArrayType(len(reason_str))
        placeholder_bytes = Expr(msg, self.context).lll_node
        method_id = fourbytes_to_int(keccak256(b"Error(string)")[:4])
        assert_reason = [
                'seq',
                ['mstore', sig_placeholder, method_id],
                ['mstore', arg_placeholder, 32],
                placeholder_bytes,
                [
                    'assert_reason',
                    test_expr,
                    int(sig_placeholder + 28),
                    int(4 + 32 + get_size_of_type(reason_str_type) * 32),
                    ],
                ]
        return LLLnode.from_list(assert_reason, typ=None, pos=getpos(self.stmt))

    def parse_assert(self):

        with self.context.assertion_scope():
            test_expr = Expr.parse_value_expr(self.stmt.test, self.context)

        if not self.is_bool_expr(test_expr):
            raise TypeMismatch('Only boolean expressions allowed', self.stmt.test)
        if self.stmt.msg:
            return self._assert_reason(test_expr, self.stmt.msg)
        else:
            return LLLnode.from_list(['assert', test_expr], typ=None, pos=getpos(self.stmt))

    def _check_valid_range_constant(self, arg_ast_node, raise_exception=True):
        with self.context.range_scope():
            # TODO should catch if raise_exception == False?
            arg_expr = Expr.parse_value_expr(arg_ast_node, self.context)

        is_integer_literal = (
            isinstance(arg_expr.typ, BaseType) and
            arg_expr.typ.is_literal and
            arg_expr.typ.typ in {'uint256', 'int128'}
        )
        if not is_integer_literal and raise_exception:
            raise StructureException(
                "Range only accepts literal (constant) values of type uint256 or int128",
                arg_ast_node
            )
        return is_integer_literal, arg_expr

    def _get_range_const_value(self, arg_ast_node):
        _, arg_expr = self._check_valid_range_constant(arg_ast_node)
        return arg_expr.value

    def parse_for(self):
        # Type 0 for, e.g. for i in list(): ...
        if self._is_list_iter():
            return self.parse_for_list()

        if not isinstance(self.stmt.iter, vy_ast.Call):
            if isinstance(self.stmt.iter, vy_ast.Subscript):
                raise StructureException("Cannot iterate over a nested list", self.stmt.iter)
            raise StructureException(
                f"Cannot iterate over '{type(self.stmt.iter).__name__}' object",
                self.stmt.iter
            )
        if getattr(self.stmt.iter.func, 'id', None) != "range":
            raise StructureException(
                "Non-literals cannot be used as loop range", self.stmt.iter.func
            )
        if len(self.stmt.iter.args) not in {1, 2}:
            raise StructureException(
                f"Range expects between 1 and 2 arguments, got {len(self.stmt.iter.args)}",
                self.stmt.iter.func
            )

        block_scope_id = id(self.stmt)
        with self.context.make_blockscope(block_scope_id):
            # Get arg0
            arg0 = self.stmt.iter.args[0]
            num_of_args = len(self.stmt.iter.args)

            # Type 1 for, e.g. for i in range(10): ...
            if num_of_args == 1:
                arg0_val = self._get_range_const_value(arg0)
                start = LLLnode.from_list(0, typ='int128', pos=getpos(self.stmt))
                rounds = arg0_val

            # Type 2 for, e.g. for i in range(100, 110): ...
            elif self._check_valid_range_constant(self.stmt.iter.args[1], raise_exception=False)[0]:
                arg0_val = self._get_range_const_value(arg0)
                arg1_val = self._get_range_const_value(self.stmt.iter.args[1])
                start = LLLnode.from_list(arg0_val, typ='int128', pos=getpos(self.stmt))
                rounds = LLLnode.from_list(arg1_val - arg0_val, typ='int128', pos=getpos(self.stmt))

            # Type 3 for, e.g. for i in range(x, x + 10): ...
            else:
                arg1 = self.stmt.iter.args[1]
                if not isinstance(arg1, vy_ast.BinOp) or not isinstance(arg1.op, vy_ast.Add):
                    raise StructureException(
                        (
                            "Two-arg for statements must be of the form `for i "
                            "in range(start, start + rounds): ...`"
                        ),
                        arg1,
                    )

                if not vy_ast.compare_nodes(arg0, arg1.left):
                    raise StructureException(
                        (
                            "Two-arg for statements of the form `for i in "
                            "range(x, x + y): ...` must have x identical in both "
                            f"places: {vy_ast.ast_to_dict(arg0)} {vy_ast.ast_to_dict(arg1.left)}"
                        ),
                        self.stmt.iter,
                    )

                rounds = self._get_range_const_value(arg1.right)
                start = Expr.parse_value_expr(arg0, self.context)

            r = rounds if isinstance(rounds, int) else rounds.value
            if r < 1:
                raise StructureException(
                    f"For loop has invalid number of iterations ({r}),"
                    " the value must be greater than zero",
                    self.stmt.iter
                )

            varname = self.stmt.target.id
            pos = self.context.new_variable(varname, BaseType('int128'), pos=getpos(self.stmt))
            self.context.forvars[varname] = True
            o = LLLnode.from_list(
                ['repeat', pos, start, rounds, parse_body(self.stmt.body, self.context)],
                typ=None,
                pos=getpos(self.stmt),
            )
            del self.context.vars[varname]
            del self.context.forvars[varname]

        return o

    def _is_list_iter(self):
        """
        Test if the current statement is a type of list, used in for loops.
        """

        # Check for literal or memory list.
        iter_var_type = (
            self.context.vars.get(self.stmt.iter.id).typ
            if isinstance(self.stmt.iter, vy_ast.Name)
            else None
        )
        if isinstance(self.stmt.iter, vy_ast.List) or isinstance(iter_var_type, ListType):
            return True

        # Check for storage list.
        if isinstance(self.stmt.iter, vy_ast.Attribute):
            iter_var_type = self.context.globals.get(self.stmt.iter.attr)
            if iter_var_type and isinstance(iter_var_type.typ, ListType):
                return True

        return False

    def parse_for_list(self):
        with self.context.range_scope():
            iter_list_node = Expr(self.stmt.iter, self.context).lll_node
        if not isinstance(iter_list_node.typ.subtype, BaseType):  # Sanity check on list subtype.
            raise StructureException('For loops allowed only on basetype lists.', self.stmt.iter)
        iter_var_type = (
            self.context.vars.get(self.stmt.iter.id).typ
            if isinstance(self.stmt.iter, vy_ast.Name)
            else None
        )
        subtype = iter_list_node.typ.subtype.typ
        varname = self.stmt.target.id
        value_pos = self.context.new_variable(
            varname,
            BaseType(subtype),
        )
        i_pos_raw_name = '_index_for_' + varname
        i_pos = self.context.new_internal_variable(
                i_pos_raw_name,
                BaseType(subtype),
                )
        self.context.forvars[varname] = True

        # Is a list that is already allocated to memory.
        if iter_var_type:

            list_name = self.stmt.iter.id
            # make sure list cannot be altered whilst iterating.
            with self.context.in_for_loop_scope(list_name):
                iter_var = self.context.vars.get(self.stmt.iter.id)
                if iter_var.location == 'calldata':
                    fetcher = 'calldataload'
                elif iter_var.location == 'memory':
                    fetcher = 'mload'
                else:
                    raise CompilerPanic(
                        f'List iteration only supported on in-memory types {self.expr}',
                    )
                body = [
                    'seq',
                    [
                        'mstore',
                        value_pos,
                        [fetcher, ['add', iter_var.pos, ['mul', ['mload', i_pos], 32]]],
                    ],
                    parse_body(self.stmt.body, self.context)
                ]
                o = LLLnode.from_list(
                    ['repeat', i_pos, 0, iter_var.size, body], typ=None, pos=getpos(self.stmt)
                )

        # List gets defined in the for statement.
        elif isinstance(self.stmt.iter, vy_ast.List):
            # Allocate list to memory.
            count = iter_list_node.typ.count
            tmp_list = LLLnode.from_list(
                obj=self.context.new_placeholder(ListType(iter_list_node.typ.subtype, count)),
                typ=ListType(iter_list_node.typ.subtype, count),
                location='memory'
            )
            setter = make_setter(tmp_list, iter_list_node, 'memory', pos=getpos(self.stmt))
            body = [
                'seq',
                ['mstore', value_pos, ['mload', ['add', tmp_list, ['mul', ['mload', i_pos], 32]]]],
                parse_body(self.stmt.body, self.context)
            ]
            o = LLLnode.from_list(
                ['seq',
                    setter,
                    ['repeat', i_pos, 0, count, body]], typ=None, pos=getpos(self.stmt)
            )

        # List contained in storage.
        elif isinstance(self.stmt.iter, vy_ast.Attribute):
            count = iter_list_node.typ.count
            list_name = iter_list_node.annotation

            # make sure list cannot be altered whilst iterating.
            with self.context.in_for_loop_scope(list_name):
                body = [
                    'seq',
                    [
                        'mstore',
                        value_pos,
                        ['sload', ['add', ['sha3_32', iter_list_node], ['mload', i_pos]]]
                    ],
                    parse_body(self.stmt.body, self.context),
                ]
                o = LLLnode.from_list(
                    ['seq',
                        ['repeat', i_pos, 0, count, body]], typ=None, pos=getpos(self.stmt)
                )

        del self.context.vars[varname]
        # this kind of open access to the vars dict should be disallowed.
        # we should use member functions to provide an API for these kinds
        # of operations.
        del self.context.vars[self.context._mangle(i_pos_raw_name)]
        del self.context.forvars[varname]
        return o

    def aug_assign(self):
        target = self.get_target(self.stmt.target)
        sub = Expr.parse_value_expr(self.stmt.value, self.context)
        if not isinstance(
            self.stmt.op, (vy_ast.Add, vy_ast.Sub, vy_ast.Mult, vy_ast.Div, vy_ast.Mod)
        ):
            raise StructureException("Unsupported operator for augassign", self.stmt)
        if not isinstance(target.typ, BaseType):
            raise TypeMismatch(
                "Can only use aug-assign operators with simple types!", self.stmt.target
            )
        if target.location == 'storage':
            o = Expr.parse_value_expr(
                vy_ast.BinOp(
                    left=LLLnode.from_list(['sload', '_stloc'], typ=target.typ, pos=target.pos),
                    right=sub,
                    op=self.stmt.op,
                    lineno=self.stmt.lineno,
                    col_offset=self.stmt.col_offset,
                    end_lineno=self.stmt.end_lineno,
                    end_col_offset=self.stmt.end_col_offset,
                ),
                self.context,
            )
            return LLLnode.from_list([
                'with', '_stloc', target, [
                    'sstore',
                    '_stloc',
                    base_type_conversion(o, o.typ, target.typ, pos=getpos(self.stmt)),
                ],
            ], typ=None, pos=getpos(self.stmt))
        elif target.location == 'memory':
            o = Expr.parse_value_expr(
                vy_ast.BinOp(
                    left=LLLnode.from_list(['mload', '_mloc'], typ=target.typ, pos=target.pos),
                    right=sub,
                    op=self.stmt.op,
                    lineno=self.stmt.lineno,
                    col_offset=self.stmt.col_offset,
                    end_lineno=self.stmt.end_lineno,
                    end_col_offset=self.stmt.end_col_offset,
                ),
                self.context,
            )
            return LLLnode.from_list([
                'with', '_mloc', target, [
                    'mstore',
                    '_mloc',
                    base_type_conversion(o, o.typ, target.typ, pos=getpos(self.stmt)),
                ],
            ], typ=None, pos=getpos(self.stmt))

    def parse_continue(self):
        return LLLnode.from_list('continue', typ=None, pos=getpos(self.stmt))

    def parse_break(self):
        return LLLnode.from_list('break', typ=None, pos=getpos(self.stmt))

    def parse_return(self):
        if self.context.return_type is None:
            if self.stmt.value:
                raise TypeMismatch("Not expecting to return a value", self.stmt)
            return LLLnode.from_list(
                make_return_stmt(self.stmt, self.context, 0, 0),
                typ=None,
                pos=getpos(self.stmt),
                valency=0,
            )
        if not self.stmt.value:
            raise TypeMismatch("Expecting to return a value", self.stmt)

        sub = Expr(self.stmt.value, self.context).lll_node

        # Returning a value (most common case)
        if isinstance(sub.typ, BaseType):
            sub = unwrap_location(sub)

            if self.context.return_type != sub.typ and not sub.typ.is_literal:
                raise TypeMismatch(
                    f"Trying to return base type {sub.typ}, output expecting "
                    f"{self.context.return_type}",
                    self.stmt.value,
                )
            elif sub.typ.is_literal and (self.context.return_type.typ == sub.typ or 'int' in self.context.return_type.typ and 'int' in sub.typ.typ):  # noqa: E501
                if not SizeLimits.in_bounds(self.context.return_type.typ, sub.value):
                    raise InvalidLiteral(
                        "Number out of range: " + str(sub.value),
                        self.stmt
                    )
                else:
                    return LLLnode.from_list(
                        [
                            'seq',
                            ['mstore', 0, sub],
                            make_return_stmt(self.stmt, self.context, 0, 32)
                        ],
                        typ=None,
                        pos=getpos(self.stmt),
                        valency=0,
                    )
            elif is_base_type(sub.typ, self.context.return_type.typ) or (is_base_type(sub.typ, 'int128') and is_base_type(self.context.return_type, 'int256')):  # noqa: E501
                return LLLnode.from_list(
                    ['seq', ['mstore', 0, sub], make_return_stmt(self.stmt, self.context, 0, 32)],
                    typ=None,
                    pos=getpos(self.stmt),
                    valency=0,
                )
            else:
                raise TypeMismatch(
                    f"Unsupported type conversion: {sub.typ} to {self.context.return_type}",
                    self.stmt.value,
                )
        # Returning a byte array
        elif isinstance(sub.typ, ByteArrayLike):
            if not sub.typ.eq_base(self.context.return_type):
                raise TypeMismatch(
                    f"Trying to return base type {sub.typ}, output expecting "
                    f"{self.context.return_type}",
                    self.stmt.value,
                )
            if sub.typ.maxlen > self.context.return_type.maxlen:
                raise TypeMismatch(
                    f"Cannot cast from greater max-length {sub.typ.maxlen} to shorter "
                    f"max-length {self.context.return_type.maxlen}",
                    self.stmt.value,
                )

            # loop memory has to be allocated first.
            loop_memory_position = self.context.new_placeholder(typ=BaseType('uint256'))
            # len & bytez placeholder have to be declared after each other at all times.
            len_placeholder = self.context.new_placeholder(typ=BaseType('uint256'))
            bytez_placeholder = self.context.new_placeholder(typ=sub.typ)

            if sub.location in ('storage', 'memory'):
                return LLLnode.from_list([
                    'seq',
                    make_byte_array_copier(
                        LLLnode(bytez_placeholder, location='memory', typ=sub.typ),
                        sub,
                        pos=getpos(self.stmt)
                    ),
                    zero_pad(bytez_placeholder),
                    ['mstore', len_placeholder, 32],
                    make_return_stmt(
                        self.stmt,
                        self.context,
                        len_placeholder,
                        ['ceil32', ['add', ['mload', bytez_placeholder], 64]],
                        loop_memory_position=loop_memory_position,
                    )
                ], typ=None, pos=getpos(self.stmt), valency=0)
            else:
                raise Exception(f"Invalid location: {sub.location}")

        elif isinstance(sub.typ, ListType):
            loop_memory_position = self.context.new_placeholder(typ=BaseType('uint256'))
            if sub.typ != self.context.return_type:
                raise TypeMismatch(
                    f"List return type {sub.typ} does not match specified "
                    f"return type, expecting {self.context.return_type}",
                    self.stmt
                )
            elif sub.location == "memory" and sub.value != "multi":
                return LLLnode.from_list(
                    make_return_stmt(
                        self.stmt,
                        self.context,
                        sub,
                        get_size_of_type(self.context.return_type) * 32,
                        loop_memory_position=loop_memory_position,
                    ),
                    typ=None,
                    pos=getpos(self.stmt),
                    valency=0,
                )
            else:
                new_sub = LLLnode.from_list(
                    self.context.new_placeholder(self.context.return_type),
                    typ=self.context.return_type,
                    location='memory',
                )
                setter = make_setter(new_sub, sub, 'memory', pos=getpos(self.stmt))
                return LLLnode.from_list([
                    'seq',
                    setter,
                    make_return_stmt(
                        self.stmt,
                        self.context,
                        new_sub,
                        get_size_of_type(self.context.return_type) * 32,
                        loop_memory_position=loop_memory_position,
                    )
                ], typ=None, pos=getpos(self.stmt))

        # Returning a struct
        elif isinstance(sub.typ, StructType):
            retty = self.context.return_type
            if not isinstance(retty, StructType) or retty.name != sub.typ.name:
                raise TypeMismatch(
                    f"Trying to return {sub.typ}, output expecting {self.context.return_type}",
                    self.stmt.value,
                )
            return gen_tuple_return(self.stmt, self.context, sub)

        # Returning a tuple.
        elif isinstance(sub.typ, TupleType):
            if not isinstance(self.context.return_type, TupleType):
                raise TypeMismatch(
                    f"Trying to return tuple type {sub.typ}, output expecting "
                    f"{self.context.return_type}",
                    self.stmt.value,
                )

            if len(self.context.return_type.members) != len(sub.typ.members):
                raise StructureException("Tuple lengths don't match!", self.stmt)

            # check return type matches, sub type.
            for i, ret_x in enumerate(self.context.return_type.members):
                s_member = sub.typ.members[i]
                sub_type = s_member if isinstance(s_member, NodeType) else s_member.typ
                if type(sub_type) is not type(ret_x):
                    raise StructureException(
                        "Tuple return type does not match annotated return. "
                        f"{type(sub_type)} != {type(ret_x)}",
                        self.stmt
                    )
            return gen_tuple_return(self.stmt, self.context, sub)

        else:
            raise TypeMismatch(f"Can't return type {sub.typ}", self.stmt)

    def get_target(self, target):
        # Check if we are doing assignment of an iteration loop.
        if isinstance(target, vy_ast.Subscript) and self.context.in_for_loop:
            raise_exception = False
            if isinstance(target.value, vy_ast.Attribute):
                list_name = f"{target.value.value.id}.{target.value.attr}"
                if list_name in self.context.in_for_loop:
                    raise_exception = True

            if isinstance(target.value, vy_ast.Name) and \
               target.value.id in self.context.in_for_loop:
                list_name = target.value.id
                raise_exception = True

            if raise_exception:
                raise StructureException(
                    f"Altering list '{list_name}' which is being iterated!",
                    self.stmt,
                )

        if isinstance(target, vy_ast.Name) and target.id in self.context.forvars:
            raise StructureException(
                f"Altering iterator '{target.id}' which is in use!",
                self.stmt,
            )
        if isinstance(target, vy_ast.Tuple):
            target = Expr(target, self.context).lll_node
            for node in target.args:
                constancy_checks(node, self.context, self.stmt)
            return target

        target = Expr.parse_variable_location(target, self.context)
        constancy_checks(target, self.context, self.stmt)
        return target


# Parse a statement (usually one line of code but not always)
def parse_stmt(stmt, context):
    return Stmt(stmt, context).lll_node


# Parse a piece of code
def parse_body(code, context):
    if not isinstance(code, list):
        return parse_stmt(code, context)

    o = ['seq']
    for stmt in code:
        lll = parse_stmt(stmt, context)
        o.append(lll)
    o.append('pass')  # force zerovalent, even last statement
    return LLLnode.from_list(o, pos=getpos(code[0]) if code else None)


def constancy_checks(node, context, stmt):
    if node.location == 'storage' and context.is_constant():
        raise ConstancyViolation(
            f"Cannot modify storage inside {context.pp_constancy()}: {node.annotation}",
            stmt,
        )
    if not node.mutable:
        raise ConstancyViolation(
            f"Cannot modify function argument: {node.annotation}",
            stmt,
        )
