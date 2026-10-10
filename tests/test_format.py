from assertpy2 import assert_that
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from docopt2 import Arguments, DocoptExit, DocoptLanguageError, docopt, format_argv
from docopt2.hypothesis import argv_strategy

_GIT = (
    "Usage:\n"
    "  git push [--force] <remote>\n"
    "  git commit --message=<msg>\n"
    "  git add <path>...\n\n"
    "Options:\n"
    "  --force          Force.\n"
    "  --message=<msg>  Message.\n"
)


def _roundtrips(doc, argv):
    result = docopt(doc, argv, complete=False)
    return docopt(doc, format_argv(result, doc), complete=False) == result


def test_format_emits_only_provided_elements_in_long_form():
    result = docopt(_GIT, "push --force origin", complete=False)
    assert_that(format_argv(result, _GIT)).is_equal_to(["push", "--force", "origin"])


def test_format_omits_an_optional_left_at_its_default():
    result = docopt(_GIT, "push origin", complete=False)
    assert_that(format_argv(result, _GIT)).is_equal_to(["push", "origin"])  # no --force, it was not given


def test_format_selects_the_alternation_branch_the_result_took():
    assert_that(format_argv(docopt(_GIT, "commit --message=hi", complete=False), _GIT)).is_equal_to(
        ["commit", "--message=hi"]
    )
    assert_that(format_argv(docopt(_GIT, "add a b c", complete=False), _GIT)).is_equal_to(["add", "a", "b", "c"])


def test_format_reproduces_a_counted_flag_and_a_short_option():
    doc = "Usage: prog [-vvv] [-p <n>] <host>\n\nOptions:\n  -p <n>  Port."
    assert_that(format_argv(docopt(doc, "-v -v -v -p 80 h", complete=False), doc)).is_equal_to(
        ["-v", "-v", "-v", "-p", "80", "h"]  # count flag emitted thrice, short option as two tokens
    )


def test_format_reproduces_a_repeatable_valued_option():
    doc = "Usage: prog [--x=<v>]... <a>\n\nOptions:\n  --x=<v>  X."
    assert_that(format_argv(docopt(doc, "--x=1 --x=2 a", complete=False), doc)).is_equal_to(["--x=1", "--x=2", "a"])


def test_format_expands_the_options_shortcut():
    doc = "Usage: prog [options] <f>\n\nOptions:\n  -v  Verbose.\n  --name=<n>  Name."
    assert_that(format_argv(docopt(doc, "-v --name=x file", complete=False), doc)).is_equal_to(
        ["-v", "--name=x", "file"]
    )


def test_format_handles_a_single_line_usage():
    doc = "Usage: prog <host> <port>"
    assert_that(format_argv(docopt(doc, "h 80", complete=False), doc)).is_equal_to(["h", "80"])


def test_format_emits_a_repeated_positional_once_as_its_list():
    # two `<a>` leaves accumulate into one list, so the second is a duplicate the walk must not re-emit
    doc = "Usage: prog <a> <a>"
    assert_that(format_argv(docopt(doc, "x y", complete=False), doc)).is_equal_to(["x", "y"])


def test_format_interleaves_a_repeated_positional_with_the_one_between():
    # <name> repeats around <path>; each leaf must take the next element, not dump the list contiguously
    doc = "usage: prog <name> <path> <name>"
    assert_that(format_argv(docopt(doc, "v1 v2 v3", complete=False), doc)).is_equal_to(["v1", "v2", "v3"])


def test_format_interleaves_a_repeated_command():
    # a command is positional too (not floating), so its repeats must bracket the positional between them
    doc = "usage: prog cmd <name> cmd"
    assert_that(format_argv(docopt(doc, "cmd v1 cmd", complete=False), doc)).is_equal_to(["cmd", "v1", "cmd"])


def test_format_interleaves_a_grouped_repetition():
    doc = "usage: prog (<a> <b>)..."
    assert_that(format_argv(docopt(doc, "1 x 2 y", complete=False), doc)).is_equal_to(["1", "x", "2", "y"])


def test_format_picks_the_repeating_branch_of_an_alternation():
    # a multi-element value must be routed to the branch that repeats its name, not the scalar one
    doc = "usage: prog (<name> | <name> ...)"
    assert_that(_roundtrips(doc, "v1 v2")).is_true()


def test_format_raises_when_the_result_matches_no_pattern():
    inconsistent = Arguments({"--nope": True})
    inconsistent.provided = frozenset({"--nope"})
    assert_that(format_argv).raises(ValueError).when_called_with(inconsistent, _GIT)


