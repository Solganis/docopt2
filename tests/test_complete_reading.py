import dataclasses
import itertools
import pathlib
from typing import Literal

import pytest
from assertpy2 import assert_that
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from docopt2 import Dispatch, DocoptExit, _completion, complete, docopt
from docopt2._completion import _complete, _finished, _next_word, _read
from docopt2._parser import MatchBudget, Tokens, parse_argv


def _schema(**fields):
    return dataclasses.make_dataclass("Bound", list(fields.items()))


def _one_of(*values):
    return Literal[values] | None


def _each_of(*values):
    return list[Literal[values]] | Literal[values] | None


def _binds(doc, argv, schema):
    try:
        docopt(doc, argv, schema=schema, complete=False, help=False)
    except DocoptExit:
        return False
    return True


_TWO_LINES = "Usage:\n  p a <x> <y>\n  p <x> b <z>\n"
_TEXT_OR_COMMAND = "Usage:\n  p [<y>]\n  p [<y> a (<y> | a)]\n  p [a]\n"


@pytest.mark.parametrize(
    ("doc", "schema", "typed", "offered"),
    [
        # the first positional that may be left out takes the word: `q` typed first is an `<x>`, which refuses it
        ("Usage: p [<x>] [<y>]", _schema(x=_one_of("p", "r"), y=_one_of("q", "r")), [], ["p", "r"]),
        ("Usage: p [<x>] [<y>]", _schema(x=_one_of("p", "r"), y=_one_of("q", "r")), ["p"], ["q", "r"]),
        # of two branches that take the word, the first is read
        ("Usage: p (<y> | <x>)", _schema(x=_one_of("p", "r"), y=_one_of("q", "r")), [], ["q", "r"]),
        # `a b` is the command `a` and an `<x>`, or an `<x>` and the command `b`: the first line is the one read
        (_TWO_LINES, _schema(x=str, y=_one_of("json"), z=_one_of("yaml")), ["a", "b"], ["json"]),
        (_TWO_LINES, _schema(x=str, y=_one_of("json"), z=_one_of("yaml")), ["c", "b"], ["yaml"]),
        # a word typed first is a `<name>`, whatever it says: no `<mode>` is offered before a name stands
        ("Usage: p [<name>] [<mode>]", _schema(name=str | None, mode=_one_of("fast", "slow")), [], []),
        (
            "Usage: p [<name>] [<mode>]",
            _schema(name=str | None, mode=_one_of("fast", "slow")),
            ["ann"],
            ["fast", "slow"],
        ),
        # `a` typed first is read as a `<y>`, which refuses it, though a path of the walk reads it as the command
        (_TEXT_OR_COMMAND, _schema(y=_each_of("q")), ["a"], ["a"]),
        (_TEXT_OR_COMMAND, _schema(y=_each_of("q")), ["q"], ["a", "q"]),
    ],
)
def test_a_value_is_offered_for_the_element_that_the_parser_gives_the_next_word_to(doc, schema, typed, offered):
    assert_that(complete(doc, [*typed, ""], schema=schema)).is_equal_to(offered)


@pytest.mark.parametrize(
    ("argv", "bound"),
    [(["a", "b", "json"], True), (["a", "b", "yaml"], False), (["c", "b", "yaml"], True), (["c", "b", "json"], False)],
)
def test_the_parse_binds_what_was_offered_after_words_that_two_lines_read_in_two_ways(argv, bound):
    schema = _schema(x=str, y=_one_of("json"), z=_one_of("yaml"))
    assert_that(_binds(_TWO_LINES, argv, schema)).is_equal_to(bound)
    assert_that(argv[2] in complete(_TWO_LINES, [*argv[:2], ""], schema=schema)).is_equal_to(bound)


