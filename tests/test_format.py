from assertpy2 import assert_that
from hypothesis import HealthCheck, given, settings

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
