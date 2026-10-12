import dataclasses
import itertools
from typing import Literal

import pytest
from assertpy2 import assert_that
from hypothesis import given, settings
from hypothesis import strategies as st

from docopt2 import Dispatch, DocoptExit, _completion, check, complete, docopt
from docopt2._completion import _complete, _in_reach, _read, _Steps
from docopt2._parser import (
    GIVEN_LIMIT,
    formal_usage,
    given_together,
    line_binders,
    most_specific,
    parse_defaults,
    parse_pattern,
    single_usage_section,
)


def _pattern(doc):
    return parse_pattern(formal_usage(single_usage_section(doc)), parse_defaults(doc))


def _together(usage, names="abcdefghij"):
    sets = given_together(_pattern(f"Usage: p {usage}"), set(names))
    return sets if sets is None else sorted("".join(sorted(one)) for one in sets)


@pytest.mark.parametrize(
    ("paths", "given", "run"),
    [
        ([("a",), ("a", "b"), ()], "ab", 1),
        ([("a",), ("a", "b"), ()], "a", 0),
        ([("a",), ("a", "b"), ()], "b", 2),
        ([("a",), ("a", "b")], "b", None),
        ([("a",), ("b",)], "ab", 0),
        ([("b",), ("a",)], "ab", 0),
        ([("a", "b"), ("b", "a")], "ab", 0),
        ([], "ab", None),
    ],
)
def test_a_table_runs_the_longest_path_given_whole_and_the_earliest_of_equals(paths, given, run):
    assert_that(most_specific(paths, set(given))).is_equal_to(run)


@pytest.mark.parametrize(
    ("usage", "together"),
    [
        ("a <x> -f", ["a"]),
        ("(a | b)", ["a", "b"]),
        ("[a] b", ["ab", "b"]),
        ("[a b]", ["", "a", "ab", "b"]),
        ("[(a | b)] c", ["ac", "bc", "c"]),
        ("(a | b)...", ["a", "ab", "b"]),
        ("(a [b] | c)...", ["a", "ab", "abc", "ac", "c"]),
        ("a (b | c) [d]", ["ab", "abd", "ac", "acd"]),
        ("<x> [options]", [""]),
    ],
)
def test_the_sets_of_commands_one_argv_of_a_line_can_give_together(usage, together):
    assert_that(_together(usage)).is_equal_to(together)


def test_only_the_names_asked_about_are_told_apart():
    assert_that(_together("(a | b) [c]", names="c")).is_equal_to(["", "c"])


@pytest.mark.parametrize(
    "usage",
    [
        "[a] [b] [c] [d] [e] [f] [g] [h] [i]",
        "[a] [b] [c] [d] [e] [f] [g] [h] [i] [j]",
        "x ([a] [b] [c] [d] [e] [f] [g] [h] [i])",
        "([a] [b] [c] [d] [e] [f] [g] [h] i | [a] [b] [c] [d] [e] [f] [g] [h] j)",
        "(a | b | c | d | e | f | g | h | i)...",
    ],
)
def test_a_line_that_gives_more_sets_than_the_limit_is_read_as_giving_any(usage):
    assert_that(_together(usage)).is_none()
    eight = _together("[a] [b] [c] [d] [e] [f] [g] [h]")
    assert_that(len(eight)).is_equal_to(GIVEN_LIMIT)


_TOOL = """Usage:
  app deploy <env> [--format=<f>]
  app status [--format=<f>]
  app user (add | rm) <name>
  app user
  app

Options:
  --format=<f>  Output format.
"""


@pytest.mark.parametrize(
    ("paths", "binders"),
    [
        ([("deploy",), ("status",)], [{0}, {1}, {None}, {None}, {None}]),
        ([("deploy",), ()], [{0}, {1}, {1}, {1}, {1}]),
        ([("user", "add"), ("user",)], [{None}, {None}, {0, 1}, {1}, {None}]),
        ([("user",), ("user", "add"), ("user", "rm")], [{None}, {None}, {1, 2}, {0}, {None}]),
        ([("user",), ("user",)], [{None}, {None}, {0}, {0}, {None}]),
        # a path that names an option may be run for any line, and one that names what the usage lacks for none
        ([("deploy",), ("--format",)], [{0, 1}, {None, 1}, {None, 1}, {None, 1}, {None, 1}]),
        ([("--format",), ("deploy",), ("status",)], [{0, 1}, {0, 2}, {None, 0}, {None, 0}, {None, 0}]),
        ([("deploy",), ("sever",), ("user", "<name>")], [{0, 2}, {None, 2}, {None, 2}, {None, 2}, {None, 2}]),
    ],
)
def test_the_handlers_a_table_can_run_for_each_usage_line(paths, binders):
    assert_that(line_binders(_pattern(_TOOL), paths)).is_equal_to(binders)


