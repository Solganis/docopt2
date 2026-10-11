import dataclasses
import enum
import ipaddress
import itertools
import pathlib
from typing import Annotated, Literal, TypedDict

import pytest
from assertpy2 import assert_that

from docopt2 import Cli, Dispatch, DocoptLanguageError, complete, docopt
from docopt2._typed import field_choices, field_takes

_DOC = """Usage:
  app deploy <env> [--format=<f>] [--level=<n>]... [-c <color>] [--note=<text>]
  app status [--format=<f>]

Options:
  --format=<f>   Output format.
  --level=<n>    Level, repeatable.
  -c <color>     Color.
  --note=<text>  A note.
"""
_NAMES = ["--format", "--level", "--note", "-c"]
_ATTACHED = ["--format=json", "--format=yaml", "--level=1", "--level=2", "--level=3"]


class _Color(enum.Enum):
    RED = "red"
    GREEN = "green"


@dataclasses.dataclass
class _Args:
    deploy: bool
    status: bool
    env: Literal["dev", "staging", "prod"] | None
    format: Annotated[Literal["json", "yaml"], "how"] | None
    level: list[Literal[1, 2, 3]]
    c: _Color | None
    note: str | None


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        # the next positional, by the closed set of its field
        (["deploy", ""], sorted([*_NAMES, *_ATTACHED, "dev", "prod", "staging"])),
        (["deploy", "st"], ["staging"]),
        (["deploy", "--", ""], ["dev", "prod", "staging"]),
        # the argument an option is waiting for: spelled out, abbreviated, short, and a repeatable one
        (["deploy", "prod", "--format", ""], ["json", "yaml"]),
        (["deploy", "prod", "--for", ""], ["json", "yaml"]),
        (["deploy", "prod", "--format", "y"], ["yaml"]),
        (["deploy", "prod", "-c", ""], ["green", "red"]),
        (["deploy", "prod", "--level", ""], ["1", "2", "3"]),
        (["deploy", "prod", "--level", "1", "--level", ""], ["1", "2", "3"]),
        (["status", "--format", ""], ["json", "yaml"]),
        (["--format", ""], ["json", "yaml"]),
        # `--option=value` beside the option's name, for a long option that takes a closed set
        (["deploy", "prod", ""], sorted([*_NAMES, *_ATTACHED])),
        (["deploy", "prod", "--format=js"], ["--format=json"]),
        (["status", ""], ["--format", "--format=json", "--format=yaml"]),
        # a field that takes any text has no values to offer
        (["deploy", "prod", "--note", ""], []),
        # a positional that is already given is not offered again
        (["deploy", "prod", "pr"], []),
    ],
)
def test_a_field_that_takes_a_closed_set_completes_its_values(words, expected):
    assert_that(complete(_DOC, words, schema=_Args)).is_equal_to(expected)


@pytest.mark.parametrize(
    "words",
    [
        # the usage does not take the option there: another line's option, one given once already, one no line has
        ["status", "--level", ""],
        ["deploy", "prod", "--format", "json", "--format", ""],
        ["deploy", "prod", "--nope", ""],
        # nor after positionals no line takes
        ["deploy", "prod", "extra", "--format", ""],
        ["status", "extra", ""],
        # nor after a positional its field does not take: no argv that starts that way can be bound
        ["deploy", "nowhere", ""],
        ["deploy", "nowhere", "--format", ""],
        # nor after an option given a value its field does not take, an empty one included
        ["deploy", "prod", "--format=", ""],
        ["deploy", "prod", "--format", "xml", ""],
        ["deploy", "prod", "--format=xml", "--level", ""],
        ["deploy", "prod", "--level", "9", ""],
    ],
)
def test_an_option_the_usage_does_not_take_at_that_point_completes_no_value(words):
    assert_that(complete(_DOC, words, schema=_Args)).is_empty()


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (["deploy", ""], _NAMES),
        (["deploy", "st"], []),
        (["deploy", "prod", "--format", ""], []),
        (["deploy", "prod", "--format=js"], []),
        (["deploy", "prod", "--format=", ""], ["--level", "--note", "-c"]),
        (["deploy", "--", ""], []),
    ],
)
def test_no_value_is_a_candidate_without_a_schema(words, expected):
    assert_that(complete(_DOC, words)).is_equal_to(expected)


_TWO_PATHS = "Usage:\n  app <a> [--one]\n  app <b> <a> [--two]\n\nOptions:\n  --one  One.\n  --two  Two."