_ROUNDTRIP_DOCS = [
    _GIT,
    "Usage: prog [-vvv] [--port=<n>] <host>\n\nOptions:\n  --port=<n>  Port [default: 80].",
    "Usage: prog [options] <f>\n\nOptions:\n  -v  Verbose.\n  --name=<n>  Name.",
    "Usage: prog (a|b|c) [--x=<v>]...\n\nOptions:\n  --x=<v>  X.",
    "Usage: prog mv <src>... <dst>",
    # a nested alternation the result may not take, so a candidate line's branch is unpickable and skipped
    "Usage:\n  prog (add|rm) <x>\n  prog list\n",
]


def _make_roundtrip_test(doc):
    @given(argv=argv_strategy(doc))
    @settings(max_examples=200, deadline=None, suppress_health_check=list(HealthCheck))
    def check(argv):
        # The core contract: whatever docopt accepts, format_argv turns the result back into an argv that
        # parses to the same result. This is the property only docopt2 can assert, via its own strategy.
        try:
            result = docopt(doc, argv, help=False, complete=False)
        except (DocoptExit, DocoptLanguageError):
            return
        assert docopt(doc, format_argv(result, doc), help=False, complete=False) == result

    return check


def test_format_round_trips_every_accepted_argv():
    for doc in _ROUNDTRIP_DOCS:
        _make_roundtrip_test(doc)()


def test_a_config_sourced_value_is_emitted_so_the_argv_stands_alone(monkeypatch):
    # format_argv used to emit only `result.provided` (argv-supplied), so an env- or config-resolved value
    # was dropped: the persisted command silently depended on an environment it did not record.
    monkeypatch.delenv("APP_PORT", raising=False)
    doc = "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [config: server.port]."
    result = docopt(doc, "", complete=False, config={"server": {"port": 8080}})
    argv = format_argv(result, doc)
    assert_that(argv).is_equal_to(["--port=8080"])
    assert_that(docopt(doc, argv, complete=False)).is_equal_to(result)  # reproduces WITHOUT the config


def test_an_env_sourced_value_is_emitted_so_the_argv_stands_alone(monkeypatch):
    doc = "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [default: 80] [env: APP_PORT]."
    monkeypatch.setenv("APP_PORT", "7000")
    result = docopt(doc, "", complete=False)
    argv = format_argv(result, doc)
    monkeypatch.delenv("APP_PORT")
    assert_that(argv).is_equal_to(["--port=7000"])
    assert_that(docopt(doc, argv, complete=False)).is_equal_to(result)  # reproduces WITHOUT the variable