_WIDE = "Usage:\n  p [a] [b] [c] [d] [e] [f] [g] [h] [i] <x> [--force]\n  p z\n"


def test_a_line_read_as_giving_any_set_can_be_run_for_by_every_handler_of_commands_and_by_none():
    paths = [*((name,) for name in "abcdefghi"), ("z",), ("a", "z"), ()]
    assert_that(line_binders(_pattern(_WIDE), paths)).is_equal_to([{None, *range(12)}, {9}])
    # one path that names all nine and no fallback: an argv of the line that gives none of them runs nothing
    assert_that(line_binders(_pattern(_WIDE), [tuple("abcdefghi")])).is_equal_to([{None, 0}, {None}])
    # the paths name one of its nine commands: two sets, and the line is worked out
    assert_that(line_binders(_pattern(_WIDE), [("a",), ("z",), ()])).is_equal_to([{0, 2}, {1}])


def test_the_one_handler_of_a_line_read_as_giving_any_set_does_not_judge_the_typed_words():
    app = Dispatch(_WIDE)
    app.on(*"abcdefghi", schema=dataclasses.make_dataclass("Wide", [("x", Literal["p"] | None)]))(_nothing)
    # `zz` alone runs no handler, so the schema of the one there is has no say over it
    assert_that(_offered(app, ["zz"])).is_equal_to(["--force"])


@dataclasses.dataclass
class _Deploy:
    env: Literal["dev", "prod"]
    format: Literal["json", "yaml"] | None


@dataclasses.dataclass
class _Status:
    format: Literal["yaml", "table"] | None


@dataclasses.dataclass
class _Named:
    name: Literal["ann", "bob"]


def _nothing(arguments):
    return arguments


def _tool(*registered):
    app = Dispatch(_TOOL)
    for command_path, schema in registered:
        app.on(*command_path, schema=schema)(_nothing)
    return app


def _said(app):
    return [(found.level, found.summary) for found in app.check()]


def test_a_schema_is_held_against_the_lines_its_handler_is_run_for_and_not_the_whole_usage():
    app = _tool((("deploy",), _Deploy), (("status",), _Status), (("user",), None), ((), None))
    # held against the whole usage, `<env>` may be absent: on the lines of `status` and `user`
    assert_that([found.summary for found in check(_TOOL, schema=_Deploy)]).is_equal_to(
        ["usage element `<env>` may be absent, but field `env` is not optional"]
    )
    assert_that(_said(app)).is_empty()


def test_a_finding_of_a_handler_s_schema_names_the_handler_and_points_into_its_own_lines():
    @dataclasses.dataclass
    class Wrong:
        env: str
        format: int | None

    app = _tool((("status",), Wrong), ((), Wrong))
    found = app.check()
    assert_that([(one.level, one.summary) for one in found]).is_equal_to(
        [
            ("error", "handler `status`: usage element `<env>` may be absent, but field `env` is not optional"),
            ("error", "the fallback handler: usage element `<env>` may be absent, but field `env` is not optional"),
        ]
    )
    usage = single_usage_section(_TOOL)
    # `--format` is written on the line of `deploy` first: a finding of `status` points at the line of `status`
    app = _tool((("status",), dataclasses.make_dataclass("Flagged", [("format", bool | None)])))
    (misfit,) = app.check()
    caret = misfit.snippets[0].carets[0]
    assert_that(misfit.summary).is_equal_to("handler `status`: field `format` does not fit usage element `--format`")
    assert_that(usage[: caret.start].splitlines()[-1].strip()).is_equal_to("app status [")
    assert_that(usage[caret.start : caret.end]).is_equal_to("--format=<f>")