@dataclasses.dataclass
class _TwoPaths:
    a: Literal["A"]
    b: Literal["B"] | None
    one: bool
    two: bool


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ([""], ["--one", "--two", "A", "B"]),
        # an option only one line has: the positional that line fills next, not one of the same name elsewhere
        (["--two", ""], ["B"]),
        (["--one", ""], ["A"]),
        (["--two", "B", ""], ["A"]),
        # a positional already typed is read by its field: `A` can only be `<a>`, so no line has a second one
        (["A", ""], ["--one"]),
    ],
)
def test_the_positional_completed_is_the_one_a_line_that_takes_the_prefix_fills_next(words, expected):
    assert_that(complete(_TWO_PATHS, words, schema=_TwoPaths)).is_equal_to(expected)


_OPTIONAL_FIRST = "Usage: app [go] <env> [--format=<f>]\n\nOptions:\n  --format=<f>  Format."


@dataclasses.dataclass
class _OptionalFirst:
    go: bool
    env: Literal["dev"]
    format: Literal["json"] | None


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        # a command that may be left out, then a positional: either can come next
        ([""], ["--format", "--format=json", "dev", "go"]),
        (["go", ""], ["--format", "--format=json", "dev"]),
        (["--format", "json", ""], ["dev", "go"]),
    ],
)
def test_a_positional_behind_a_command_that_may_be_left_out_is_completed_too(words, expected):
    assert_that(complete(_OPTIONAL_FIRST, words, schema=_OptionalFirst)).is_equal_to(expected)


_PAIR = "Usage: app <a> <b>"


@dataclasses.dataclass
class _Pair:
    a: Literal["a:b", "ab"]
    b: Literal["done"]


@dataclasses.dataclass
class _PairNothingToOffer:
    a: Literal["a:b"]
    b: Literal["done"]


@pytest.mark.parametrize(
    ("schema", "words", "expected"),
    [
        # `a:b` is a value the field takes and none that is offered: typed, it is read as taken
        (_Pair, [""], ["ab"]),
        (_Pair, ["a:b", ""], ["done"]),
        (_Pair, ["ab", ""], ["done"]),
        (_Pair, ["garbage", ""], []),
        # a field with no value to offer still reads what was typed for it
        (_PairNothingToOffer, [""], []),
        (_PairNothingToOffer, ["a:b", ""], ["done"]),
        (_PairNothingToOffer, ["garbage", ""], []),
    ],
)
def test_what_a_field_takes_is_not_what_is_offered_for_it(schema, words, expected):
    assert_that(complete(_PAIR, words, schema=schema)).is_equal_to(expected)


@pytest.mark.parametrize("schema", [_Pair, _PairNothingToOffer])
def test_the_parse_binds_the_value_that_is_taken_and_not_offered(schema):
    assert_that([_binds(_PAIR, [first, "done"], schema) for first in ("a:b", "garbage")]).is_equal_to([True, False])


def _binds(doc, argv, schema):
    try:
        docopt(doc, argv, schema=schema, complete=False, help=False)
    except (SystemExit, DocoptLanguageError, ValueError):  # ValueError: what a pydantic model refuses with
        return False
    return True


def _audit(doc, schema, alphabet, closed, longest, room, *, exact=True):
    """Hold completion against every argv over ``alphabet``, up to ``longest`` tokens, that the parse binds.

    ``closed`` is written by hand: the texts of the closed sets that are in the alphabet. Returns how many
    argvs are bound, and what is wrong:

    - a value offered that is not in the alphabet, which would go unjudged;
    - a dead end: a value offered at a prefix that no bound argv goes on from. Judged at every prefix, live or
      not, and with ``exact`` off only at a prefix some bound argv starts with. Judged where ``room`` more
      tokens after the value still fit in ``longest``, so that the argv it leads to was enumerated;
    - a hole: a place in a bound argv where the token is or carries a closed value, where another text in its
      place is not bound, and where that token was not offered;
    - a silenced name: a token of a bound argv that the usage alone offers there and the schema takes away.
    """
    argvs = [argv for size in range(longest + 1) for argv in itertools.product(alphabet, repeat=size)]
    bound = [argv for argv in argvs if _binds(doc, list(argv), schema)]
    live = {argv[:cut] for argv in bound for cut in range(len(argv) + 1)}
    wrong = []
    for prefix in (argv for argv in argvs if len(argv) + 1 + room <= longest and (exact or argv in live)):
        offered = complete(doc, [*prefix, ""], schema=schema)
        values = [name for name in offered if name in closed or name.partition("=")[2] in closed]
        wrong += [("outside the alphabet", prefix, name) for name in values if name not in alphabet]
        wrong += [("a dead end", prefix, name) for name in values if (*prefix, name) not in live]
    for argv in bound:
        for cut, token in enumerate(argv):
            offered = complete(doc, [*argv[:cut], ""], schema=schema)
            name, attached, value = token.rpartition("=")
            free = _binds(doc, [*argv[:cut], f"{name}{attached}zzz", *argv[cut + 1 :]], schema)
            if value in closed and not free and token not in offered:
                wrong.append(("a hole", argv[:cut], token))
            if token in complete(doc, [*argv[:cut], ""]) and token not in offered:
                wrong.append(("silenced", argv[:cut], token))
    return len(bound), wrong


