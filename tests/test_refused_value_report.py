import dataclasses
import enum
from typing import Annotated, Literal

import pytest
from assertpy2 import assert_that

from docopt2 import Dispatch, DocoptExit, _core, docopt
from docopt2._parser import MatchBudget, _MatchBudgetExceededError
from docopt2._typed import _CoercionError, bind_schema

_DOC = """Usage: app [-v] [--level=<n>]... [-p <port>] [<name>]

Options:
  --level=<n>               Level [env: REFUSED_LEVELS].
  -p <port>, --port=<port>  Port [env: REFUSED_PORT] [config: server.port].
"""


@dataclasses.dataclass
class _Args:
    v: bool
    level: list[int]
    port: int | None
    name: str | None


def _refused(call):
    """The lines of the refusal ``call`` ends in. One line that says so where it returns, or where something
    other than a refusal comes out of it."""
    try:
        call()
    except DocoptExit as refused:
        return str(refused).splitlines()
    except Exception as leaked:  # a leak is what the caller's assertion must show
        return [f"leaked {type(leaked).__name__}"]
    return ["accepted"]


def _refusal(doc, argv, schema, **settings):
    return _refused(lambda: docopt(doc, argv, schema=schema, complete=False, help=False, **settings))


def _shown(doc, argv, schema, intro, **settings):
    """The snippet of a refusal that ``intro`` opens: its line, where its caret starts, the text under the caret
    and the caret's label. None where the refusal has no such snippet."""
    lines = _refusal(doc, argv, schema, **settings)
    at = next((index for index, line in enumerate(lines) if line.strip("| ") == intro), None)
    if at is None:
        return None
    text, carets = lines[at + 1][8:], lines[at + 2][8:]
    start, width = carets.index("^"), carets.count("^")
    return text, start, text[start : start + width], carets[start + width :].strip()


def _summary(doc, argv, schema, **settings):
    return _refusal(doc, argv, schema, **settings)[0]


@pytest.mark.parametrize(
    ("argv", "key", "start", "under"),
    [
        # each way an option is given its argument
        (["--port", "abc"], "--port", 7, "abc"),
        (["--port=abc"], "--port", 7, "abc"),
        (["--por=abc"], "--port", 6, "abc"),
        (["-p", "abc"], "--port", 3, "abc"),
        (["-pabc"], "--port", 2, "abc"),
        (["-p=abc"], "--port", 3, "abc"),
        (["-vp", "abc"], "--port", 4, "abc"),
        (["-vpabc"], "--port", 3, "abc"),
        # the same text stands earlier in the line, as another value or inside another token
        (["--level", "7", "-p", "7x", "7x"], "--port", 13, "7x"),
        (["7x", "-p", "7x"], "--port", 6, "7x"),
        (["--port=x", "x"], "--port", 7, "x"),
        (["-px", "x"], "--port", 2, "x"),
        # of a repeated option, the one value that is refused
        (["--level", "1", "--level=x", "--level", "3"], "--level", 18, "x"),
        (["--level", "x", "--level", "x"], "--level", 8, "x"),
        (["--level=1", "--level", "1x", "--level", "1"], "--level", 18, "1x"),
        # a line given whole keeps its own spacing
        ("  --level   1   --level   x ", "--level", 26, "x"),
        # an argument that is empty has no text to point at: the token it is attached to is shown
        (["--port="], "--port", 0, "--port="),
        (["-p="], "--port", 0, "-p="),
    ],
)
def test_a_refused_value_is_pointed_at_where_it_was_typed(argv, key, start, under):
    line = argv if isinstance(argv, str) else " ".join(argv)
    assert_that(_summary(_DOC, argv, _Args)).is_equal_to(f"error: invalid value for `{key}`")
    label = "expected int" if key == "--level" else "expected int | None"
    assert_that(_shown(_DOC, argv, _Args, "in the arguments:")).is_equal_to((line, start, under, label))


_PAIRS = "Usage: app (<a> <b>)..."
_EITHER = "Usage: app (<x> | <x> <y>)"
_COPY = "Usage: app <name> <count>"


@dataclasses.dataclass
class _Pairs:
    a: list[int]
    b: list[Literal["x", "y"]]


@dataclasses.dataclass
class _Either:
    x: str
    y: int | None


@dataclasses.dataclass
class _Copy:
    name: str
    count: int


_TURNS = "Usage: app (a [<x>] | b <y>)..."


