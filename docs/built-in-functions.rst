.. index:: function, built-in;

.. _built_in_functions:

Built in Functions
******************

Vyper provides a collection of built in functions available in the global namespace of all
contracts.

.. _functions:

.. py:function:: floor(value: decimal) -> int128

    Rounds a decimal down to the nearest integer.

    * ``value``: Decimal value to round down

.. py:function:: ceil(value: decimal) -> int128

    Rounds a decimal up to the nearest integer.

    * ``value``: Decimal value to round up

.. py:function:: convert(value, type_) -> Any

    Converts a variable or literal from one type to another.

    * ``value``: Value to convert
    * ``type_``: The destination type to convert to (``bool``, ``decimal``, ``int128``, ``uint256`` or ``bytes32``)

    Returns a value of the type specified by ``type_``.

    For more details on available type conversions, see :ref:`type_conversions`.

.. py:function:: empty(typename) -> Any

    Returns a value which is the default (zeroed) value of its type.

    * ``typename``: Name of the type

    For instance, `xs: uint256[5] = empty(uint256[5])`

.. py:function:: as_wei_value(value: int, unit: str) -> uint256

    Takes an amount of ether currency specified by a number and a unit and returns the integer quantity of wei equivalent to that amount.

    * ``value``: Value for the ether unit
    * ``unit``: Ether unit name (e.g. ``"wei"``, ``"ether"``, ``"gwei"``, etc.) indicating the denomination of ``value``.

.. py:function:: slice(b: bytes, start: int128, length: int128) -> bytes

    Copies a list of bytes and returns a specified slice.

    * ``b``: ``bytes`` or ``bytes32`` to be sliced
    * ``start``: start position of the slice
    * ``length``: length of the slice

.. py:function:: len(b: bytes) -> int128

    Returns the length of a given ``bytes`` list.

.. py:function:: concat(a, b, *args) -> bytes

    Takes 2 or more bytes arrays of type ``bytes32`` or ``bytes`` and combines them into a single ``bytes`` list.

.. py:function:: keccak256(value) -> bytes32

    Returns a ``keccak256`` hash of the given value.

    * ``value``: Value to hash. Can be ``str_literal``, ``bytes``, or ``bytes32``.

.. py:function:: sha256(value) -> bytes32

    Returns a ``sha256`` (SHA2 256bit output) hash of the given value.

    * ``value``: Value to hash. Can be ``str_literal``, ``bytes``, or ``bytes32``.

.. py:function:: uint256_addmod(a: uint256, b: uint256, c: uint256) -> uint256

    Returns the modulo of ``(a + b) % c``. Reverts if ``c == 0``.

.. py:function:: uint256_mulmod(a: uint256, b: uint256, c: uint256) -> uint256

    Returns the modulo from ``(a * b) % c``. Reverts if ``c == 0``.

.. py:function:: sqrt(d: decimal) -> decimal

    Returns the square root of the provided decimal number, using the Babylonian square root algorithm.

.. py:function:: method_id(method, type_) -> Union[bytes32, bytes[4]]

    Takes a function declaration and returns its method_id (used in data field to call it).

    * ``method``: Method declaration as ``str_literal``
    * ``type_``: Type of output (``bytes32`` or ``bytes[4]``)

    Returns a value of the type specified by ``type_``.

.. py:function:: ecrecover(hash: bytes32, v: uint256, r: uint256, s: uint256) -> address

    Recovers the address associated with the public key from the given elliptic curve signature.

    * ``r``: first 32 bytes of signature
    * ``s``: second 32 bytes of signature
    * ``v``: final 1 byte of signature

    Returns the associated address, or ``0`` on error.

.. py:function:: ecadd(a: uint256[2], b: uint256[2]) -> uint256[2]

    Takes two points on the Alt-BN128 curve and adds them together.

.. py:function:: ecmul(point: uint256[2], scalar: uint256) -> uint256[2]

    Takes a point on the Alt-BN128 curve (``p``) and a scalar value (``s``), and returns the result of adding the point to itself ``s`` times, i.e. ``p * s``.

    * ``point``: Point to be multiplied
    * ``scalar``: Scalar value

.. py:function:: extract32(b: bytes, start: int128, type_=bytes32) -> Union[bytes32, int128, address]

    Extracts a value from a ``bytes`` list.

    * ``b``: ``bytes`` list to extract from
    * ``start``: Start point to extract from
    * ``type_``: Type of output (``bytes32``, ``int128``, or ``address``). Defaults to ``bytes32``.

    Returns a value of the type specified by ``type_``.

Low Level Built in Functions
****************************

Vyper contains a set of built in functions which execute opcodes such as ``SEND`` or ``SELFDESTRUCT``.

.. py:function:: send(to: address, value: uint256) -> None

    Sends ether from the contract to the specified Ethereum address.

    * ``to``: The destination address to send ether to
    * ``value``: The wei value to send to the address

    .. note::

        The amount to send is always specified in ``wei``.