_LINES = "Usage:\n  app deploy <env> [--level=<n>]...\n  app status [--level=<n>]\n\nOptions:\n  --level=<n>  Level."


@dataclasses.dataclass
class _Lines:
    deploy: bool
    status: bool
    env: Literal["dev"] | None
    level: list[Literal[2]]


@pytest.mark.parametrize(
    ("doc", "schema", "alphabet", "closed", "longest", "room", "bound"),
    [
        (_TWO_PATHS, _TwoPaths, ["A", "B", "--one", "--two"], {"A", "B"}, 5, 1, 7),
        (
            _OPTIONAL_FIRST,
            _OptionalFirst,
            ["go", "dev", "--format", "json", "--format=json"],
            {"dev", "json"},
            5,
            1,
            12,
        ),
        (_LINES, _Lines, ["deploy", "status", "dev", "--level", "2", "--level=2"], {"dev", "2"}, 5, 2, 40),
        (_PAIR, _Pair, ["a:b", "ab", "done", "zzz"], {"ab", "done"}, 3, 1, 2),
    ],
)
def test_over_every_argv_the_parse_binds_a_value_is_offered_where_one_is_needed_and_nowhere_it_is_a_dead_end(
    doc, schema, alphabet, closed, longest, room, bound
):
    assert_that(_audit(doc, schema, alphabet, closed, longest, room)).is_equal_to((bound, []))


_HOST = "Usage: app <host> [--format=<f>] [--note=<t>]\n\nOptions:\n  --format=<f>  Format.\n  --note=<t>    Note."


def test_a_pydantic_model_silences_no_name_and_offers_no_dead_end_on_the_way_to_an_argv_it_binds():
    pydantic = pytest.importorskip("pydantic")

    class Host(pydantic.BaseModel):
        host: ipaddress.IPv4Address
        format: Literal["json"] | None = None
        note: str | None = None

    class Pair(pydantic.BaseModel):
        a: Literal["a:b", "ab"]
        b: Literal["done"]

    alphabet = ["10.0.0.1", "--format", "json", "--format=json", "--note"]
    assert_that(_audit(_HOST, Host, alphabet, {"json"}, 4, 1, exact=False)).is_equal_to((45, []))
    assert_that(_audit(_PAIR, Pair, ["a:b", "ab", "done", "zzz"], {"ab", "done"}, 3, 1, exact=False)).is_equal_to(
        (2, [])
    )


def test_a_pydantic_model_is_asked_for_its_closed_sets_of_strings_and_judges_no_typed_word():
    pydantic = pytest.importorskip("pydantic")

    class Model(pydantic.BaseModel):
        host: ipaddress.IPv4Address
        level: Literal[1, 2]
        format: Literal["json", "yaml"] | None = None
        note: str | None = None

    doc = _HOST.replace("<host>", "<host> <level>")
    names = ["--format", "--format=json", "--format=yaml", "--note"]
    # the model refuses the text `1` for `Literal[1, 2]`, which a dataclass with that field takes: not offered
    assert_that(_binds(doc, ["10.0.0.1", "1"], Model)).is_false()
    assert_that(complete(doc, ["10.0.0.1", ""], schema=Model)).is_equal_to(names)
    # a typed word is not judged: the model binds it by rules of its own
    assert_that(complete(doc, ["10.0.0.1", "nine", ""], schema=Model)).is_equal_to(names)
    assert_that(complete(doc, ["10.0.0.1", "1", "--format", "xml", ""], schema=Model)).is_equal_to(["--note"])
    assert_that(complete(doc, ["10.0.0.1", "1", "--format=xml", "--note", ""], schema=Model)).is_empty()
    assert_that(field_takes(Model)("format", "xml")).is_true()