@dataclasses.dataclass
class _Turns:
    a: int
    b: int
    x: list[str]
    y: list[int]


@pytest.mark.parametrize(
    ("doc", "argv", "schema", "expected"),
    [
        # two positionals with one text: the one its field refused
        (_COPY, ["abc", "abc"], _Copy, ("abc abc", 4, "abc", "expected int")),
        # two repeated positionals that take turns: the third token is the second `<a>`, the second is a `<b>`
        (_PAIRS, ["1", "x", "x", "y"], _Pairs, ("1 x x y", 4, "x", "expected int")),
        (_PAIRS, ["1", "x", "2", "1"], _Pairs, ("1 x 2 1", 6, "1", "expected one of `x`, `y`")),
        (_EITHER, ["a", "b"], _Either, ("a b", 2, "b", "expected int | None")),
        # the first way the usage reads the line gives `b` to `<x>` and leaves a token over: a later one takes all
        (_TURNS, ["a", "b", "5x"], _Turns, ("a b 5x", 4, "5x", "expected int")),
    ],
)
def test_a_refused_positional_is_the_token_the_usage_gave_to_that_element(doc, argv, schema, expected):
    assert_that(_shown(doc, argv, schema, "in the arguments:")).is_equal_to(expected)


@dataclasses.dataclass
class _Number:
    n: int


@dataclasses.dataclass
class _Numbers:
    v: bool
    args: list[int]


@pytest.mark.parametrize(
    ("doc", "argv", "schema", "settings", "expected"),
    [
        # each of them changes which token a place belongs to, or whether the line can be read again at all
        ("Usage: app <n>", ["-5.5"], _Number, {"negative_numbers": True}, ("-5.5", 0, "-5.5", "expected int")),
        (
            "Usage: app [-v] <args>...",
            ["1", "-v", "x"],
            _Numbers,
            {"options_first": True},
            ("1 -v x", 2, "-v", "expected int"),
        ),
        ("Usage: app <n>", ["x", "surplus"], _Number, {"allow_extra": True}, ("x surplus", 0, "x", "expected int")),
    ],
)
def test_the_line_is_read_for_its_places_as_it_was_read_for_its_values(doc, argv, schema, settings, expected):
    assert_that(_shown(doc, argv, schema, "in the arguments:", **settings)).is_equal_to(expected)


@pytest.mark.parametrize(
    ("argv", "settings", "expected"),
    [
        (["-5.5"], {"negative_numbers": True}, "    ^^^^ expected int"),
        (["1", "-v", "x"], {"options_first": True}, "      ^^ expected int"),
        (["x", "surplus"], {"allow_extra": True}, "    ^ expected int"),
    ],
)
def test_a_handler_table_reads_the_line_for_its_places_with_the_settings_it_was_run_with(argv, settings, expected):
    app = Dispatch("Usage: app [-v] <args>...")
    app.on(schema=_Numbers)(lambda args: args)
    if "allow_extra" in settings:
        app = Dispatch("Usage: app <n>")
        app.on(schema=_Number)(lambda args: args)
    with pytest.raises(DocoptExit) as refused:
        app.run(argv, complete=False, help=False, **settings)
    lines = str(refused.value).splitlines()
    assert_that(lines).contains("   |  in the arguments:", f"   |{expected}")


def test_where_the_search_for_a_whole_reading_runs_out_the_greedy_one_gives_the_place(monkeypatch):
    flags = " ".join(f"[-{letter}]" for letter in "abcdefghijklmopqrs")
    doc = f"Usage: app <n> [{flags}]"
    ran_out = []
    budget_exit = MatchBudget.__exit__

    def watched_exit(self, kind, error, trace):
        ran_out.append(kind is _MatchBudgetExceededError)
        return budget_exit(self, kind, error, trace)

    monkeypatch.setattr(MatchBudget, "__exit__", watched_exit)
    try:
        shown = _shown(doc, ["x", "surplus"], _Number, "in the arguments:", allow_extra=True)
    except _MatchBudgetExceededError:
        shown = "the search ran out and nothing caught it"
    assert_that(shown).is_equal_to(("x surplus", 0, "x", "expected int"))
    # both searches ran out: the one docopt() bound from, and the one that read the line again for its places
    assert_that(ran_out).is_equal_to([True, True])