def test_a_field_whose_element_the_handler_s_lines_never_give_must_be_optional():
    @dataclasses.dataclass
    class Loose:
        name: str | None
        env: str | None

    assert_that(_said(_tool((("status",), Loose)))).is_empty()
    assert_that(_said(_tool((("user", "add"), _Named), (("user", "rm"), _Named)))).is_empty()
    # the handler of `user` is run for `app user` too, where there is no name
    assert_that(_said(_tool((("user",), _Named)))).is_equal_to(
        [("error", "handler `user`: usage element `<name>` may be absent, but field `name` is not optional")]
    )


@pytest.mark.parametrize(
    ("registered", "said"),
    [
        ([(("sever",), None)], [("error", "handler `sever` can never run: the usage has no `sever`", None)]),
        (
            [(("deploi",), _Deploy)],
            [("error", "handler `deploi` can never run: the usage has no `deploi`", "did you mean `deploy`?")],
        ),
        (
            [(("user", "--force"), None)],
            [("error", "handler `user --force` can never run: the usage has no `--force`", None)],
        ),
        (
            [(("user",), None), (("user",), _Named)],
            [
                (
                    "warning",
                    "handler `user` can never run: another handler is run for every argv that gives its commands",
                    None,
                )
            ],
        ),
        (
            [(("deploy", "status"), None)],
            [("warning", "handler `deploy status` can never run: no usage line gives its commands together", None)],
        ),
        # a fallback that every line has a handler before is no finding: it is there in case one has none
        ([(("deploy",), None), (("status",), None), (("user",), None), ((), None), ((), _Status)], []),
    ],
)
def test_a_handler_no_argv_can_reach_is_reported_and_a_fallback_never_is(registered, said):
    found = _tool(*registered).check()
    assert_that([(one.level, one.summary, one.help) for one in found]).is_equal_to(said)


def test_a_handler_whose_path_names_an_option_is_held_against_every_line():
    app = _tool((("--format",), _Deploy))
    assert_that(_said(app)).is_equal_to(
        [("error", "handler `--format`: usage element `<env>` may be absent, but field `env` is not optional")]
    )


def test_the_check_of_a_table_holds_the_findings_of_its_usage_and_stops_at_a_usage_that_does_not_parse():
    unused = Dispatch("Usage: p go\n\nOptions:\n  --never  Declared and in no usage line.\n")
    unused.on("go", schema=_Status)(_nothing)
    assert_that([(one.level, one.summary) for one in unused.check()]).is_equal_to(
        [
            ("warning", "option `--never` is declared but never used"),
            ("error", "handler `go`: schema field `format` has no matching usage element"),
        ]
    )
    broken = Dispatch("Usage: p (go")
    broken.on("go", schema=_Status)(_nothing)
    assert_that([(one.level, one.summary) for one in broken.check()]).is_equal_to([("error", "unclosed `(`")])


def test_a_table_runs_the_handler_the_check_reads_its_lines_for():
    app = Dispatch(_TOOL)
    for command_path in (("user", "add"), ("user",), ()):
        app.on(*command_path)(lambda arguments, ran=command_path: ran)
    ran = [app.run(argv) for argv in (["user", "add", "x"], ["user", "rm", "x"], ["user"], ["status"], [])]
    assert_that(ran).is_equal_to([("user", "add"), ("user",), ("user",), (), ()])


def _offered(app, words):
    return _complete(app.doc, [*words, ""], [], app._table())[0]


def test_once_the_typed_words_leave_one_handler_its_schema_completes_the_line():
    app = _tool((("deploy",), _Deploy), (("status",), _Status), (("user", "add"), _Named), (("user",), None))
    assert_that(_offered(app, ["deploy"])).is_equal_to(["--format", "--format=json", "--format=yaml", "dev", "prod"])
    assert_that(_offered(app, ["status", "--format"])).is_equal_to(["table", "yaml"])
    assert_that(_offered(app, ["deploy", "dev", "--format"])).is_equal_to(["json", "yaml"])
    assert_that(_offered(app, ["deploy", "nowhere"])).is_empty()
    # `user (add | rm) <name>` is a line of two handlers: the names are those of the one run for the finished line
    assert_that(_offered(app, ["user", "add"])).is_equal_to(["ann", "bob"])
    assert_that(_offered(app, ["user", "rm"])).is_empty()
    assert_that(_offered(app, ["user", "rm", "zed"])).is_empty()
    assert_that(_offered(app, ["user"])).is_equal_to(["add", "rm"])


