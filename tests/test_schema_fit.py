import dataclasses
import datetime
import decimal
import enum
import ipaddress
import itertools
import pathlib
import uuid
from typing import Annotated, Literal, TypedDict

import pytest
from assertpy2 import assert_that

from docopt2 import Cli, DocoptExit, DocoptLanguageError, check, docopt

try:
    from typing import NotRequired
except ImportError:  # Python 3.10
    from typing_extensions import NotRequired


class _Five(enum.Enum):
    FIVE = "5"


class _Three(enum.IntEnum):
    THREE = 3


# every element a usage can hold for a field `x`, with each argv that is tried for it. TEXT is a text the type takes
_ELEMENTS = {
    "a flag": ("Usage: app [-x]", [[], ["-x"]]),
    "a required flag": ("Usage: app -x", [["-x"]]),
    "a counted flag": ("Usage: app [-x]...", [[], ["-x"], ["-x", "-x"], ["-x", "-x", "-x"]]),
    "a required counted flag": ("Usage: app -x...", [["-x"], ["-x", "-x"], ["-x", "-x", "-x"]]),
    "a command": ("Usage: app [x]", [[], ["x"]]),
    "a required command": ("Usage: app x", [["x"]]),
    "a counted command": ("Usage: app [x]...", [[], ["x"], ["x", "x"], ["x", "x", "x"]]),
    "an option": ("Usage: app [--x=<v>]", [[], ["--x", "TEXT"]]),
    "a required option": ("Usage: app --x=<v>", [["--x", "TEXT"]]),
    "an option with a default": (
        "Usage: app [--x=<v>]\n\nOptions:\n  --x=<v>  X [default: TEXT].",
        [[], ["--x", "TEXT"]],
    ),
    "an option from the environment": (
        "Usage: app [--x=<v>]\n\nOptions:\n  --x=<v>  X [env: FIT_X].",
        [[], ["--x", "TEXT"]],
    ),
    "a repeated option": ("Usage: app [--x=<v>]...", [[], ["--x", "TEXT"], ["--x", "TEXT", "--x", "TEXT"]]),
    "a positional": ("Usage: app [<x>]", [[], ["TEXT"]]),
    "a required positional": ("Usage: app <x>", [["TEXT"]]),
    "a positional with a default": ("Usage: app [<x>]\n\nArguments:\n  <x>  X [default: TEXT].", [[], ["TEXT"]]),
    "a repeated positional": ("Usage: app <x>...", [["TEXT"], ["TEXT", "TEXT"]]),
    "an optional repeated positional": ("Usage: app [<x>...]", [[], ["TEXT"], ["TEXT", "TEXT"]]),
    "an element of one line of two": ("Usage:\n  app go <x>\n  app stop", [["go", "TEXT"], ["stop"]]),
    "an option of [options]": ("Usage: app [options]\n\nOptions:\n  --x=<v>  X.", [[], ["--x", "TEXT"]]),
}


def _is(*kinds):
    return lambda value: type(value) in kinds


def _all(kind):
    return lambda value: type(value) is list and all(type(item) is kind for item in value)