.. py:function:: raw_call(to: address, data: bytes, outsize: int = 0, gas: uint256 = gasLeft, value: uint256 = 0, is_delegate_call: bool = False, is_static_call: bool = False) -> bytes[outsize]

    Calls to the specified Ethereum address.

    * ``to``: Destination address to call to
    * ``data``: Data to send to the destination address
    * ``outsize``: Maximum length of the bytes array returned from the call. If the returned call data exceeds this length, only this number of bytes is returned.
    * ``gas``: The amount of gas to attach to the call. If not set, all remainaing gas is forwarded.
    * ``value``: The wei value to send to the address (Optional, default ``0``)
    * ``is_delegate_call``: If ``True``, the call will be sent as ``DELEGATECALL`` (Optional, default ``False``)
    * ``is_static_call``: If ``True``, the call will be sent as ``STATICCALL`` (Optional, default ``False``)

    Returns the data returned by the call as a ``bytes`` list, with ``outsize`` as the max length.

    Returns ``None`` if ``outsize`` is omitted or set to ``0``.

.. py:function:: selfdestruct(to: address) -> None

    Triggers the ``SELFDESTRUCT`` opcode (``0xFF``), causing the contract to be destroyed.

    * ``to``: Address to forward the contract's ether balance to

    .. warning::

        This method will delete the contract from the Ethereum blockchain. All non-ether assets associated with this contract will be "burned" and the contract will be inaccessible.

.. py:function:: raise(reason: str) -> None

    Raises an exception.

    * ``reason``: The exception reason (must be <= 32 bytes)

    This method triggers the ``REVERT`` opcode (``0xFD``) with the provided reason given as the error message. The code will stop operation, the contract's state will be reverted to the state before the transaction took place and the remaining gas will be returned to the transaction's sender.

    .. note::

        To give it a more Python-like syntax, the raise function can be called without parenthesis, the syntax would be ``raise "An exception"``. Even though both options will compile, it's recommended to use the Pythonic version without parentheses.

.. py:function:: assert(cond: bool, reason: str = None) -> None

    Asserts the specified condition.

    * ``cond``: The boolean condition to assert
    * ``reason``: The exception reason (must be <= 32 bytes)

    This method's behavior is equivalent to:

    .. code-block:: python

        if not cond:
            raise reason

    The only difference in behavior is that ``assert`` can be called without a reason string, while ``raise`` requires one.

    If the reason string is set to ``UNREACHABLE``, an ``INVALID`` opcode (``0xFE``) will be used instead of ``REVERT``. In this case, calls that revert will not receive a gas refund.

    You cannot directly ``assert`` the result of a non-constant function call. The proper pattern for doing so is to assign the result to a memory variable, and then call assert on that variable. Alternatively, use the :ref:`assert_modifiable<assert-modifiable>` method.

    .. note::

        To give it a more Python-like syntax, the assert function can be called without parenthesis, the syntax would be ``assert your_bool_condition``. Even though both options will compile, it's recommended to use the Pythonic version without parenthesis.

.. _assert-modifiable:

.. py:function:: assert_modifiable(cond: bool) -> None

    Asserts a specified condition, without checking for constancy on a callable condition.

    * ``cond``: The boolean condition to assert

    Use ``assert_modifiable`` in place of ``assert`` when you wish to directly assert the result of a potentially state-changing call.

    For example, a common use case is verifying the results of an ERC20 token transfer:

    .. code-block:: python

        @public
        def transferTokens(token: address, to: address, amount: uint256) -> bool:
            assert_modifiable(ERC20(token).transfer(to, amount))
            return True

.. py:function:: raw_log(topics: bytes32[4], data: bytes) -> None

    Provides low level access to the ``LOG`` opcodes, emitting a log without having to specify an ABI type.

    * ``topics``: List of ``bytes32`` log topics
    * ``data``: Unindexed event data to include in the log, bytes or bytes32

    This method provides low-level access to the ``LOG`` opcodes (``0xA0``..``0xA4``). The length of ``topics`` determines which opcode will be used. ``topics`` is a list of bytes32 topics that will be indexed. The remaining unindexed parameters can be placed in the ``data`` parameter.


.. py:function:: create_forwarder_to(target: address, value: uint256 = 0) -> address

    Duplicates a contract's code and deploys it as a new instance, by means of a ``DELEGATECALL``.

    * ``target``: Address of the contract to duplicate
    * ``value``: The wei value to send to the new contract address (Optional, default 0)

    Returns the address of the duplicated contract.

.. py:function:: blockhash(block_num: uint256) -> bytes32

    Returns the hash of the block at the specified height.

    .. note::

        The EVM only provides access to the most 256 blocks. This function will return 0 if the block number is greater than or equal to the current block number or more than 256 blocks behind the current block.