@pytest.mark.parametrize(
    ("doc", "schema", "typed", "offered"),
    [
        # `-f` is on the second line alone, so a line that holds it gives the word to `<y>`
        ("Usage:\n  p <x>\n  p <y> [-f]\n", _schema(x=_one_of("p"), y=_one_of("q"), f=bool), [], ["-f", "p", "q"]),
        ("Usage:\n  p <x>\n  p <y> [-f]\n", _schema(x=_one_of("p"), y=_one_of("q"), f=bool), ["-f"], ["q"]),
        # the first line needs `-f`: it reads a line finished with the option, the second reads one without
        ("Usage:\n  p <y> -f\n  p <x> [-f]\n", _schema(x=_one_of("p"), y=_one_of("q"), f=bool), [], ["-f", "p", "q"]),
        ("Usage:\n  p <y> -f\n  p <x> [-f]\n", _schema(x=_one_of("p"), y=_one_of("q"), f=bool), ["-f"], ["q"]),
        # two lines that differ by an option alone are two lines to finish
        (
            "Usage:\n  p <x> -f\n  p <y> -g\n",
            _schema(x=_one_of("p"), y=_one_of("q"), f=bool, g=bool),
            [],
            ["-f", "-g", "p", "q"],
        ),
    ],
)
def test_a_path_is_finished_with_the_options_it_left_and_without_them(doc, schema, typed, offered):
    assert_that(complete(doc, [*typed, ""], schema=schema)).is_equal_to(offered)


def test_a_flag_that_the_finished_line_gives_is_held_against_its_field_as_a_word_is():
    doc = "Usage: p <x> -f"
    # every line of the usage holds `-f`, and this field refuses a flag that is given: no value leads to a bound line
    refusing = _schema(x=_one_of("one"), f=Literal[False])
    assert_that(complete(doc, [""], schema=refusing)).is_equal_to(["-f"])
    assert_that(_binds(doc, ["one", "-f"], refusing)).is_false()
    assert_that(complete(doc, [""], schema=_schema(x=_one_of("one"), f=bool))).is_equal_to(["-f", "one"])


def test_what_a_repeated_element_holds_is_held_against_its_field_as_the_parse_gives_it():
    twice = "Usage: p <x> -f -f"
    # the parse gives the flag as the count 2, which `Literal[True]` refuses and `Literal[2]` takes
    assert_that(complete(twice, [""], schema=_schema(x=_one_of("one"), f=Literal[True]))).is_equal_to(["-f"])
    assert_that(_binds(twice, ["one", "-f", "-f"], _schema(x=_one_of("one"), f=Literal[True]))).is_false()
    assert_that(complete(twice, [""], schema=_schema(x=_one_of("one"), f=Literal[2]))).is_equal_to(["-f", "one"])
    counted = _schema(x=_one_of("one"), f=Literal[1, 2])
    assert_that(complete("Usage: p <x> (-f)...", ["-f", "-f", ""], schema=counted)).is_equal_to(["-f", "one"])
    assert_that(complete("Usage: p <x> (-f)...", ["-f", "-f", "-f", ""], schema=counted)).is_equal_to(["-f"])
    listed = "Usage: p (<x>)... <y>"
    # a list that is whole is asked about as the list it is: a field of one text refuses it, whatever the text
    assert_that(complete(listed, ["p", ""], schema=_schema(x=_each_of("p", "q"), y=_one_of("r")))).is_equal_to(
        ["p", "q", "r"]
    )
    assert_that(complete(listed, ["p", ""], schema=_schema(x=_one_of("p", "q"), y=_one_of("r")))).is_equal_to(
        ["p", "q"]
    )


def test_a_line_is_not_read_where_every_value_of_a_later_word_is_a_command():
    doc = "Usage:\n  p <bad> stop\n  p <x> <y>\n"
    only_stop = _schema(bad=_one_of("ok"), x=_one_of("one"), y=_one_of("stop"))
    # the one `<y>` there is, is `stop`: `one stop` is the first line, where `<bad>` refuses `one`
    assert_that(complete(doc, [""], schema=only_stop)).is_equal_to(["ok"])
    assert_that(_binds(doc, ["one", "stop"], only_stop)).is_false()
    more = _schema(bad=_one_of("ok"), x=_one_of("one"), y=_one_of("stop", "go"))
    assert_that(complete(doc, [""], schema=more)).is_equal_to(["ok", "one"])
    assert_that(_binds(doc, ["one", "go"], more)).is_true()
    # the argument of an option is read by its option, never as a command
    doc = "Usage:\n  p <x> --mode=<m>\n  p stop\n"
    schema = _schema(x=_one_of("one"), mode=_one_of("stop"))
    assert_that(complete(doc, [""], schema=schema)).is_equal_to(["--mode", "--mode=stop", "one", "stop"])
    assert_that(_binds(doc, ["one", "--mode=stop"], schema)).is_true()