# each annotation with a text it takes and with what a value of it is, both written by hand. A bool is an int
# to every type checker, so it is one here: the one place it is not is a `Literal` of numbers.
_NONE = type(None)
_TYPES = {
    "bool": (bool, "5", _is(bool)),
    "int": (int, "5", _is(int, bool)),
    "float": (float, "5", _is(float)),
    "str": (str, "5", _is(str)),
    "Path": (pathlib.Path, "5", lambda value: isinstance(value, pathlib.Path)),
    "bool | None": (bool | None, "5", _is(bool, _NONE)),
    "int | None": (int | None, "5", _is(int, bool, _NONE)),
    "str | None": (str | None, "5", _is(str, _NONE)),
    "list[int]": (list[int], "5", _all(int)),
    "list[str]": (list[str], "5", _all(str)),
    "list": (list, "5", _is(list)),
    "list[int] | None": (list[int] | None, "5", lambda value: value is None or _all(int)(value)),
    "Literal['5']": (Literal["5"], "5", lambda value: value == "5"),
    "Literal['5'] | None": (Literal["5"] | None, "5", lambda value: value is None or value == "5"),
    "list[Literal['5']]": (list[Literal["5"]], "5", _all(str)),
    "Literal[0, 1]": (Literal[0, 1], "1", lambda value: type(value) is int and value in (0, 1)),
    "Literal[True]": (Literal[True], "True", lambda value: value is True),
    "Literal[False]": (Literal[False], "", lambda value: value is False),
    "Literal[3]": (Literal[3], "3", lambda value: type(value) is int and value == 3),
    "Literal[1, False]": (Literal[1, False], "1", lambda value: value is False or (type(value) is int and value == 1)),
    "Literal[False] | str": (Literal[False] | str, "5", lambda value: value is False or type(value) is str),
    # a count that only a later member of a union, or an Enum, names
    "Literal['a'] | Literal[3]": (
        Literal["a"] | Literal[3],
        "a",
        lambda value: value == "a" or (value == 3 and type(value) is int),
    ),
    "an IntEnum of 3": (_Three, "3", lambda value: value is _Three.THREE),
    # one and two are asked beside the count the type names
    "Literal[3] | str": (
        Literal[3] | str,
        "5",
        lambda value: type(value) is str or (value == 3 and type(value) is int),
    ),
    # a flag's `True` equals the literal `1` and is no `1`
    "str | Literal[1]": (
        str | Literal[1],
        "5",
        lambda value: type(value) is str or (value == 1 and type(value) is int),
    ),
    "an Enum": (_Five, "5", lambda value: value is _Five.FIVE),
    "UUID": (uuid.UUID, "12345678-1234-5678-1234-567812345678", lambda value: isinstance(value, uuid.UUID)),
    "datetime": (datetime.datetime, "2026-10-11T09:00", lambda value: isinstance(value, datetime.datetime)),
    "Decimal": (decimal.Decimal, "5", lambda value: isinstance(value, decimal.Decimal)),
    "IPv4Address": (ipaddress.IPv4Address, "5", lambda value: isinstance(value, ipaddress.IPv4Address)),
    "IPv4Address | None": (ipaddress.IPv4Address | None, "5", _is(_NONE)),
    "int | str": (int | str, "5", _is(int, bool, str)),
    "str | int | None": (str | int | None, "5", _is(int, bool, str, _NONE)),
    "list[int] | int": (list[int] | int, "5", lambda value: type(value) in (int, bool) or _all(int)(value)),
    "Annotated[int, ...]": (Annotated[int, "why"], "5", _is(int, bool)),
    "Annotated[str | None, ...]": (Annotated[str | None, "why"], "5", _is(str, _NONE)),
    "Annotated[bool, ...] | None": (Annotated[bool, "why"] | None, "5", _is(bool, _NONE)),
}


def _outcomes(doc, argvs, annotation, is_a):
    """What binding does on each of ``argvs`` that the usage accepts: `binds`, `mistyped` where the field got a
    value that is not of its annotation, `refused` where the binder turned the argv away as the user's,
    `schema` where it raised the error of a schema."""
    schema = dataclasses.make_dataclass("Schema", [("x", annotation)])
    told = []
    for argv in argvs:
        docopt(doc, argv, complete=False, help=False)
        try:
            bound = docopt(doc, argv, schema=schema, complete=False, help=False)
        except DocoptLanguageError:
            told.append("schema")
        except DocoptExit:
            told.append("refused")
        else:
            told.append("binds" if is_a(bound.x) else "mistyped")
    return told


def _is_a_defect(element, annotation, outcomes):
    """Whether binding shows the schema to be at fault, as far as the check undertakes to say.

    It raises a schema's error on some argv. Or it hands the field a value of another type on some argv, or
    turns away a text that the annotation takes. Or, for a flag or a command, it turns away every argv there
    is: to turn away one of two is a limit the author set. A counted flag or command typed with a closed set
    is the one case the check judges by shape alone, so there only a schema's error counts."""
    yields_text = "flag" not in element and "command" not in element
    closed = "Literal" in annotation or "Enum" in annotation
    if "schema" in outcomes or ("counted" in element and closed):
        return "schema" in outcomes
    if "mistyped" in outcomes:
        return True
    return "refused" in outcomes if yields_text else "binds" not in outcomes