def test_a_value_left_at_its_default_is_still_omitted(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    doc = "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [default: 80] [env: APP_PORT]."
    assert_that(format_argv(docopt(doc, "", complete=False), doc)).is_empty()


def test_an_env_flag_read_as_off_emits_no_token(monkeypatch):
    # A source other than DEFAULT is not enough to emit: an `[env: V]` flag read as OFF has source ENV and
    # value False, and emitting `--verbose` for it re-parses to True, so nothing round-trips and the whole
    # call raised. Only a value actually present is a token.
    doc = "Usage: prog [--verbose]\n\nOptions:\n  --verbose  Loud [env: PROG_V]."
    monkeypatch.setenv("PROG_V", "0")
    result = docopt(doc, "", complete=False)
    assert_that(dict(result)).is_equal_to({"--verbose": False})
    assert_that(format_argv(result, doc)).is_empty()


def test_an_env_flag_read_as_on_emits_its_token(monkeypatch):
    doc = "Usage: prog [--verbose]\n\nOptions:\n  --verbose  Loud [env: PROG_V]."
    monkeypatch.setenv("PROG_V", "1")
    result = docopt(doc, "", complete=False)
    argv = format_argv(result, doc)
    monkeypatch.delenv("PROG_V")
    assert_that(argv).is_equal_to(["--verbose"])
    assert_that(docopt(doc, argv, complete=False)).is_equal_to(result)


def _formats_to(result, doc):
    """The argv ``format_argv`` returns, or its refusal, so a test compares either one with what it expects."""
    try:
        return format_argv(result, doc)
    except ValueError as refusal:
        return refusal


def test_a_positional_that_starts_with_a_dash_goes_behind_a_double_dash():
    # written bare, `-x` re-parses as an option, so the result docopt produced had no argv at all
    doc = "Usage: prog [-v] <name>"
    result = docopt(doc, ["-v", "--", "-x"], complete=False)
    assert_that(dict(result)).is_equal_to({"-v": True, "<name>": "-x"})
    assert_that(_formats_to(result, doc)).is_equal_to(["-v", "--", "-x"])


def test_the_options_move_in_front_of_the_double_dash():
    # after `--` every token is a positional, so an option written after it would be read as a value
    doc = "Usage: prog <src> [--force] <dst>"
    result = docopt(doc, ["--force", "--", "-a", "-b"], complete=False)
    argv = _formats_to(result, doc)
    assert_that(argv).is_equal_to(["--force", "--", "-a", "-b"])
    assert_that(docopt(doc, argv, complete=False)).is_equal_to(result)


def test_a_double_dash_is_itself_a_value_behind_a_double_dash():
    doc = "Usage: prog <n>"
    result = docopt(doc, ["--", "--"], complete=False)
    assert_that(dict(result)).is_equal_to({"<n>": "--"})
    assert_that(_formats_to(result, doc)).is_equal_to(["--", "--"])


def test_dash_leading_values_of_a_repeated_positional_keep_their_order():
    doc = "Usage: prog <cmd> [<args>...]"
    result = docopt(doc, ["run", "--", "-x", "--help", "y"], help=False, complete=False)
    assert_that(_formats_to(result, doc)).is_equal_to(["--", "run", "-x", "--help", "y"])


def test_a_negative_number_read_as_a_positional_formats_without_the_flag_that_read_it():
    doc = "Usage: prog <n>"
    result = docopt(doc, ["-5"], negative_numbers=True, complete=False)
    argv = _formats_to(result, doc)
    assert_that(argv).is_equal_to(["--", "-5"])
    assert_that(docopt(doc, argv, complete=False)).is_equal_to(result)


def test_a_usage_that_declares_the_double_dash_writes_it_once():
    doc = "Usage: prog [--] <args>..."
    result = docopt(doc, ["--", "-x"], complete=False)
    assert_that(format_argv(result, doc)).is_equal_to(["--", "-x"])


def test_a_lone_dash_parses_bare_so_it_gets_no_double_dash():
    # both spellings parse back to the result here, and the one that formatted before the fallback must win
    doc = "Usage: prog <file>"
    result = docopt(doc, ["-"], complete=False)
    assert_that(docopt(doc, ["--", "-"], complete=False)).is_equal_to(result)
    assert_that(format_argv(result, doc)).is_equal_to(["-"])


def test_an_argv_without_a_dash_leading_positional_has_no_double_dash():
    assert_that(format_argv(docopt(_GIT, "push --force origin", complete=False), _GIT)).does_not_contain("--")


def test_a_short_option_whose_value_is_a_double_dash_is_written_attached():
    # as its own token, `--` after `-s` ends the options and `-s` is left without its argument
    doc = "Usage: prog -s <v>\n\nOptions:\n  -s <v>  S."
    result = docopt(doc, ["-s=--"], complete=False)
    assert_that(dict(result)).is_equal_to({"-s": "--"})
    argv = _formats_to(result, doc)
    assert_that(argv).is_equal_to(["-s=--"])
    assert_that(docopt(doc, argv, complete=False)).is_equal_to(result)


def test_a_short_option_with_any_other_value_keeps_its_two_tokens():
    doc = "Usage: prog -s <v>\n\nOptions:\n  -s <v>  S."
    assert_that(format_argv(docopt(doc, ["-s", "-x"], complete=False), doc)).is_equal_to(["-s", "-x"])


def test_a_result_only_options_first_could_produce_formats_behind_a_double_dash():
    doc = "Usage: prog [-v] <cmd> [<args>...]"
    result = docopt(doc, ["run", "-v"], options_first=True, complete=False)
    assert_that(dict(result)).is_equal_to({"-v": False, "<cmd>": "run", "<args>": ["-v"]})
    argv = _formats_to(result, doc)
    assert_that(argv).is_equal_to(["--", "run", "-v"])
    assert_that(docopt(doc, argv, complete=False)).is_equal_to(result)


def test_a_negative_number_in_front_of_a_declared_double_dash_cannot_be_formatted():
    # the usage's own `--` is a boundary, so a second one in front of `-5` would itself be read as <n>
    doc = "Usage: prog <n> -- <tail>"
    result = docopt(doc, ["-5", "--", "x"], negative_numbers=True, complete=False)
    assert_that(dict(result)).is_equal_to({"<n>": "-5", "--": True, "<tail>": "x"})
    assert_that(format_argv).raises(ValueError).when_called_with(result, doc)


def test_a_result_that_carries_help_formats_and_parses_back_only_where_help_is_not_acted_on():
    doc = "Usage: prog [--help] [<x>]"
    result = docopt(doc, ["--help"], help=False, complete=False)
    argv = _formats_to(result, doc)
    assert_that(argv).is_equal_to(["--help"])
    assert_that(docopt(doc, argv, help=False, complete=False)).is_equal_to(result)
    assert_that(docopt).raises(SystemExit).when_called_with(doc, argv, complete=False)  # help=True prints and exits


def test_a_result_options_first_produced_parses_back_under_the_defaults_and_not_under_options_first():
    doc = "Usage: prog <src> [--force] <dst>"
    result = docopt(doc, ["--force", "a", "b"], options_first=True, complete=False)
    argv = _formats_to(result, doc)
    assert_that(argv).is_equal_to(["a", "--force", "b"])
    assert_that(docopt(doc, argv, help=False, complete=False)).is_equal_to(result)
    # under the setting that produced it, `--force` after `a` is a third positional
    assert_that(docopt).raises(DocoptExit).when_called_with(doc, argv, options_first=True, complete=False)


def test_a_zero_count_has_no_token_so_it_is_read_from_its_source_again(monkeypatch):
    doc = "Usage: prog [-v...]\n\nOptions:\n  -v  Verbose [env: V]."
    monkeypatch.setenv("V", "0")
    result = docopt(doc, "", complete=False)
    argv = _formats_to(result, doc)
    assert_that(argv).is_empty()
    monkeypatch.setenv("V", "3")
    assert_that(dict(docopt(doc, argv, complete=False))).is_equal_to({"-v": 3})


def test_a_default_is_written_out_when_the_environment_changed_since_the_parse(monkeypatch):
    # left out, `--port` would now resolve from the variable, and the argv that does parse back was never tried
    doc = "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [default: 80] [env: APP_PORT]."
    monkeypatch.delenv("APP_PORT", raising=False)
    result = docopt(doc, "", complete=False)
    assert_that(_formats_to(result, doc)).is_empty()
    monkeypatch.setenv("APP_PORT", "81")
    argv = _formats_to(result, doc)
    assert_that(argv).is_equal_to(["--port=80"])
    assert_that(docopt(doc, argv, complete=False)).is_equal_to(result)


def test_a_mapping_built_by_hand_formats_when_it_is_one_the_usage_can_produce():
    # it records no sources, so every element reads as left at its default and nothing would be written
    by_hand = Arguments({"push": True, "commit": False, "add": False, "--force": True, "<remote>": "origin"})
    by_hand.update({"--message": None, "<path>": []})
    argv = _formats_to(by_hand, _GIT)
    assert_that(argv).is_equal_to(["push", "--force", "origin"])
    assert_that(docopt(_GIT, argv, complete=False)).is_equal_to(by_hand)


_A_VALUE = st.sampled_from(["-x", "--", "--help", "-5", "-", "", "a", "add", "rm", "copy", "list", "--port=9", "-v"])
_HOST = "Usage: prog [-v] [--port=<n>] <host> [<rest>...]\n\nOptions:\n  --port=<n>  Port [default: 80]."
_COMMAND = "Usage: prog (add|rm) <x> [--force]"
_TWO_LINES = "Usage:\n  prog copy <src>... <dst>\n  prog [--all] list [<pattern>]\n"


@st.composite
def _accepted_behind_a_separator(draw: st.DrawFn) -> tuple[str, list[str]]:
    """A usage and an argv it accepts whatever the values are: behind ``--`` every token is a positional."""
    values = draw(st.lists(_A_VALUE, max_size=3))
    shape = draw(st.sampled_from(["host", "command", "copy", "list"]))
    if shape == "host":
        options = draw(st.lists(st.sampled_from(["-v", "--port=1"]), unique=True))
        return _HOST, [*options, "--", draw(_A_VALUE), *values]
    if shape == "command":
        options = draw(st.lists(st.just("--force"), max_size=1))
        return _COMMAND, [*options, "--", draw(st.sampled_from(["add", "rm"])), draw(_A_VALUE)]
    if shape == "copy":
        return _TWO_LINES, ["--", "copy", draw(_A_VALUE), draw(_A_VALUE), *values]
    options = draw(st.lists(st.just("--all"), max_size=1))
    return _TWO_LINES, [*options, "--", "list", *values[:1]]


@given(case=_accepted_behind_a_separator())
@settings(deadline=None, suppress_health_check=list(HealthCheck))
@example(case=(_COMMAND, ["--force", "--", "add", "--force"]))
@example(case=(_TWO_LINES, ["--", "copy", "-a", "--", "-b"]))
def test_whatever_stands_behind_a_double_dash_formats_back(case):
    # no refusal is waved through: the strategy builds only what the usage accepts, so a refusal fails the test
    doc, argv = case
    result = docopt(doc, argv, help=False, complete=False)
    formatted = _formats_to(result, doc)
    assert isinstance(formatted, list), formatted
    assert docopt(doc, formatted, help=False, complete=False) == result