def test_a_value_that_is_also_a_command_is_read_again_as_itself():
    doc = "Usage:\n  p <y> a\n  p <x> <z>\n"
    schema = _schema(y=_one_of("k"), x=_one_of("m"), z=_one_of("a", "b"))
    # `m b` is the second usage line. `m a` is the first, a `<y>` and the command: `<y>` refuses `m`
    assert_that(complete(doc, ["m", ""], schema=schema)).is_equal_to(["b"])
    assert_that([_binds(doc, ["m", value], schema) for value in ("a", "b")]).is_equal_to([False, True])
    # read as itself, `stop` is still the `<x>` of the first line here, though the second has a command of that name
    doc = "Usage:\n  p go <x>\n  p <y> stop\n"
    schema = _schema(x=_one_of("stop", "now"), y=_one_of("k"))
    assert_that(complete(doc, ["go", ""], schema=schema)).is_equal_to(["now", "stop"])
    assert_that(_binds(doc, ["go", "stop"], schema)).is_true()


_ONE_OR_ROUNDS = "Usage:\n  p [<y>]\n  p (<x>)...\n"


def test_a_value_that_shows_only_on_a_line_of_two_rounds_is_offered():
    schema = _schema(x=_each_of("p"), y=_one_of("q"))
    # one word is a `<y>`, and two are `<x>`: `p` leads to a line the parse binds only with a second round
    assert_that(complete(_ONE_OR_ROUNDS, [""], schema=schema)).is_equal_to(["p", "q"])
    assert_that([_binds(_ONE_OR_ROUNDS, argv, schema) for argv in (["p"], ["p", "p"], ["q"])]).is_equal_to(
        [False, True, True]
    )
    assert_that(complete(_ONE_OR_ROUNDS, ["p", ""], schema=schema)).is_equal_to(["p"])
    assert_that(complete(_ONE_OR_ROUNDS, ["q", ""], schema=schema)).is_empty()


def test_the_second_round_may_be_another_branch_of_what_is_repeated():
    doc = "Usage:\n  p (<y>)...\n  p (<x> | -f)...\n"
    schema = _schema(x=_each_of("p"), y=_each_of("q"), f=bool)
    # any number of words are `<y>`: `p` is an `<x>` only on a line that holds `-f`, a round of the other branch
    assert_that(complete(doc, [""], schema=schema)).is_equal_to(["-f", "p", "q"])
    assert_that([_binds(doc, argv, schema) for argv in (["p"], ["p", "p"], ["p", "-f"])]).is_equal_to(
        [False, False, True]
    )


@pytest.mark.parametrize(
    ("doc", "schema", "typed", "files"),
    [
        ("Usage: p [<name>] [<file>]", _schema(name=str | None, file=pathlib.Path | None), [], False),
        ("Usage: p [<name>] [<file>]", _schema(name=str | None, file=pathlib.Path | None), ["ann"], True),
        ("Usage: p [<file>] [<name>]", _schema(name=_one_of("ann"), file=pathlib.Path | None), [], True),
        ("Usage: p [<file>] [<name>]", _schema(name=_one_of("ann"), file=pathlib.Path | None), ["notes"], False),
    ],
)
def test_a_file_name_is_asked_for_where_the_parser_gives_the_next_word_to_a_path(doc, schema, typed, files):
    assert_that(_complete(doc, [*typed, ""], [schema])[1]).is_equal_to(files)


def test_no_more_paths_are_finished_than_the_limit_and_the_names_are_offered_all_the_same(monkeypatch):
    doc = "Usage:\n  p <x> [--force]\n  p <y> c\n"
    schema = _schema(x=_one_of("one"), y=_one_of("two"), force=bool)
    assert_that(complete(doc, [""], schema=schema)).is_equal_to(["--force", "one", "two"])
    monkeypatch.setattr(_completion, "_PATHS_FINISHED", 1)
    assert_that(complete(doc, [""], schema=schema)).is_equal_to(["--force", "one"])
    monkeypatch.setattr(_completion, "_PATHS_FINISHED", 0)
    assert_that(complete(doc, [""], schema=schema)).is_equal_to(["--force"])