_GRID = list(itertools.product(_ELEMENTS, _TYPES))


@pytest.mark.parametrize(("element", "annotation"), _GRID, ids=[f"{element}: {name}" for element, name in _GRID])
def test_the_check_calls_a_field_unfit_exactly_where_binding_shows_it_to_be(element, annotation, monkeypatch):
    monkeypatch.delenv("FIT_X", raising=False)
    hint, text, is_a = _TYPES[annotation]
    doc = _ELEMENTS[element][0].replace("TEXT", text)
    argvs = [[text if token == "TEXT" else token for token in argv] for argv in _ELEMENTS[element][1]]
    outcomes = _outcomes(doc, argvs, hint, is_a)
    schema = dataclasses.make_dataclass("Schema", [("x", hint)])
    errors = [found for found in check(doc, schema=schema) if found.level == "error"]
    assert_that((bool(errors), outcomes)).is_equal_to((_is_a_defect(element, annotation, outcomes), outcomes))


@dataclasses.dataclass
class _Fits:
    go: bool
    stop: bool
    v: int
    out: pathlib.Path | None
    level: list[int]
    name: str
    mode: Literal["fast", "slow"]


_DOC = """Usage:
  app go <name> [-v]... [--out=<f>] [--level=<n>]... [--mode=<m>]
  app stop <name>

Options:
  --mode=<m>  Mode [default: fast].
"""


@dataclasses.dataclass
class _Id:
    x: uuid.UUID


def test_a_flag_handed_to_a_type_of_texts_is_refused_and_does_not_leak_what_the_type_raised():
    # `UUID(True)` raises AttributeError, which no caller of the binder expects
    assert_that(_lines("Usage: app [-x]", ["-x"], _Id)[0]).is_equal_to("error: invalid value for `-x`")
    assert_that([found.summary for found in check("Usage: app [-x]", schema=_Id)]).is_equal_to(
        ["field `x` does not fit usage element `-x`"]
    )


def test_a_schema_that_fits_has_nothing_found():
    assert_that(check(_DOC, schema=_Fits)).is_empty()


def _said(found):
    """Each finding as what a reader gets: its level and summary, the text its caret is under with the caret's
    label, and its note and help."""
    told = []
    for one in found:
        carets = [
            (snippet.source[caret.start : caret.end], caret.label)
            for snippet in one.snippets
            for caret in snippet.carets
        ]
        told.append((one.level, one.summary, carets, one.note, one.help))
    return told


@dataclasses.dataclass
class _Unfit:
    go: bool
    stop: str
    v: pathlib.Path
    out: str
    level: int
    name: list[str]
    mode: bool
    missing: int


def test_every_way_a_schema_is_unfit_is_found_at_once_with_the_element_it_is_about():
    list_note = "a repeated usage element yields a list, but the schema type int is not a list; use list[...]"
    scalar_note = (
        "the schema type list[str] is a list, but this usage element is not repeated; "
        "mark it with `...` to repeat, or use a scalar type"
    )
    flag_note = "a bool field maps to a flag, but the usage element yields the string 'x'; use a flag or str"
    assert_that(_said(check(_DOC, schema=_Unfit))).is_equal_to(
        [
            (
                "error",
                "field `stop` does not fit usage element `stop`",
                [("stop", "typed as str")],
                "the element yields `False`, which is no str",
                None,
            ),
            (
                "error",
                "field `v` does not fit usage element `-v`",
                [("-v", "typed as Path")],
                "the element yields `0`, which Path does not take",
                None,
            ),
            (
                "error",
                "usage element `--out` may be absent, but field `out` is not optional",
                [("--out=<f>", "may be absent")],
                None,
                "annotate it as `out: ... | None` or give it a default",
            ),
            (
                "error",
                "field `level` does not fit usage element `--level`",
                [("--level=<n>", "typed as int")],
                list_note,
                None,
            ),
            (
                "error",
                "field `name` does not fit usage element `<name>`",
                [("<name>", "typed as list[str]")],
                scalar_note,
                None,
            ),
            (
                "error",
                "field `mode` does not fit usage element `--mode`",
                [("--mode=<m>", "typed as bool")],
                flag_note,
                None,
            ),
            ("error", "schema field `missing` has no matching usage element", [], None, None),
        ]
    )