class _Numbered(enum.IntEnum):
    ONE = 1
    TWO = 2


class _Odd(TypedDict):
    plain: Literal["a", "two words", "", "b\tc", "ok", "$(id)", "a;b", "*", "it's", "v1.2", "a/b@c%d+e,f-g_h"]
    led_by_a_dash: Literal["-x", "--", "x-y"]
    broken_by_bash: Literal["a:b", "a=b", "ab"]
    raw: Literal[b"bytes"]
    nothing: Literal[None, "some"]
    number: _Numbered
    listed: list[_Color]
    maybe_listed: list[_Color] | None
    where: pathlib.Path
    bare: list
    text: str
    count: int


def test_the_texts_of_a_closed_set_are_those_its_own_coercion_takes_one_plain_word_each():
    assert_that(field_choices([_Odd])).is_equal_to(
        {
            "plain": ["a", "ok", "v1.2", "a/b@c%d+e,f-g_h"],
            "led_by_a_dash": ["x-y"],
            "broken_by_bash": ["ab"],
            "nothing": ["some"],
            "number": ["1", "2"],
            "listed": ["red", "green"],
            "maybe_listed": ["red", "green"],
        }
    )


class _Unresolved:
    name: "NoSuchType"  # noqa: F821 - the point: an annotation that names nothing


def test_a_schema_whose_annotations_do_not_resolve_offers_nothing_and_does_not_raise():
    assert_that(field_choices([_Unresolved, _Args]).get("env")).is_equal_to(["dev", "staging", "prod"])
    assert_that(complete(_DOC, ["deploy", "st"], schema=_Unresolved)).is_empty()


def test_a_pydantic_model_completes_its_closed_sets_too():
    pydantic = pytest.importorskip("pydantic")

    class Model(pydantic.BaseModel):
        deploy: bool
        env: Literal["dev", "prod"] | None = None

    assert_that(complete(_DOC, ["deploy", ""], schema=Model)).is_equal_to(sorted([*_NAMES, "dev", "prod"]))


def _reply(monkeypatch, capsys, words, call):
    """What a completion request for ``words`` prints: each candidate and its description."""
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.setenv("_DOCOPT2_WORDS", "\n".join(words))
    with pytest.raises(SystemExit):
        call()
    return [tuple(line.split("\t")) for line in capsys.readouterr().out.splitlines()]


def test_a_request_answered_by_docopt_with_a_schema_carries_values(monkeypatch, capsys):
    with_schema = lambda: docopt(_DOC, [], schema=_Args)
    assert_that(_reply(monkeypatch, capsys, ["deploy", "prod", "--format"], with_schema)).is_equal_to(
        [("json", ""), ("yaml", "")]
    )
    assert_that(_reply(monkeypatch, capsys, ["status"], with_schema)).is_equal_to(
        [("--format", "Output format"), ("--format=json", "Output format"), ("--format=yaml", "Output format")]
    )
    assert_that(_reply(monkeypatch, capsys, ["status"], lambda: docopt(_DOC, []))).is_equal_to(
        [("--format", "Output format")]
    )


class _Typed(Cli):
    __cli_doc__ = "Usage: app <env> [--format=<f>]\n\nOptions:\n  --format=<f>  Output format."
    env: Literal["dev", "prod"]
    format: Literal["json"] | None


def test_a_request_answered_by_a_schema_class_carries_values(monkeypatch, capsys):
    assert_that(_reply(monkeypatch, capsys, [], _Typed.parse)).is_equal_to(
        [("--format", "Output format"), ("--format=json", "Output format"), ("dev", ""), ("prod", "")]
    )


@dataclasses.dataclass
class _Deploy:
    env: Literal["dev", "prod"]
    format: Literal["json", "yaml"] | None


@dataclasses.dataclass
class _Status:
    format: Literal["yaml", "table"] | None


def _table():
    app = Dispatch(_DOC)
    app.on("deploy", schema=_Deploy)(lambda args: args)
    app.on("status", schema=_Status)(lambda args: args)
    app.on()(lambda args: args)
    return app