def _line(doc, typed, times=1):
    options, pattern = _read(doc)
    return pattern, _finished(parse_argv(Tokens(typed), list(options)), tuple(pattern.flat()) * times)


def test_a_line_whose_reading_costs_more_than_a_parse_may_offers_nothing():
    fields = (lambda _key: ["one"]), None, (lambda _key: True)
    pattern, line = _line("Usage: p <x>", [])
    assert_that(_next_word(pattern, line, lambda _taken: fields, set())).is_equal_to((["one"], True))
    with MatchBudget(1):
        assert_that(_next_word(pattern, line, lambda _taken: fields, set())).is_equal_to(([], False))


def test_a_line_that_the_usage_does_not_take_or_that_nothing_binds_offers_nothing():
    fields = (lambda _key: ["one"]), None, (lambda _key: True)
    # two words for one positional: the match that takes the first leaves the second over
    pattern, line = _line("Usage: p <x>", [], times=2)
    assert_that(_next_word(pattern, line, lambda _taken: fields, set())).is_equal_to(([], False))
    pattern, line = _line("Usage: p <x>", [])
    assert_that(_next_word(pattern, line, lambda _taken: None, set())).is_equal_to(([], False))


def test_paths_that_end_alike_are_read_once(monkeypatch):
    read = []
    next_word = _completion._next_word
    monkeypatch.setattr(_completion, "_next_word", lambda *asked: read.append(asked[1]) or next_word(*asked))
    schema = _schema(a=_each_of("one"), b=_each_of("one"), c=_each_of("one"))
    # nine ways to read the two words typed and three branches for the next: two lines, of one more word or two
    assert_that(complete("Usage: prog (<a> | <b> | <c>)...", ["one", "one", ""], schema=schema)).is_equal_to(["one"])
    assert_that([len(line) for line in read]).is_equal_to([3, 4])


def test_a_line_is_finished_with_a_stand_in_for_each_word_not_typed_and_the_separator_left_out():
    doc = "Usage: p <x> go <y> [--o=<v>] [-f]"
    options, pattern = _read(doc)
    typed = parse_argv(Tokens(["--", "first"]), list(options))
    line = _finished(typed, tuple(pattern.flat()))
    assert_that([(leaf.name, leaf.value) for leaf in line]).is_equal_to(
        [(None, "first"), (None, "\1"), (None, "go"), (None, "\0"), ("--o", "\0"), ("-f", True)]
    )


def _table(doc, *registered):
    app = Dispatch(doc)
    for command_path, schema in registered:
        app.on(*command_path, schema=schema)(lambda arguments, ran=command_path: ran)
    return app


def _offered(app, typed):
    return _complete(app.doc, [*typed, ""], [], app._table())


def _run(app, argv):
    try:
        return app.run(argv, complete=False, help=False)
    except DocoptExit as refused:
        return str(refused).splitlines()[0]


def test_a_table_offers_the_values_of_the_handler_that_is_run_for_the_finished_line():
    app = _table(_TWO_LINES, (("a",), _schema(y=_one_of("json"))), (("b",), _schema(z=_one_of("yaml"))))
    # both handlers are in reach after `a b`, and the first line is the one read: its handler is the one run
    assert_that(_offered(app, ["a", "b"])).is_equal_to((["json"], False))
    assert_that([_run(app, ["a", "b", value]) for value in ("json", "yaml")]).is_equal_to(
        [("a",), "error: invalid value for `<y>`"]
    )
    assert_that(_offered(app, ["c", "b"])).is_equal_to((["yaml"], False))
    assert_that(_run(app, ["c", "b", "yaml"])).is_equal_to(("b",))


_SHARED = "Usage: app (deploy | status) <env> [--format=<f>]"
_LATER = "Usage: app <env> (deploy | status)"
_DEPLOY = _schema(env=_one_of("dev", "prod"), format=_one_of("json", "yaml"))
_STATUS = _schema(env=_one_of("dev", "stage"), format=_one_of("yaml", "table"))