@dataclasses.dataclass
class _Limited:
    v: Literal[0, 1]
    q: Literal[True]


def test_an_element_that_only_the_options_shortcut_holds_is_found_with_no_place_to_show():
    doc = "Usage: app [options]\n\nOptions:\n  --out=<f>  Out."
    assert_that(_said(check(doc, schema=_Out))).is_equal_to(
        [
            (
                "error",
                "usage element `--out` may be absent, but field `out` is not optional",
                [],
                None,
                "annotate it as `out: ... | None` or give it a default",
            )
        ]
    )


def test_a_type_that_takes_some_of_what_a_flag_or_a_count_yields_is_the_authors_limit_and_no_misfit():
    assert_that(check("Usage: app [-v]... [-q]", schema=_Limited)).is_empty()


@dataclasses.dataclass
class _Third:
    v: Literal[3]


@dataclasses.dataclass
class _Never:
    q: Literal[False]


def test_a_counted_flag_typed_with_a_closed_set_is_judged_by_its_shape_alone():
    # the set is the author's limit on the count, and which counts a usage can reach is not worked out
    assert_that(check("Usage: app [-v]...", schema=_Third)).is_empty()
    assert_that(docopt("Usage: app [-v]...", ["-vvv"], schema=_Third, complete=False)).is_equal_to(_Third(v=3))
    # so a count the usage can never reach for that set is not found either: the boundary, held on purpose
    assert_that(check("Usage: app -v -v", schema=_Third)).is_empty()
    assert_that(_lines("Usage: app -v -v", ["-v", "-v"], _Third)[0]).is_equal_to("error: invalid value for `-v`")
    # a shape that is wrong whatever the count is still found
    assert_that([found.summary for found in check("Usage: app [-v]...", schema=_ThirdOfMany)]).is_equal_to(
        ["field `v` does not fit usage element `-v`"]
    )


@dataclasses.dataclass
class _ThirdOfMany:
    v: list[Literal[3]]


@dataclasses.dataclass
class _Where:
    v: pathlib.Path


@pytest.mark.parametrize(("doc", "least"), [("Usage: app [-v]...", 0), ("Usage: app -v...", 1)])
def test_a_misfit_of_a_counted_flag_names_the_least_count_the_usage_can_yield(doc, least):
    assert_that([found.note for found in check(doc, schema=_Where)]).is_equal_to(
        [f"the element yields `{least}`, which Path does not take"]
    )


def test_a_flag_the_usage_always_requires_is_never_false():
    assert_that(check("Usage: app [-q]", schema=_Never)).is_empty()
    assert_that(_said(check("Usage: app -q", schema=_Never))).is_equal_to(
        [
            (
                "error",
                "field `q` does not fit usage element `-q`",
                [("-q", "typed as one of `False`")],
                "the element yields `True`, which one of `False` does not take",
                None,
            )
        ]
    )


@dataclasses.dataclass
class _Numbered:
    flag: Literal[0, 1]
    count: Literal[True, 2]


def test_a_literal_is_matched_by_a_value_of_its_own_type():
    # `True == 1`, and a flag's `True` is still no `1`: it is bound as the literal its field names
    bound = docopt("Usage: app [--flag] [--count]...", ["--flag", "--count"], schema=_Numbered, complete=False)
    assert_that([(type(value), value) for value in dataclasses.astuple(bound)]).is_equal_to([(int, 1), (bool, True)])
    assert_that(check("Usage: app [--flag] [--count]...", schema=_Numbered)).is_empty()


class _Counting(enum.Enum):
    ONE = "one"

    @classmethod
    def _missing_(cls, value):
        _ASKED.append(value)
        return None


_ASKED: list[object] = []


@dataclasses.dataclass
class _Asked:
    x: _Counting | int | None


