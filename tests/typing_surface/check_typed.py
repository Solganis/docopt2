# Not a pytest module (no test_ prefix); verified by running mypy/pyright/ty over it.
# assert_type fails the checker if the inferred type is wrong.
from __future__ import annotations

import dataclasses

import pydantic
from typing_extensions import assert_type  # 3.10-safe; understood by all checkers

from docopt2 import Arguments, Cli, docopt


@dataclasses.dataclass
class Args:
    host: str
    port: int


# schema= overload narrows the result to the schema type.
typed = docopt("Usage: prog <host> <port>", "h 80", schema=Args)
assert_type(typed, Args)
assert_type(typed.port, int)

# No schema -> the back-compat Arguments mapping, with typed provenance/surplus accessors.
untyped = docopt("Usage: prog <host>", "h")
assert_type(untyped, Arguments)
assert_type(untyped.provided, "frozenset[str]")
assert_type(untyped.extra, "list[str]")
assert_type(untyped.was_given("<host>"), bool)


# The Cli base class: parse() returns the concrete subclass (Self), fully typed.
class Server(Cli):
    __cli_doc__ = "Usage: prog <host> <port>"
    host: str
    port: int


server = Server.parse("h 80")
assert_type(server, Server)
assert_type(server.host, str)


# A pydantic model as schema narrows the same way.
class PydArgs(pydantic.BaseModel):
    host: str
    port: int


pyd = docopt("Usage: prog <host> <port>", "h 80", schema=PydArgs)
assert_type(pyd, PydArgs)
