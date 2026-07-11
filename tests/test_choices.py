import dataclasses
import enum
from typing import Literal

from assertpy2 import assert_that
from pytest import raises

from docopt2 import DocoptExit, docopt

_LEVEL_DOC = "Usage: prog --level=<lvl>\n\nOptions:\n  --level=<lvl>  Level [default: info]."


@dataclasses.dataclass
class _Levelled:
    level: Literal["debug", "info", "warn"]


def test_literal_accepts_a_declared_choice():
    assert_that(docopt(_LEVEL_DOC, "--level=warn", complete=False, schema=_Levelled).level).is_equal_to("warn")


def test_literal_rejects_an_undeclared_value_and_lists_the_choices():
    with raises(DocoptExit) as exc_info:
        docopt(_LEVEL_DOC, "--level=trace", complete=False, schema=_Levelled)
    message = str(exc_info.value)
    assert_that(message).contains("invalid value for `--level`")
    assert_that(message).contains("expected one of `debug`, `info`, `warn`")  # caret label lists the valid set
    assert_that(message).contains("`trace` is not one of `debug`, `info`, `warn`")  # help reads naturally


@dataclasses.dataclass
class _OptionalLevel:
    level: Literal["debug", "info"] | None


def test_optional_literal_left_absent_is_none():
    doc = "Usage: prog [--level=<lvl>]\n\nOptions:\n  --level=<lvl>  Level."
    assert_that(docopt(doc, "", complete=False, schema=_OptionalLevel).level).is_none()


class _Color(enum.Enum):
    RED = "red"
    GREEN = "green"


@dataclasses.dataclass
class _Painted:
    color: _Color


def test_enum_rejection_also_lists_the_member_values():
    with raises(DocoptExit) as exc_info:
        docopt("Usage: prog <color>", "purple", complete=False, schema=_Painted)
    message = str(exc_info.value)
    assert_that(message).contains("expected one of `red`, `green`")
    assert_that(message).contains("`purple` is not one of `red`, `green`")


@dataclasses.dataclass
class _Tags:
    tags: list[Literal["a", "b", "c"]]


def test_list_of_literals_coerces_each_element():
    assert_that(docopt("Usage: prog <tags>...", "a c a", complete=False, schema=_Tags).tags).is_equal_to(
        ["a", "c", "a"]
    )
