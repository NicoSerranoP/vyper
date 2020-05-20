import io
import re
from tokenize import (
    COMMENT,
    NAME,
    OP,
    NEWLINE,
    NL,
    TokenError,
    TokenInfo,
    tokenize,
    untokenize,
)
from typing import Sequence, Tuple

from vyper.exceptions import SyntaxException, VersionException
from vyper.typing import ClassTypes, ParserPosition

VERSION_RE = re.compile(r"^(\d+\.)(\d+\.)(\w*)$")


def _parse_version_str(version_str: str, start: ParserPosition) -> Sequence[str]:
    match = VERSION_RE.match(version_str)

    if match is None:
        raise VersionException(
            f'Could not parse given version string "{version_str}"', start,
        )

    return match.groups()


def validate_version_pragma(version_str: str, start: ParserPosition) -> None:
    """
    Validates a version pragma directive against the current compiler version.
    """
    from vyper import __version__

    version_arr = version_str.split("@version")

    file_version = version_arr[1].strip()
    file_major, file_minor, file_patch = _parse_version_str(file_version, start)
    compiler_major, compiler_minor, compiler_patch = _parse_version_str(
        __version__, start
    )

    if (file_major, file_minor) != (compiler_major, compiler_minor):
        raise VersionException(
            f'File version "{file_version}" is not compatible '
            f'with compiler version "{__version__}"',
            start,
        )


VYPER_CLASS_TYPES = {
    "contract",
    "struct",
}


def pre_parse(code: str) -> Tuple[ClassTypes, str]:
    """
    Re-formats a vyper source string into a python source string and performs
    some validation.  More specifically,

    * Translates "contract" and "struct" keyword into python "class" keyword
    * Validates "@version" pragma against current compiler version
    * Prevents direct use of python "class" keyword
    * Prevents use of python semi-colon statement separator

    Also returns a mapping of detected contract and struct names to their
    respective vyper class types ("contract" or "struct").

    Parameters
    ----------
    code : str
        The vyper source code to be re-formatted.

    Returns
    -------
    dict
        Mapping of class types for the given source.
    str
        Reformatted python source string.
    """
    result = []
    unlocked_functions = []
    previous_keyword = None
    pk = None
    '''sl = 0
    sc = 0
    '''
    class_types: ClassTypes = {}

    try:
        code_bytes = code.encode("utf-8")
        g = tokenize(io.BytesIO(code_bytes).readline)

        for token in g:
            toks = [token]
            typ = token.type
            string = token.string
            start = token.start
            end = token.end
            line = token.line

            if typ == COMMENT and "@version" in string:
                validate_version_pragma(string[1:], start)

            if typ == NAME and string == "class" and start[1] == 0:
                raise SyntaxException(
                    "The `class` keyword is not allowed. Perhaps you meant `contract` or `struct`?",
                    code,
                    start[0],
                    start[1],
                )

            # Make note of contract or struct name along with the type keyword
            # that preceded it
            if typ == NAME and previous_keyword is not None:
                class_types[string] = previous_keyword
                previous_keyword = None

            # Translate vyper-specific class keywords into python "class"
            # keyword
            if typ == NAME and string in VYPER_CLASS_TYPES and start[1] == 0:
                toks = [TokenInfo(NAME, "class", start, end, line)]
                previous_keyword = string

            if (typ, string) == (OP, ";"):
                raise SyntaxException(
                    "Semi-colon statements not allowed", code, start[0], start[1]
                )
            #This is code added for programming languages-----------------------
            if (typ, string) == (NAME, "unlock"):
                pk = string
                '''sl = start[0]
                sc = start[1]
                cont = 0
                '''
                continue
            if (typ, string, pk) == (OP, "[", "unlock"):
                continue
            if (typ, pk) == (NAME, "unlock"):
                unlocked_functions.extend([string])
                #Insert the flag activator for that function here
                '''new_name = "ul_" + string
                len_name = len(new_name)
                new_line = "self." + new_name + " = True\n"
                self_line = [TokenInfo(NAME, "self", (sl,sc), (sl,sc+4), new_line)]
                sc = sc + 4
                result.extend(self_line)
                dot = [TokenInfo(OP, ".", (sl,sc), (sl,sc+1), new_line)]
                sc = sc + 1
                result.extend(dot)
                unlock_name = [TokenInfo(NAME, new_name, (sl,sc), (sl,sc+len_name), new_line)]
                sc = sc + len_name
                result.extend(unlock_name)
                cont = cont + 1
                '''
                continue
            if (typ, string, pk) == (OP, ",", "unlock"):
                '''comma = [TokenInfo(OP, "=", (sl,sc), (sl,sc+1), new_line)]
                sc = sc + 1
                result.extend(comma)
                '''
                continue
            if (typ, string, pk) == (OP, "]", "unlock"):
                continue
            if (typ, string, pk) == (NEWLINE, "\n", "unlock"):
                '''if (cont!=0):
                    equal = [TokenInfo(OP, "=", (sl,sc), (sl,sc+1), new_line)]
                    sc = sc + 1
                    result.extend(equal)
                    true = [TokenInfo(NAME, "True", (sl,sc), (sl,sc+4), new_line)]
                    sc = sc + 4
                    result.extend(true)
                    space = [TokenInfo(NEWLINE, "\n", (sl,sc), (sl,sc+1), new_line)]
                    sc = sc + 1
                    result.extend(space)
                sl = 0
                sc = 0
                cont = 0
                '''
                pk = None
                continue
            #The added code end here--------------------------------------------
            result.extend(toks)
        #for r in result:
            #print(r)
    except TokenError as e:
        raise SyntaxException(e.args[0], code, e.args[1][0], e.args[1][1]) from e

    return class_types, unlocked_functions, untokenize(result).decode("utf-8")
