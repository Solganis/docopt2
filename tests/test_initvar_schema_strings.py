from __future__ import annotations

import dataclasses
import sys
from dataclasses import InitVar

from assertpy2 import assert_that

from docopt2 import DocoptLanguageError, docopt


@dataclasses.dataclass
class _Server:
    host: str
    port: InitVar[int]
    address: str = dataclasses.field(init=False)

    def __post_init__(self, port: int) -> None:
        self.address = f"{self.host}:{port + 1}"


def test_an_init_only_field_written_as_a_string_annotation_is_bound_where_typing_can_resolve_it():
    # 3.10: typing.get_type_hints refuses a string that evaluates to an InitVar, before docopt2 sees the hint
    expected = (
        {"host": "h", "address": "h:81"}
        if sys.version_info >= (3, 11)
        else "TypeError: Forward references must evaluate to types. Got dataclasses.InitVar[int]."
    )
    assert_that(_Server.__annotations__["port"]).is_equal_to("InitVar[int]")
    try:
        bound = dataclasses.asdict(docopt("Usage: prog <host> <port>", ["h", "80"], schema=_Server, complete=False))
    except (TypeError, DocoptLanguageError) as raised:
        bound = f"{type(raised).__name__}: {raised}"
    assert_that(bound).is_equal_to(expected)