def test_on_a_line_that_two_commands_share_each_command_is_offered_its_own_handler_s_values():
    app = _table(_SHARED, (("deploy",), _DEPLOY), (("status",), _STATUS))
    assert_that(_offered(app, ["deploy"])[0]).is_equal_to(["--format", "--format=yaml", "dev", "prod"])
    assert_that(_offered(app, ["status"])[0]).is_equal_to(["--format", "--format=yaml", "dev", "stage"])
    # the value of an option is read by its name on any line: it is offered where each handler in reach takes it
    assert_that(_offered(app, ["deploy", "dev", "--format"])[0]).is_equal_to(["yaml"])


def test_a_value_is_offered_for_each_handler_that_a_command_typed_later_may_choose():
    app = _table(
        _LATER, (("deploy",), _schema(env=_one_of("dev", "prod"))), (("status",), _schema(env=_one_of("dev", "stage")))
    )
    assert_that(_offered(app, [])[0]).is_equal_to(["dev", "prod", "stage"])
    assert_that([_run(app, argv) for argv in (["prod", "deploy"], ["stage", "status"])]).is_equal_to(
        [("deploy",), ("status",)]
    )


_BARE_LINE = "Usage:\n  p a <x>\n  p <x>\n"


@pytest.mark.parametrize(
    ("registered", "first", "after_a"),
    [
        # no handler is run for the second line: a value there leads to a line the table refuses
        ([(("a",), _schema(x=_one_of("one")))], ["a"], ["one"]),
        ([(("a",), _schema(x=_one_of("one"))), ((), _schema(x=_one_of("two")))], ["a", "two"], ["one"]),
        # a handler with no schema takes the line as it is: it has no value to offer
        ([(("a",), _schema(x=_one_of("one"))), ((), None)], ["a"], ["one"]),
        ([(("a",), None), ((), _schema(x=_one_of("two")))], ["a", "two"], []),
    ],
)
def test_a_line_offers_the_values_of_its_own_handler_and_none_where_no_handler_or_no_schema_is(
    registered, first, after_a
):
    app = _table(_BARE_LINE, *registered)
    assert_that(_offered(app, [])[0]).is_equal_to(first)
    assert_that(_offered(app, ["a"])[0]).is_equal_to(after_a)


def test_a_word_typed_is_held_against_the_handler_run_for_the_finished_line():
    app = _table("Usage: app (add | rm) <name> <role>", (("add",), _schema(name=_one_of("ann"), role=_one_of("admin"))))
    app.on("rm", schema=_schema(name=str, role=_one_of("guest")))(lambda arguments: "rm")
    assert_that(_offered(app, ["add", "ann"])[0]).is_equal_to(["admin"])
    assert_that(_offered(app, ["add", "zed"])[0]).is_empty()
    assert_that(_offered(app, ["rm", "zed"])[0]).is_equal_to(["guest"])


def test_a_handler_whose_path_names_an_option_is_run_where_the_line_gives_the_option_or_its_default():
    fast = _table(
        "Usage: app <mode> [--fast]",
        (("--fast",), _schema(mode=_one_of("x"), fast=bool)),
        ((), _schema(mode=_one_of("y"), fast=bool)),
    )
    assert_that(_offered(fast, [])[0]).is_equal_to(["--fast", "x", "y"])
    assert_that(_offered(fast, ["--fast"])[0]).is_equal_to(["x"])
    assert_that([_run(fast, argv) for argv in (["x", "--fast"], ["y"])]).is_equal_to([("--fast",), ()])
    doc = "Usage: app <mode> [--format=<f>]\n\nOptions:\n  --format=<f>  Format [default: json].\n"
    default = _table(doc, (("--format",), _schema(mode=_one_of("x"), format=str)), ((), _schema(mode=_one_of("y"))))
    # the default makes the option given on every line, as it is for `Dispatch.run`
    assert_that(_offered(default, [])[0]).is_equal_to(["--format", "x"])
    assert_that([_run(default, argv) for argv in (["x"], ["y"])]).is_equal_to(
        [("--format",), "error: invalid value for `<mode>`"]
    )
    # so does the default that an `Arguments:` section states for a positional
    doc = "Usage: app [<mode>] <name>\n\nArguments:\n  <mode>  Mode [default: fast].\n"
    stated = _table(doc, (("<mode>",), _schema(name=_one_of("x"), mode=str)), ((), _schema(name=_one_of("y"))))
    assert_that(_offered(stated, [])[0]).is_equal_to(["x"])
    assert_that([_run(stated, argv) for argv in (["x"], ["y"])]).is_equal_to(
        [("<mode>",), "error: invalid value for `<name>`"]
    )