def test_while_several_handlers_are_in_reach_a_value_is_offered_where_each_takes_it_and_no_word_is_judged():
    app = _tool((("deploy",), _Deploy), (("status",), _Status), (("user", "add"), _Named), (("user",), None))
    # before a command every handler is in reach: `yaml` is the one format both that declare it take
    assert_that(_offered(app, [])).is_equal_to(["--format", "--format=yaml", "deploy", "status", "user"])
    assert_that(_offered(app, ["--format"])).is_equal_to(["yaml"])
    # nor is `json` judged, which the handler of `status` refuses: `status` is offered still
    assert_that(_offered(app, ["--format=json"])).is_equal_to(["deploy", "status"])
    assert_that(_offered(app, ["--format=json", "status"])).is_empty()


def test_a_line_shared_with_a_handler_of_no_schema_judges_no_typed_word():
    app = Dispatch("Usage: app (add | rm) <name> [--force]")
    app.on("add", schema=_Named)(_nothing)
    app.on("rm")(_nothing)
    # the handler of `rm` takes any name, and before the line is whole `rm` may still be what was meant
    assert_that(_offered(app, ["rm", "zed"])).is_equal_to(["--force"])
    assert_that(_offered(app, ["add", "zed"])).is_equal_to(["--force"])
    assert_that(_offered(app, ["add"])).is_equal_to(["--force", "ann", "bob"])
    alone = Dispatch("Usage: app (add | rm) <name> [--force]")
    alone.on(schema=_Named)(_nothing)
    assert_that(_offered(alone, ["rm", "zed"])).is_empty()


_TWICE_READ = "Usage:\n  p a <x> [--format=<f>]\n  p <x> b [--format=<f>]\n\nOptions:\n  --format=<f>  Format.\n"


def test_words_that_two_lines_read_in_two_ways_leave_the_handlers_of_both_in_reach():
    app = Dispatch(_TWICE_READ)
    app.on("a", schema=dataclasses.make_dataclass("First", [("format", Literal["json", "yaml"] | None)]))(
        lambda bound: ("a", bound.format)
    )
    app.on("b", schema=dataclasses.make_dataclass("Second", [("format", Literal["yaml", "table"] | None)]))(
        lambda bound: ("b", bound.format)
    )
    # `a b` is the command `a` and the text `b`, or the text `a` and the command `b`: the first line is the one read
    offered = _offered(app, ["a", "b", "--format"])
    assert_that(offered).is_equal_to(["yaml"])
    assert_that([app.run(["a", "b", "--format", value]) for value in offered]).is_equal_to([("a", "yaml")])
    assert_that(_bound_or_refused(app, ["a", "b", "--format", "table"])).is_equal_to("refused")
    # `a zz` is no line of the second handler
    assert_that(_offered(app, ["a", "zz", "--format"])).is_equal_to(["json", "yaml"])


def _bound_or_refused(app, argv):
    try:
        return app.run(argv)
    except DocoptExit:
        return "refused"


class _NoHash(type):
    __hash__ = None


def test_a_schema_class_that_cannot_be_hashed_stops_no_tab_press():
    @dataclasses.dataclass
    class Odd(metaclass=_NoHash):
        format: Literal["json"] | None

    app = Dispatch("Usage: p go [--format=<f>]")
    app.on("go", schema=Odd)(_nothing)
    app.on(schema=Odd)(_nothing)
    try:
        offered = _offered(app, ["go"])
    except TypeError as leaked:
        offered = f"leaked {leaked}"
    assert_that(offered).is_equal_to(["--format"])


def test_a_path_may_name_an_option_that_only_the_options_shortcut_holds():
    app = Dispatch("Usage: app go [options]\n\nOptions:\n  --force  Force it.\n")
    app.on("go", "--force", schema=_Status)(_nothing)
    assert_that([one.summary for one in app.check()]).is_equal_to(
        ["handler `go --force`: schema field `format` has no matching usage element"]
    )
    assert_that(_offered(app, ["go"])).is_equal_to(["--force"])