def test_a_handler_table_offers_a_value_only_where_every_handler_that_declares_the_field_takes_it(monkeypatch, capsys):
    app = _table()
    names = [("--level", "Level, repeatable"), ("--note", "A note"), ("-c", "Color")]
    whole = [("--format", "Output format"), ("--format=yaml", "Output format"), *names, ("dev", ""), ("prod", "")]
    assert_that(_reply(monkeypatch, capsys, ["deploy"], app.run)).is_equal_to(whole)
    # `json` is the deploy handler's alone and `table` the status handler's alone: neither is offered for either
    assert_that(_reply(monkeypatch, capsys, ["deploy", "dev", "--format"], app.run)).is_equal_to([("yaml", "")])
    assert_that(_reply(monkeypatch, capsys, ["status", "--format"], app.run)).is_equal_to([("yaml", "")])
    assert_that(_reply(monkeypatch, capsys, ["status"], app.run)).is_equal_to(
        [("--format", "Output format"), ("--format=yaml", "Output format")]
    )


@pytest.mark.parametrize(
    ("prefix", "then"),
    [
        # for each value the table offers there: what is typed after it, and the field it must end up in
        (["deploy"], {"dev": ([], "env"), "prod": ([], "env"), "--format=yaml": (["dev"], "format")}),
        (["deploy", "dev", "--format"], {"yaml": ([], "format")}),
        (["status", "--format"], {"yaml": ([], "format")}),
        (["status"], {"--format=yaml": ([], "format")}),
    ],
)
def test_every_value_a_handler_table_offers_is_bound_by_the_handler_the_line_runs(prefix, then, monkeypatch, capsys):
    app = _table()
    offered = [name for name, _ in _reply(monkeypatch, capsys, prefix, app.run)]
    values = [name for name in offered if not name.startswith("-") or "=" in name]
    assert_that(sorted(values)).is_equal_to(sorted(then))
    monkeypatch.delenv("_DOCOPT2_COMPLETE")
    bound = {value: getattr(app.run([*prefix, value, *tail]), field) for value, (tail, field) in then.items()}
    assert_that(bound).is_equal_to({value: value.rpartition("=")[2] for value in then})


def test_a_schema_judges_a_typed_word_as_binding_it_would():
    takes = field_takes(_Deploy)
    assert_that([takes("env", "dev"), takes("env", "nowhere"), takes("format", "json")]).is_equal_to(
        [True, False, True]
    )
    assert_that([takes("format", "table"), takes("no_such_field", "anything")]).is_equal_to([False, True])


@pytest.mark.parametrize(
    "typed",
    [
        # `json` is a format the deploy handler takes and the status handler refuses
        ["deploy", "dev", "--format", "json"],
        ["deploy", "dev", "--format=json", "--level", "1"],
        # nor is a word no handler takes judged: which of them binds is not known before the line is whole
        ["deploy", "nowhere"],
        ["deploy", "dev", "--format", "xml"],
    ],
)
def test_a_handler_table_takes_no_name_away_after_a_typed_word(typed, monkeypatch, capsys):
    offered = [line[0] for line in _reply(monkeypatch, capsys, typed, _table().run)]
    alone = complete(_DOC, [*typed, ""])
    assert_that(alone).is_not_empty()
    assert_that([name for name in alone if name not in offered]).is_empty()


def test_a_handler_table_completes_a_waiting_option_after_a_word_no_handler_takes(monkeypatch, capsys):
    assert_that(_reply(monkeypatch, capsys, ["deploy", "nowhere", "--format"], _table().run)).is_equal_to(
        [("yaml", "")]
    )


def test_a_handler_table_with_no_doc_is_refused_as_docopt_refuses_it_request_or_not(monkeypatch):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.setenv("_DOCOPT2_WORDS", "")
    try:
        said = Dispatch(None).run([])
    except DocoptLanguageError as refused:
        said = str(refused)
    except (TypeError, AttributeError, SystemExit) as leaked:
        said = f"leaked: {type(leaked).__name__}"
    assert_that(said).contains("doc (the usage message) must not be None")


def test_a_handler_table_told_not_to_complete_parses_the_argv_it_was_given(monkeypatch):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.setenv("_DOCOPT2_WORDS", "deploy")
    app = _table()
    try:
        ran = app.run(["deploy", "prod"], complete=False)
    except SystemExit:
        ran = "answered the request and left"
    assert_that(ran).is_equal_to(_Deploy(env="prod", format=None))