@pytest.mark.parametrize(
    ("doc", "argv", "schema"),
    [
        # a line that can be read only once is not there to be read for its places
        (_DOC, iter(["--port", "abc"]), _Args),
        ("Usage: app <n>", iter(["x"]), _Number),
        # an argument that is an empty token has no text to point at and nothing it is attached to
        (_DOC, ["--port", ""], _Args),
        (_DOC, ["-p", ""], _Args),
    ],
)
def test_a_value_with_no_place_to_show_gets_no_snippet_of_the_arguments(doc, argv, schema):
    values = list(argv)
    key, value = ("<n>", "x") if schema is _Number else ("--port", values[-1])
    once = argv if isinstance(argv, list) else iter(values)  # the parameter was just read to its end
    with pytest.raises(DocoptExit) as refused:
        docopt(doc, once, schema=schema, complete=False, help=False)
    lines = str(refused.value).splitlines()
    assert_that(lines[0]).is_equal_to(f"error: invalid value for `{key}`")
    assert_that(lines).does_not_contain("   |  in the arguments:").contains("   |  in the usage:")
    assert_that(next(line for line in lines if "= note:" in line)).starts_with(
        f"   = note: `{value}` is not a valid int"
    )


@pytest.mark.parametrize(
    ("variable", "value", "config", "argv", "intro", "expected"),
    [
        (
            "REFUSED_PORT",
            "http",
            None,
            [],
            "in the environment:",
            ("REFUSED_PORT=http", 13, "http", "expected int | None"),
        ),
        (
            "REFUSED_LEVELS",
            "many",
            None,
            [],
            "in the environment:",
            ("REFUSED_LEVELS=many", 15, "many", "expected int"),
        ),
        (
            None,
            None,
            {"server": {"port": "http"}},
            [],
            "in the config:",
            ("server.port = http", 14, "http", "expected int | None"),
        ),
        # the same text in the argv is another element's value: it is not what was refused
        (
            "REFUSED_PORT",
            "http",
            None,
            ["http"],
            "in the environment:",
            ("REFUSED_PORT=http", 13, "http", "expected int | None"),
        ),
    ],
)
def test_a_refused_value_that_is_not_in_the_argv_is_shown_where_it_was_written(
    variable, value, config, argv, intro, expected, monkeypatch
):
    if variable is not None:
        monkeypatch.setenv(variable, value)
    assert_that(_shown(_DOC, argv, _Args, intro, config=config)).is_equal_to(expected)
    assert_that(_shown(_DOC, argv, _Args, "in the arguments:", config=config)).is_none()


_DEFAULTED = """Usage: app [--port=<p>] [--level=<n>]... [<mode>]

Arguments:
  <mode>       Mode [default: 0x].

Options:
  --port=<p>   Port [default: http].
  --level=<n>  Level [default: 1 two 3].
"""


@dataclasses.dataclass
class _Defaulted:
    port: int
    level: list[int]
    mode: int


@pytest.mark.parametrize(
    ("argv", "key", "expected"),
    [
        (["--level", "5", "7"], "--port", ("[default: http]", 10, "http", "expected int")),
        # of a default of several values, the one that is refused, among the others
        (["--port", "5", "7"], "--level", ("[default: 1 two 3]", 12, "two", "expected int")),
        (["--port", "5", "--level", "5"], "<mode>", ("[default: 0x]", 10, "0x", "expected int")),
    ],
)
def test_a_refused_default_is_shown_as_a_default_is_written(argv, key, expected):
    assert_that(_summary(_DEFAULTED, argv, _Defaulted)).is_equal_to(f"error: invalid value for `{key}`")
    assert_that(_shown(_DEFAULTED, argv, _Defaulted, "as the default:")).is_equal_to(expected)
    assert_that(_shown(_DEFAULTED, argv, _Defaulted, "in the arguments:")).is_none()


def test_a_default_of_several_values_is_rebuilt_with_one_space_between_them():
    doc = _DEFAULTED.replace("[default: 1 two 3]", "[default:   1    two \t 3 ]")
    assert_that(_shown(doc, ["--port", "5", "7"], _Defaulted, "as the default:")).is_equal_to(
        ("[default: 1 two 3]", 12, "two", "expected int")
    )


_COUNTED = """Usage: app [-v]... [-q]

Options:
  -v  Verbose [env: REFUSED_V] [config: log.verbose].
  -q  Quiet [env: REFUSED_Q] [config: log.quiet].
"""