def test_a_union_asks_each_member_once():
    _ASKED.clear()
    assert_that(docopt("Usage: app [<x>]", ["5"], schema=_Asked, complete=False)).is_equal_to(_Asked(x=5))
    assert_that(_ASKED).is_equal_to(["5"])


@dataclasses.dataclass
class _Defaulted:
    out: str = "a.txt"
    level: int = 0


class _Keyed(TypedDict):
    out: NotRequired[str]
    level: int


def test_a_field_that_may_be_left_out_takes_an_element_that_may_be_absent():
    doc = "Usage: app [--out=<f>] [--level=<n>]"
    assert_that(check(doc, schema=_Defaulted)).is_empty()
    assert_that([found.summary for found in check(doc, schema=_Keyed)]).is_equal_to(
        ["usage element `--level` may be absent, but field `level` is not optional"]
    )


class _Command(Cli):
    __cli_doc__ = "Usage: app [--out=<f>] <name>"
    out: str
    name: str


def test_a_cli_subclass_is_checked_against_its_own_usage():
    assert_that([found.summary for found in check(_Command.__cli_doc__, schema=_Command)]).is_equal_to(
        ["usage element `--out` may be absent, but field `out` is not optional"]
    )


@dataclasses.dataclass
class _Name:
    name: str | None


@dataclasses.dataclass
class _Out:
    out: str


def test_two_elements_for_one_field_are_found_and_the_field_is_held_against_the_first():
    # `name: str | None` fits the option and would not fit the repeated positional: that is not said twice
    doc = "Usage: app [--name=<n>] [<name>...]"
    assert_that(_said(check(doc, schema=_Name))).is_equal_to(
        [
            (
                "error",
                "usage elements `--name` and `<name>` both map to field `name`",
                [("<name>", "the second of them")],
                None,
                "rename one of the two elements",
            )
        ]
    )
    assert_that(lambda: docopt(doc, [], schema=_Name, complete=False)).raises(DocoptLanguageError).when_called_with()


def test_an_element_that_several_lines_write_is_shown_where_it_is_written_first():
    doc = "Usage:\n  app go [--out=<f>]\n  app stop [--out=<f>]"
    found = check(doc, schema=_Out)
    assert_that([one.summary for one in found]).is_equal_to(
        ["usage element `--out` may be absent, but field `out` is not optional"]
    )
    caret = found[0].snippets[0].carets[0]
    assert_that((caret.start, caret.end)).is_equal_to((doc.index("--out=<f>"), doc.index("--out=<f>") + 9))


class _Plain:
    name: str


class _Empty:
    pass


def test_a_plain_class_takes_no_fields_and_a_class_with_no_fields_needs_none():
    assert_that(_said(check("Usage: app <name>", schema=_Plain))).is_equal_to(
        [
            (
                "error",
                "schema `_Plain` is a plain class with no constructor to take its fields",
                [],
                None,
                "make it a dataclass or subclass `Cli`",
            )
        ]
    )
    assert_that(check("Usage: app <name>", schema=_Empty)).is_empty()


class _Unresolved:
    name: "NoSuchType"  # noqa: F821 - the point: an annotation that names nothing


def test_what_was_not_checked_is_said_and_not_passed_over():
    pydantic = pytest.importorskip("pydantic")

    class Model(pydantic.BaseModel):
        name: int

    assert_that(_said(check("Usage: app [<name>]", schema=Model))).is_equal_to(
        [
            (
                "warning",
                "schema `Model` is a pydantic model, which binds by rules of its own: it was not checked",
                [],
                None,
                None,
            )
        ]
    )
    assert_that(_said(check("Usage: app (<name>", schema=_Name))).is_equal_to(
        [("warning", "the usage message does not parse: schema `_Name` was not checked", [], None, None)]
    )
    assert_that(_said(check("no usage here", schema=_Name))).is_equal_to(
        [("warning", "the usage message does not parse: schema `_Name` was not checked", [], None, None)]
    )
    assert_that(_said(check("Usage: app <name>", schema=_Unresolved))).is_equal_to(
        [
            (
                "error",
                "the annotations of schema `_Unresolved` do not resolve",
                [],
                "name 'NoSuchType' is not defined",
                None,
            )
        ]
    )


