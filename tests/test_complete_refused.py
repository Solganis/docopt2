import dataclasses
from typing import Literal

import pytest
from assertpy2 import assert_that
from hypothesis import given, settings
from hypothesis import strategies as st

from docopt2 import Dispatch, DocoptExit, _completion
from docopt2._completion import _complete
from docopt2._parser import Required

_TOOL = """Usage:
  app deploy <env> [--format=<f>] [--level=<n>]
  app status [--format=<f>] [--level=<n>] [-v]
  app other [--format=<f>]
  app bare [--format=<f>]

Options:
  --format=<f>  Output format.
  --level=<n>   Level.
"""


def _schema(**fields):
    return dataclasses.make_dataclass("Bound", list(fields.items()))


def _table(doc, *registered):
    app = Dispatch(doc)
    for command_path, schema in registered:
        app.on(*command_path, schema=schema)(lambda _bound, command_path=command_path: command_path)
    return app


def _offered(app, typed):
    return _complete(app.doc, [*typed, ""], [], app._table())[0]


def _bound(app, argv):
    try:
        app.run(argv, complete=False, help=False)
    except DocoptExit:
        return False
    return True


def _tool():
    deploy = _schema(env=Literal["dev", "prod"], format=Literal["json", "yaml"] | None, level=Literal["1", "2"] | None)
    status = _schema(format=Literal["yaml", "table"] | None, level=Literal["2", "3"] | None, v=bool)
    return _table(_TOOL, (("deploy",), deploy), (("status",), status), (("other",), None))


@pytest.mark.parametrize(
    ("typed", "offered"),
    [
        (["--format=json"], ["--level", "--level=2", "bare", "deploy", "other"]),
        (["--format", "json"], ["--level", "--level=2", "bare", "deploy", "other"]),
        (["--format=table"], ["--level", "--level=2", "-v", "bare", "other", "status"]),
        (["--format=yaml"], ["--level", "--level=2", "-v", "bare", "deploy", "other", "status"]),
        (["--format=csv"], ["bare", "other"]),
        (["--format=json", "--level=1"], ["deploy"]),
        (["--format=json", "--level=3"], []),
    ],
)
def test_a_candidate_is_left_out_where_every_handler_it_leaves_in_reach_refuses_a_value_typed_for_an_option(
    typed, offered
):
    # `-v` leaves the handler of `status` alone. `other` is run by a handler of no schema, and `bare` by none
    assert_that(_offered(_tool(), typed)).is_equal_to(offered)


def test_the_value_of_an_option_that_waits_is_left_out_as_any_other_candidate_and_what_stands_for_it_is_not_judged():
    assert_that(_offered(_tool(), ["--format=json", "--level"])).is_equal_to(["2"])
    assert_that(_offered(_tool(), ["--format=csv", "--level"])).is_empty()


def test_a_flag_typed_is_held_against_no_handler_since_it_may_be_given_again_and_count():
    doc = "Usage:\n  p go [-f] [-f] [-f]\n  p stop [-f] [-f] [-f]\n"
    app = _table(doc, (("go",), _schema(f=Literal[2])), (("stop",), _schema(f=Literal[3])))
    assert_that(_offered(app, ["-f"])).is_equal_to(["-f", "go", "stop"])
    assert_that(_bound(app, ["-f", "go", "-f"])).is_true()


def test_each_value_typed_for_a_repeated_option_is_held_against_the_handler_as_one_of_its_list():
    doc = "Usage:\n  p go [--tag=<t>]...\n  p stop [--tag=<t>]...\n\nOptions:\n  --tag=<t>  Tag.\n"
    first, second = _schema(tag=list[Literal["a", "b"]]), _schema(tag=list[Literal["b", "c"]])
    app = _table(doc, (("go",), first), (("stop",), second))
    assert_that(_offered(app, ["--tag=a"])).is_equal_to(["--tag", "--tag=b", "go"])
    assert_that(_offered(app, ["--tag=b", "--tag=a"])).is_equal_to(["--tag", "--tag=b", "go"])
    assert_that(_offered(app, ["--tag=a", "--tag=c"])).is_empty()
    assert_that(_bound(app, ["--tag=b", "--tag=a", "go", "--tag=b"])).is_true()


def test_a_typed_positional_is_held_against_no_handler_while_several_are_in_reach():
    app = _table("Usage:\n  p <x> go\n  p <x> stop\n", (("go",), _schema(x=Literal["a"])), (("stop",), _schema(x=int)))
    assert_that(_offered(app, ["a"])).is_equal_to(["go", "stop"])


def test_a_line_is_walked_once_for_all_the_candidates_that_name_no_command_of_it(monkeypatch):
    lines = "".join(f"  p c{at} [--format=<f>]\n" for at in range(6))
    app = _table(f"Usage:\n{lines}", *(((f"c{at}",), _schema(format=Literal["yaml"] | None)) for at in range(6)))
    walked, behind = [], _completion._behind
    monkeypatch.setattr(_completion, "_behind", lambda node, *given: walked.append(type(node)) or behind(node, *given))
    assert_that(_offered(app, ["--format=json"])).is_empty()
    # for no word, for its own command, and for any of the five others
    assert_that(walked.count(Required)).is_equal_to(3 * 6)