@dataclasses.dataclass
class _Counted:
    v: Literal[0, 1, 2]
    q: Literal[False]


@pytest.mark.parametrize(
    ("variables", "config", "intro", "expected"),
    [
        # the text that was written, not the count or the bool a flag reads it as
        ({"REFUSED_V": "03"}, None, "in the environment:", ("REFUSED_V=03", 10, "03", "expected one of `0`, `1`, `2`")),
        ({"REFUSED_Q": "yes"}, None, "in the environment:", ("REFUSED_Q=yes", 10, "yes", "expected one of `False`")),
        ({}, {"log": {"verbose": 3}}, "in the config:", ("log.verbose = 3", 14, "3", "expected one of `0`, `1`, `2`")),
        ({}, {"log": {"quiet": True}}, "in the config:", ("log.quiet = true", 12, "true", "expected one of `False`")),
    ],
)
def test_a_refused_flag_or_count_from_elsewhere_is_shown_as_the_text_written_there(
    variables, config, intro, expected, monkeypatch
):
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    assert_that(_shown(_COUNTED, [], _Counted, intro, config=config)).is_equal_to(expected)


@pytest.mark.parametrize("later", ["2", None])
def test_the_text_shown_is_the_one_the_value_was_resolved_from_whatever_the_environment_holds_later(later, monkeypatch):
    monkeypatch.setenv("REFUSED_V", "03")
    bind = _core.bind_schema

    def bind_after_a_change(parsed, schema):
        if later is None:
            monkeypatch.delenv("REFUSED_V")
        else:
            monkeypatch.setenv("REFUSED_V", later)
        return bind(parsed, schema)

    monkeypatch.setattr(_core, "bind_schema", bind_after_a_change)
    assert_that(_shown(_COUNTED, [], _Counted, "in the environment:")).is_equal_to(
        ("REFUSED_V=03", 10, "03", "expected one of `0`, `1`, `2`")
    )


@dataclasses.dataclass
class _Loud:
    v: Literal[0, 1, 2]
    q: Literal[True]


@pytest.mark.parametrize(
    ("argv", "schema", "key", "note"),
    [
        # three tokens made the count: there is no one place of it
        (["-vvv"], _Counted, "-v", "   = note: `3` is not one of `0`, `1`, `2`"),
        (["-v", "-q"], _Counted, "-q", "   = note: `True` is not one of `False`"),
        # a flag that was not given, refused: no default is written for a flag
        ([], _Loud, "-q", "   = note: `False` is not one of `True`"),
    ],
)
def test_a_refused_flag_or_count_of_the_argv_is_shown_by_its_usage_element_alone(argv, schema, key, note):
    with pytest.raises(DocoptExit) as refused:
        docopt(_COUNTED, argv, schema=schema, complete=False, help=False)
    lines = str(refused.value).splitlines()
    assert_that(lines[0]).is_equal_to(f"error: invalid value for `{key}`")
    intros = [line.strip("| ") for line in lines if line.endswith(":") and line.startswith("   |  ")]
    assert_that(intros).is_equal_to(["in the usage:"])
    assert_that(lines).contains(note)


def test_an_empty_default_has_no_text_to_show():
    doc = "Usage: app [--port=<p>]\n\nOptions:\n  --port=<p>  Port [default: ]."
    assert_that(_summary(doc, [], _Port)).is_equal_to("error: invalid value for `--port`")
    assert_that(_shown(doc, [], _Port, "as the default:")).is_none()
    assert_that(_shown(doc, [], _Port, "in the usage:")).is_equal_to(
        ("Usage: app [--port=<p>]", 12, "--port=<p>", "typed as int | None")
    )


def test_a_handler_table_shows_a_value_of_its_config():
    app = Dispatch(_DOC)
    app.on(schema=_Args)(lambda args: args)
    lines = _refused(lambda: app.run([], complete=False, help=False, config={"server": {"port": "http"}}))
    assert_that(lines).contains("   |  in the config:", "   |    server.port = http")


def test_a_handler_table_names_the_environment_too(monkeypatch):
    monkeypatch.setenv("REFUSED_PORT", "http")
    app = Dispatch(_DOC)
    app.on(schema=_Args)(lambda args: args)
    with pytest.raises(DocoptExit) as refused:
        app.run([], complete=False, help=False)
    assert_that(str(refused.value)).contains("in the environment:", "REFUSED_PORT=http").does_not_contain(
        "in the arguments:"
    )