def test_the_findings_of_a_schema_come_after_those_of_the_usage_and_the_usage_alone_is_checked_as_before():
    doc = "Usage: app [options] <name>"
    alone = check(doc)
    assert_that([found.level for found in alone]).is_equal_to(["warning"])
    both = check(doc, schema=_Plain)
    assert_that([found.summary for found in both][: len(alone)]).is_equal_to([found.summary for found in alone])
    assert_that([found.level for found in both]).is_equal_to(["warning", "error"])


@dataclasses.dataclass
class _Wide:
    n: int | str | None
    m: str | int | None
    k: int | float | None
    flag: bool | str | None


_WIDE = "Usage: app [<n>] [--m=<v>] [--k=<v>] [--flag=<v>]"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        # left to right: the first member that takes the text binds it
        (["5"], _Wide(n=5, m=None, k=None, flag=None)),
        (["abc"], _Wide(n="abc", m=None, k=None, flag=None)),
        (["--m", "5"], _Wide(n=None, m="5", k=None, flag=None)),
        (["--k", "5"], _Wide(n=None, m=None, k=5, flag=None)),
        (["--k", "5.5"], _Wide(n=None, m=None, k=5.5, flag=None)),
        # a member that cannot hold a text at all is passed over
        (["--flag", "yes"], _Wide(n=None, m=None, k=None, flag="yes")),
    ],
)
def test_a_union_of_several_types_is_tried_member_by_member(argv, expected):
    try:
        bound = docopt(_WIDE, argv, schema=_Wide, complete=False, help=False)
    except DocoptExit as refused:
        bound = _Wide(n=str(refused).splitlines()[0], m=None, k=None, flag=None)
    assert_that(bound).is_equal_to(expected)
    assert_that([type(value) for value in dataclasses.astuple(bound)]).is_equal_to(
        [type(value) for value in dataclasses.astuple(expected)]
    )


@dataclasses.dataclass
class _Shapes:
    x: list[int] | int
    flag: bool | int | None
    both: bool | list[int] | None


_SHAPES = "Usage: app <x>... [--flag=<v>] [--both=<v>]"


def test_where_no_member_takes_a_text_the_member_that_could_hold_a_text_says_why():
    # `int` refuses the list, `list[int]` only the text in it: the user's text is at fault, not the schema
    lines = _lines(_SHAPES, ["5", "abc"])
    assert_that(lines[0]).is_equal_to("error: invalid value for `<x>`")
    assert_that(lines).contains("   = note: `abc` is not a valid int")
    lines = _lines(_SHAPES, ["5", "--flag", "abc"])
    assert_that(lines[0]).is_equal_to("error: invalid value for `--flag`")
    assert_that(lines).contains("   = note: `abc` is not a valid bool | int | None")


def test_where_every_member_refuses_the_shape_it_is_the_schema_that_is_at_fault():
    assert_that(_lines(_SHAPES, ["5", "--both", "abc"])).is_equal_to(
        [
            "DocoptLanguageError: the schema type list[int] is a list, but this usage element is not repeated; "
            "mark it with `...` to repeat, or use a scalar type"
        ]
    )


def _lines(doc, argv, schema=None):
    try:
        docopt(doc, argv, schema=schema or _Shapes, complete=False, help=False)
    except DocoptExit as refused:
        return str(refused).splitlines()
    except DocoptLanguageError as unfit:
        return [f"DocoptLanguageError: {unfit}"]
    except Exception as leaked:  # a leak is what the caller's assertion must show
        return [f"leaked {type(leaked).__name__}"]
    return ["bound"]


def test_a_text_that_no_member_of_a_union_takes_is_refused_by_the_name_of_the_whole_union():
    with pytest.raises(DocoptExit) as refused:
        docopt(_WIDE, ["--k", "abc"], schema=_Wide, complete=False, help=False)
    assert_that(str(refused.value).splitlines()).contains("   = note: `abc` is not a valid int | float | None")
