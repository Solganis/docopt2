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


def test_a_mistyped_choice_gets_a_did_you_mean_suggestion():
    with raises(DocoptExit) as exc_info:
        docopt(_LEVEL_DOC, "--level=warm", complete=False, schema=_Levelled)  # warm -> warn (one substitution)
    assert_that(str(exc_info.value)).contains("did you mean `warn`?")


def test_a_transposed_choice_is_still_suggested():
    with raises(DocoptExit) as exc_info:
        docopt(_LEVEL_DOC, "--level=inof", complete=False, schema=_Levelled)  # inof -> info (transposition)
    assert_that(str(exc_info.value)).contains("did you mean `info`?")


def test_a_value_close_to_no_choice_gets_no_suggestion():
    with raises(DocoptExit) as exc_info:
        docopt(_LEVEL_DOC, "--level=production", complete=False, schema=_Levelled)
    assert_that(str(exc_info.value)).does_not_contain("did you mean")


@dataclasses.dataclass
class _Bind:
    port: Literal[80, 443, 8080]


def test_an_int_valued_literal_coerces_the_argv_string_to_the_number():
    # argv gives the string "443", but the literals are ints; a plain membership test misses them, so
    # every int-valued Literal used to reject all input. The string is parsed to the literal's type.
    assert_that(docopt("Usage: prog <port>", "443", complete=False, schema=_Bind).port).is_equal_to(443)


def test_an_int_valued_literal_still_rejects_a_non_member():
    with raises(DocoptExit) as exc_info:
        docopt("Usage: prog <port>", "22", complete=False, schema=_Bind)  # numeric, but not a member
    assert_that(str(exc_info.value)).contains("invalid value for `<port>`")


def test_an_int_valued_literal_rejects_a_value_that_is_not_even_a_number():
    # A non-numeric string cannot be parsed to the literal's int type; the conversion raises and is
    # skipped, and the value is rejected rather than crashing.
    with raises(DocoptExit) as exc_info:
        docopt("Usage: prog <port>", "https", complete=False, schema=_Bind)
    assert_that(str(exc_info.value)).contains("invalid value for `<port>`")


class _Level(enum.IntEnum):
    LOW = 1
    HIGH = 2


@dataclasses.dataclass
class _Job:
    level: _Level


def test_an_int_enum_coerces_the_argv_string_to_its_member():
    # IntEnum members are keyed by int, so `_Level("2")` raised; the string is parsed to the member type.
    assert_that(docopt("Usage: run <level>", "2", complete=False, schema=_Job).level).is_equal_to(_Level.HIGH)


def test_an_int_enum_still_rejects_a_non_member():
    with raises(DocoptExit) as exc_info:
        docopt("Usage: run <level>", "9", complete=False, schema=_Job)
    assert_that(str(exc_info.value)).contains("invalid value for `<level>`")