@pytest.mark.parametrize(
    ("argv", "under", "usage_label", "note"),
    [
        (["--level", "1", "--level", "x"], "x", "typed as list[int]", "   = note: `x` is not a valid int"),
        (["--port", "x"], "x", "typed as int | None", "   = note: `x` is not a valid int | None"),
    ],
)
def test_the_usage_element_is_labelled_with_the_type_of_the_field_and_the_value_with_its_own(
    argv, under, usage_label, note
):
    with pytest.raises(DocoptExit) as refused:
        docopt(_DOC, argv, schema=_Args, complete=False, help=False)
    lines = str(refused.value).splitlines()
    assert_that(next(line for line in lines if "typed as" in line)).ends_with(usage_label)
    assert_that(lines).contains(note)
    assert_that(_shown(_DOC, argv, _Args, "in the arguments:")[2]).is_equal_to(under)


@dataclasses.dataclass
class _Logs:
    a: list[int]
    b: list[Literal["debug", "info"]]


def test_a_refused_value_of_a_closed_set_still_gets_its_hint_among_several():
    with pytest.raises(DocoptExit) as refused:
        docopt(_PAIRS, ["1", "debug", "2", "inof"], schema=_Logs, complete=False, help=False)
    assert_that(str(refused.value).splitlines()).contains(
        "   = note: `inof` is not one of `debug`, `info`", "   = help: did you mean `info`?"
    )


@dataclasses.dataclass
class _Port:
    port: int | None


@dataclasses.dataclass
class _EitherList:
    x: list[bool] | list[int]


def test_of_a_union_of_lists_the_member_that_refused_names_the_value():
    # `list[bool]` cannot hold a text at all, so `list[int]` is the member that speaks: it took `1` and refused `x`
    assert_that(_shown("Usage: app <x>...", ["1", "x"], _EitherList, "in the arguments:")).is_equal_to(
        ("1 x", 2, "x", "expected int")
    )
    with pytest.raises(_CoercionError) as refused:
        bind_schema({"<x>": ["1", "x"]}, _EitherList)
    assert_that((refused.value.raw, refused.value.index, refused.value.expected)).is_equal_to(("x", 1, "int"))


class _Moody(enum.Enum):
    A = "A"

    @classmethod
    def _missing_(cls, value):
        _ASKED.append(value)
        return cls.A if value == "a" and _ASKED.count("a") > 1 else None


_ASKED: list[object] = []


@dataclasses.dataclass
class _Moods:
    x: list[_Moody]


def test_the_value_named_is_the_one_coercion_refused_and_nothing_is_coerced_again_to_find_it():
    # asked a second time this Enum would take `a`, and the report would then name `b`
    _ASKED.clear()
    with pytest.raises(_CoercionError) as refused:
        bind_schema({"<x>": ["a", "b"]}, _Moods)
    assert_that((refused.value.raw, refused.value.index)).is_equal_to(("a", 0))
    assert_that(_ASKED).is_equal_to(["a"])


@dataclasses.dataclass
class _Wrapped:
    plain: list[int]
    annotated_beside_none: Annotated[list[int], "why"] | None
    beside_none: list[int] | None
    annotated: Annotated[list[int], "why"]
    bare: list
    scalar: int


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        ("plain", ["1", "x", "y"], ("x", 1, "int", "list[int]")),
        ("beside_none", ["x"], ("x", 0, "int", "list[int] | None")),
        ("annotated", ["1", "2", "x"], ("x", 2, "int", "list[int]")),
        # how a union with None is spelled differs between Python versions: the spelling of this one is taken
        ("annotated_beside_none", ["1", "x"], ("x", 1, "int", str(Annotated[list[int], "why"] | None))),
        ("scalar", "x", ("x", None, "int", "int")),
    ],
)
def test_a_refusal_names_the_value_its_place_among_the_values_its_type_and_the_type_of_the_field(key, raw, expected):
    given = {"plain": [], "beside_none": None, "annotated": [], "bare": ["anything"], "scalar": "1"}
    given = {**given, "annotated_beside_none": None, key: raw}
    with pytest.raises(_CoercionError) as refused:
        bind_schema(given, _Wrapped)
    error = refused.value
    assert_that((error.raw, error.index, error.expected, error.declared)).is_equal_to(expected)
    assert_that(error.key).is_equal_to(key)