_KINDS = ["json", "yaml", "table"]
_SETS = st.lists(st.sampled_from(_KINDS), min_size=1, max_size=2, unique=True)
_MARKS = {"x": "<x>", "format": "--format=", "level": "--level=", "q": "-q"}
_OPTIONS = "\n\nOptions:\n  --format=<f>  Format.\n  --level=<n>  Level.\n"


def _fitting(usage, sets):
    """A schema of the elements ``usage`` has, with ``sets`` for what its two options take. None for no sets."""
    if sets is None:
        return None
    formats, levels = (Literal[tuple(one)] | None for one in sets)
    declared = {"x": str | None, "format": formats, "level": levels, "q": bool}
    return _schema(**{name: annotation for name, annotation in declared.items() if _MARKS[name] in usage})


_OWN_LINE = st.sampled_from(
    ["[--format=<f>] [--level=<n>]", "[<x>] [--format=<f>] [--level=<n>]", "[--format=<f>]", "[--level=<n>] [-q]"]
)
_VALUED = st.lists(st.sampled_from(["--format", "--level"]), max_size=2, unique=True).flatmap(
    lambda names: st.tuples(*(st.sampled_from(_KINDS).map(lambda kind, name=name: f"{name}={kind}") for name in names))
)
_TAKEN = st.tuples(_SETS, _SETS)


@settings(max_examples=200)
@given(st.tuples(_OWN_LINE, _OWN_LINE, _OWN_LINE), st.tuples(_TAKEN, _TAKEN, st.none() | _TAKEN), _VALUED)
def test_where_each_command_has_its_line_a_candidate_is_offered_exactly_where_a_line_it_leads_to_is_bound(
    tails, taken, typed
):
    usage = "Usage:" + "".join(f"\n  p {name} {tail}" for name, tail in zip("abc", tails, strict=True))
    app = _table(usage + _OPTIONS, *(((name,), _fitting(usage, sets)) for name, sets in zip("abc", taken, strict=True)))
    literals = ["-q", "a", "b", "c"]
    offered = [name for name in _offered(app, typed) if name in literals]
    leads_on = [
        name for name in literals if any(_bound(app, [*typed, name, *tail]) for tail in ([], ["a"], ["b"], ["c"]))
    ]
    assert_that(offered).described_as(f"{usage} {taken} after {typed}").is_equal_to(leads_on)


_SHARED_LINE = st.sampled_from(
    [
        "a [--format=<f>] [--level=<n>]",
        "(a | b) [--format=<f>] [--level=<n>]",
        "<x> a [--format=<f>] [--level=<n>]",
        "[a] b [--format=<f>] [--level=<n>]",
        "a [b] [--format=<f>] [-q]",
        "[<x>] [--format=<f>] [--level=<n>]",
    ]
)
_PATHS = st.sampled_from([("a",), ("b",), ("a", "b"), ()])
_WORDS = ["a", "b", "w", "-q", "--format=json", "--format=table", "--level=json", "--level=table"]
_TAILS = [[], *([word] for word in _WORDS), *([first, second] for first in _WORDS[:4] for second in _WORDS[:4])]


def _lost(lines, registered, typed):
    """The table of a generated case, and the candidates it leaves out for a value typed for an option."""
    usage = "Usage:" + "".join(f"\n  p {line}" for line in lines)
    app = _table(usage + _OPTIONS, *((command_path, _fitting(usage, sets)) for command_path, sets in registered))
    offered = _offered(app, typed)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(_completion, "_refusing", lambda *_given: set())
        unsifted = _offered(app, typed)
    assert_that([name for name in offered if name not in unsifted]).is_empty()
    return app, [name for name in unsifted if name not in offered]


_ONE_KIND = st.sampled_from(_KINDS[:2]).map(lambda kind: [kind])
_NARROW = st.one_of(st.none(), *[st.tuples(_ONE_KIND, _ONE_KIND)] * 4)
_CASES = (
    st.lists(_SHARED_LINE, min_size=1, max_size=3),
    st.lists(st.tuples(_PATHS, _NARROW), min_size=1, max_size=3, unique_by=lambda one: one[0]),
    st.lists(st.sampled_from(_WORDS), max_size=1).flatmap(
        lambda words: st.sampled_from(_WORDS[4:]).map(lambda valued: [valued, *words])
    ),
)


@settings(max_examples=300)  # a case in ten leaves a candidate out, and each one left out is followed through 25 argv
@given(*_CASES)
def test_a_table_leaves_out_no_candidate_that_a_bound_line_goes_on_from_and_gains_none(lines, registered, typed):
    app, lost = _lost(lines, registered, typed)
    bound = [(name, tail) for name in lost for tail in _TAILS if _bound(app, [*typed, name, *tail])]
    assert_that(bound).described_as(f"{lines} {registered} after {typed}").is_empty()


def test_the_generated_tables_do_leave_candidates_out():
    registered = [(("a",), (["table"], ["yaml", "table"]))]
    # `b` alone is run by no handler, and `a b` by the one that refuses `json`
    lines = ["[a] b [--format=<f>] [--level=<n>]", "a [b] [--format=<f>] [-q]"]
    assert_that(_lost(lines, registered, ["--format=json"])[1]).is_equal_to(
        ["--level", "--level=table", "--level=yaml", "-q", "a", "b"]
    )
    assert_that(_lost(lines, registered, ["--format=table"])[1]).is_empty()