_VALUES = ["p", "q", "r"]
_ATOMS = st.sampled_from(["a", "b", "<x>", "<y>"])
# a usage line of up to three leaves, none of them repeated: every argv it takes has three words at most
_LINES = st.recursive(
    _ATOMS,
    lambda inner: st.one_of(
        st.tuples(inner, inner).map(" ".join),
        inner.map("[{}]".format),
        st.tuples(inner, inner).map(lambda pair: f"({pair[0]} | {pair[1]})"),
    ),
    max_leaves=3,
)
_SETS = st.lists(st.sampled_from(_VALUES), min_size=1, max_size=2, unique=True)
_PATHS = st.lists(st.lists(st.sampled_from("ab"), max_size=2, unique=True).map(tuple), min_size=1, max_size=3)
_TOKENS = ["a", "b", *_VALUES]
_UP_TO_ONE = [list(argv) for size in range(2) for argv in itertools.product(_TOKENS, repeat=size)]
_UP_TO_TWO = [list(argv) for size in range(3) for argv in itertools.product(_TOKENS, repeat=size)]
_UP_TO_THREE = [list(argv) for size in range(4) for argv in itertools.product(_TOKENS, repeat=size)]


def _generated(lines, sets):
    doc = "Usage:\n" + "".join(f"  p {line}\n" for line in lines)
    fields = {name: _each_of(*values) for name, values in zip("xy", sets, strict=True) if f"<{name}>" in doc}
    return doc, _schema(**fields)


def _never_bound(offered_after, binds):
    """The values offered after a word typed or after none, with none of the lines they can lead to bound: each
    of those lines has three words at most, so all of them are tried."""
    offers = [(typed, value) for typed in _UP_TO_ONE for value in offered_after(typed) if value in _VALUES]
    assume(offers)
    return [(typed, value) for typed, value in offers if not any(binds([*typed, value, *tail]) for tail in _UP_TO_TWO)]


@settings(max_examples=60)  # 4 ms an example: each value offered is followed through 31 argv
@given(st.lists(_LINES, min_size=1, max_size=3), st.tuples(_SETS, _SETS))
def test_a_value_offered_to_a_schema_is_bound_on_some_line_that_the_usage_takes(lines, sets):
    doc, schema = _generated(lines, sets)
    never = _never_bound(
        lambda typed: complete(doc, [*typed, ""], schema=schema), lambda argv: _binds(doc, argv, schema)
    )
    assert_that(never).described_as(f"{doc}{sets}").is_empty()


@settings(max_examples=60)  # 4 ms an example, as above
@given(st.lists(_LINES, min_size=1, max_size=3), _PATHS, st.lists(st.tuples(_SETS, _SETS), min_size=3, max_size=3))
def test_a_value_offered_by_a_table_is_bound_on_some_line_that_a_handler_is_run_for(lines, paths, sets):
    doc = _generated(lines, sets[0])[0]
    app = _table(doc, *((path, _generated(lines, sets[at])[1]) for at, path in enumerate(paths)))
    never = _never_bound(lambda typed: _offered(app, typed)[0], lambda argv: isinstance(_run(app, argv), tuple))
    assert_that(never).described_as(f"{doc}{paths} {sets}").is_empty()


@settings(max_examples=60)  # 20 ms an example: 156 argv parsed for each usage
@given(st.lists(_LINES, min_size=1, max_size=3), st.tuples(_SETS, _SETS))
def test_each_value_of_a_line_the_parse_binds_was_offered_in_its_place(lines, sets):
    doc, schema = _generated(lines, sets)
    places = [
        (argv, cut)
        for argv in _UP_TO_THREE
        if _binds(doc, argv, schema)
        for cut, token in enumerate(argv)
        if token in _VALUES
    ]
    assume(places)
    missed = [(argv, cut) for argv, cut in places if argv[cut] not in complete(doc, [*argv[:cut], ""], schema=schema)]
    assert_that(missed).described_as(f"{doc}{sets}").is_empty()