@pytest.mark.parametrize("words", [["-a", "-b", "-c", "-d", "-e", "-f", "-g", "-h", "wrong", ""], [""], ["-a", ""]])
def test_a_tab_press_costs_a_table_no_step_of_the_walk_beyond_what_its_usage_costs(words, monkeypatch):
    spent = []
    spend = _Steps.spend
    monkeypatch.setattr(_Steps, "spend", lambda steps: spent.append(1) or spend(steps))
    monkeypatch.setattr(_completion, "MATCH_LIMIT", 4000)
    # each line forks at a flag that was typed and at a word that may be left out, for as long as it is let
    line = "[-a] [-b] [-c] [-d] [-e] [-f] [-g] [-h] [w1] [w2] [w3] [w4] [w5] [w6] [w7] [w8]"
    doc = "Usage:\n" + "".join(f"  p {line} c{at} expected\n" for at in range(16))
    table = [((f"c{at}",), dataclasses.make_dataclass(f"Own{at}", [("expected", bool)])) for at in range(16)]
    by_usage = complete(doc, words)
    of_usage = len(spent)
    spent.clear()
    assert_that(_complete(doc, words, [], table)[0]).is_equal_to(by_usage)
    # which lines may take the words is read off the pattern, and the one walk there is, is the usage's own
    assert_that(of_usage).is_greater_than_or_equal_to(4000)
    assert_that(len(spent)).is_equal_to(of_usage)


@pytest.mark.parametrize(
    ("usage", "typed", "in_reach"),
    [
        # a round may leave its option for later: `c c -f -f` is an argv of the line
        ("(c -f)...", ["c", "c"], {0}),
        ("(c -f)...", ["c", "-f", "c"], {0}),
        ("(c -f)...", ["c", "z"], set()),
        ("c [<x>] d", ["c"], {0}),
        ("c [<x>] d", ["c", "d"], {0}),
        ("[c] d", ["d"], {None, 0}),
        ("c [<x>] d", ["c", "d", "d"], {0}),
        ("c [<x>] d", ["c", "d", "d", "d"], set()),
        ("c -- <x>", ["c", "--", "-f"], {0}),
        ("c [options]", ["c", "--other"], {0}),
        ("c", ["c", "--other"], set()),
        ("(c | <x> c)", ["z", "c"], {0}),
        ("(c | <x> c)", ["z", "z"], set()),
        ("[c] [c] [c]", ["c", "c", "c"], {None, 0}),
        ("[c] [c] [c]", ["c", "c", "c", "c"], set()),
        ("c --other=<v>", ["c", "--other"], {0}),
    ],
)
def test_a_line_may_take_the_typed_words_where_it_holds_their_options_and_reads_their_positionals_in_order(
    usage, typed, in_reach
):
    doc = f"Usage: p {usage}\n\nOptions:\n  -f  A flag.\n  --other=<v>  Another.\n"
    assert_that(_in_reach(*_read(doc), typed, [(("c",), None)])).is_equal_to(in_reach)


_ATOMS = st.sampled_from(["a", "b", "c", "<x>", "-f"])
_LINES = st.recursive(
    _ATOMS,
    lambda inner: st.one_of(
        st.tuples(inner, inner).map(" ".join),
        inner.map("[{}]".format),
        st.tuples(inner, inner).map(lambda pair: f"({pair[0]} | {pair[1]})"),
        inner.map("({})...".format),
    ),
    max_leaves=3,
)
_PATHS = st.lists(st.lists(st.sampled_from("abc"), max_size=2, unique=True).map(tuple), min_size=1, max_size=4)
_ARGVS = [list(argv) for size in range(4) for argv in itertools.product(["a", "b", "c", "z", "-f"], repeat=size)]


