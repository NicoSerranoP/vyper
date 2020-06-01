# Just show the steps
# In aleth/build/aleth-vm
# aleth-vm trace --code 60026000556001600055

# Print the opcode of each step
# aleth-vm trace --mnemonics --code 60026000556001600055

# To run this code
# 1) activate virtual machine: source ~/vyper-env/bin/activate
# 2) run with python3: python3 -i nicoMain.py

import ast as python_ast
from vyper.ast.pre_parser import pre_parse
from vyper.compiler.phases import CompilerData
from vyper.compiler import compile_code

# Open the file
path = '/home/kiko/programming_languages/vyper/examples/safe_remote_purchase/basic.vy'
source_code = open(path, 'r')
# Tokenize and change 'contract' and 'struct' for 'class' & process 'unlock'
#class_types, unlocked_functions, reformatted_code = pre_parse(source_code.read())


# I should make 'unlock' as a python readable in order to create the AST
# Create a python AST
'''py_ast = python_ast.parse(reformatted_code)
'''

# The CompilerData obj takes care of EVERYTHING (parsing, compiling, etc)
'''compiler_data = CompilerData(source_code.read())
print("\nFunctions Definitions: ")
defs = compiler_data.global_ctx._declared_functions
for var in defs:
    print(var)
'''

# This is the main command to compile a Vyper source code
print("Trying the whole compilation process")
final = compile_code(source_code.read(), output_formats = ['abi','bytecode','source_map'] )
bytecode = final["bytecode"]
abi = final['abi']