@settings(max_examples=40)  # 25 ms an example, 156 argv parsed for each line: the 300 of the profile would cost 8 s
@given(st.lists(_LINES, min_size=1, max_size=2), _PATHS)
def test_the_handler_a_table_runs_for_an_argv_of_a_line_is_one_the_line_is_read_as_bound_by(lines, paths):
    doc = "Usage:\n" + "".join(f"  p {line}\n" for line in lines)
    said = line_binders(_pattern(doc), paths)
    for line, binders in zip(lines, said, strict=True):
        for argv in _ARGVS:
            try:
                parsed = docopt(f"Usage: p {line}", argv, complete=False, help=False)
            except DocoptExit:
                continue
            run = most_specific(paths, [name for name in "abc" if parsed.get(name)])
            assert_that(binders).described_as(f"{line!r} with {argv} under {paths}").contains(run)


_TOKENS = ["a", "b", "c", "z", "-f"]
_TAILS = [list(tail) for size in range(3) for tail in itertools.product(_TOKENS, repeat=size)]


@settings(max_examples=100)  # 6 ms an example, 31 argv run for each: the 300 of the profile would cost 2 s
@given(st.lists(_LINES, min_size=1, max_size=3), _PATHS, st.lists(st.sampled_from(_TOKENS), max_size=2))
def test_the_handler_run_for_a_whole_argv_is_one_that_every_prefix_of_it_left_in_reach(lines, paths, prefix):
    doc = "Usage:\n" + "".join(f"  p {line}\n" for line in lines)
    app = Dispatch(doc)
    for at, command_path in enumerate(paths):
        app.on(*command_path)(lambda _arguments, at=at: at)
    try:
        reach = _in_reach(*_read(doc), prefix, app._table())
    except DocoptExit:
        return  # an option the usage does not have: nothing is completed after it
    for tail in _TAILS:
        try:
            run = app.run([*prefix, *tail], complete=False, help=False)
        except DocoptExit as refused:
            if "no handler is registered" not in str(refused):
                continue  # no line takes the argv
            run = None
        assert_that(reach).described_as(f"{doc!r} {prefix} then {tail} under {paths}").contains(run)


_OPTIONS = "\nOptions:\n  --o=<v>  An option.\n"
_BODIES = st.sampled_from(["<x>", "<x> [--o=<v>]", "[--o=<v>] <x>", "[--o=<v>]", "<x> <y>"])
_VALUES = st.lists(st.sampled_from(["p", "q", "r"]), min_size=1, max_size=3, unique=True)
_WORDS = st.lists(st.sampled_from(["a", "b", "p", "q", "r", "--o", "--o=p", "--o=r", "zz"]), max_size=3)


def _schema(xs, os):
    return dataclasses.make_dataclass(
        "Bound", [("x", Literal[tuple(xs)] | None), ("o", Literal[tuple(os)] | None), ("y", str | None)]
    )


@given(st.sampled_from("ab"), _BODIES, _BODIES, _VALUES, _VALUES, _VALUES, _VALUES, _WORDS)
def test_after_its_command_a_table_completes_a_line_as_the_handler_s_schema_completes_that_line_alone(
    command, first, second, first_x, first_o, second_x, second_o, after
):
    schemas = [_schema(first_x, first_o), _schema(second_x, second_o)]
    doc = f"Usage:\n  p a {first}\n  p b {second}\n{_OPTIONS}"
    table = [(("a",), schemas[0]), (("b",), schemas[1])]
    at = "ab".index(command)
    words = [command, *after, ""]
    alone = complete(f"Usage: p {command} {(first, second)[at]}\n{_OPTIONS}", words, schema=schemas[at])
    assert_that(_complete(doc, words, [], table)[0]).is_equal_to(alone)


@given(st.lists(_LINES, min_size=1, max_size=3), _WORDS)
def test_a_table_with_no_schema_completes_as_the_usage_does_and_one_fallback_as_its_schema_does(lines, words):
    doc = "Usage:\n" + "".join(f"  p {line}\n" for line in lines)
    schema = dataclasses.make_dataclass("Bound", [("x", Literal["p", "q"] | list[Literal["p", "q"]] | None)])
    assert_that(_complete(doc, [*words, ""], [], [(("a",), None), ((), None)])[0]).is_equal_to(
        complete(doc, [*words, ""])
    )
    assert_that(_complete(doc, [*words, ""], [], [((), schema)])[0]).is_equal_to(
        complete(doc, [*words, ""], schema=schema)
    )
