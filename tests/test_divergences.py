from assertpy2 import assert_that
from pytest import raises

from docopt2 import DocoptExit, docopt

NEG_DOC = "usage: prog --negative_pi=NEGPI NEGTAU"


def test_negative_number_as_positional_with_flag():
    # Extended negative-float behavior, gated behind the opt-in.
    result = docopt(NEG_DOC, "--negative_pi -3.14 -6.28", negative_numbers=True)
    assert_that(result).is_equal_to({"--negative_pi": "-3.14", "NEGTAU": "-6.28"})


def test_negative_number_is_a_short_cluster_by_default():
    # Default is vanilla docopt: -6.28 is a short-option cluster, so this is a user error.
    with raises(DocoptExit):
        docopt(NEG_DOC, "--negative_pi -3.14 -6.28")


def test_flag_still_parses_genuine_short_options():
    result = docopt("usage: prog [-v] <n>", "-v -3", negative_numbers=True)
    assert_that(result["-v"]).is_true()
    assert_that(result["<n>"]).is_equal_to("-3")


def test_negative_numbers_with_options_first():
    result = docopt("usage: prog [--verbose] <nums>...", "--verbose -3 -6", options_first=True, negative_numbers=True)
    assert_that(result).is_equal_to({"--verbose": True, "<nums>": ["-3", "-6"]})


REPEATED_OPTION_DOC = """Usage:
    prog [--to=SITE]... [--] FILE...
    prog [--to=SITE]... --config CONFIG [[--] FILE...]

Options:
    --config CONFIG     Configuration file.
    --to=SITE           Target site
"""


def test_repeated_option_across_alternatives_is_not_duplicated():
    # vanilla docopt leaks a repeated option's accumulated values across usage alternatives,
    # yielding ['a', 'b', 'b']; docopt2 deliberately fixes this.
    result = docopt(REPEATED_OPTION_DOC, "--to a --to b c")
    assert_that(result).is_equal_to({"--": False, "--config": None, "--to": ["a", "b"], "FILE": ["c"]})


def test_repeated_option_arg_not_doubled_with_optional_present():
    # A repeated option-argument across two usage lines with an optional flag: vanilla doubled
    # every value after the first (['1', '2', '2'...]); docopt2 keeps them once each.
    doc = """Usage:
  prog [-a] [-x <v>]...
  prog [-b] [-x <v>]...
"""
    assert_that(docopt(doc, "-x 1 -x 2", help=False)["<v>"]).is_equal_to(["1", "2"])


def test_repeated_long_option_not_duplicated_across_subcommands():
    # A repeated long option across two subcommand lines: vanilla duplicated the last value.
    doc = """Usage:
  prog update [--table=<t>]...
  prog update schema [--table=<t>]...
"""
    assert_that(docopt(doc, "update schema --table=1 --table=2", help=False)["--table"]).is_equal_to(["1", "2"])


def test_repeated_flag_with_options_shortcut_has_no_phantom_key():
    # Combining a repeatable flag with `[options]` used to inject a phantom '-vvv' key.
    doc = """Usage:
    program [-v | -vv | -vvv]
    program sub [-v | -vv | -vvv] [options]

Options:
    -e, --extra  An extra option.
"""
    assert_that(docopt(doc, "sub -vvv", help=False)).is_equal_to({"sub": True, "-v": 3, "--extra": False})


def test_short_option_accepts_equals_separator():
    # vanilla docopt keeps the '=' in the value for `-s=25` (yielding '=25'); docopt2 treats a
    # single leading '=' as the separator, matching the long-option `--speed=25` form.
    doc = """Usage:
  prog [options] <name>

Options:
  -s=<kn>, --speed=<kn>  Speed.
"""
    assert_that(docopt(doc, "-s=25 x", help=False)["--speed"]).is_equal_to("25")


def test_double_dash_separator_not_leaked_when_absent_from_docstring():
    # POSIX: `--` ends option parsing. vanilla docopt leaks the separator into the positional
    # list when the usage pattern lacks a `--`; docopt2 drops it.
    assert_that(docopt("Usage: prog [-v] <args>...", "-v -- -x", help=False)).is_equal_to(
        {"-v": True, "<args>": ["-x"]}
    )


def test_double_dash_still_reported_when_declared():
    # When the usage declares `[--]`, the separator is kept and reported as passed.
    assert_that(docopt("Usage: prog [-v] [--] <args>...", "-v -- -x", help=False)).is_equal_to(
        {"-v": True, "--": True, "<args>": ["-x"]}
    )


def test_only_the_first_double_dash_is_a_separator():
    # A second `--` after the separator is an ordinary positional value.
    assert_that(docopt("Usage: prog <args>...", "-- -- x", help=False)["<args>"]).is_equal_to(["--", "x"])


def test_dropping_an_undeclared_double_dash_shifts_the_positionals_along():
    # The same root as the test above, in a face the docs' one-value example does not show: the original
    # gives the first positional the separator itself and pushes the rest along, so every positional after
    # it ends up holding the token its neighbour holds here.
    assert_that(docopt("Usage: prog -a | <name> <path>...", "-- x y", help=False)).is_equal_to(
        {"-a": False, "<name>": "x", "<path>": ["y"]}
    )


def test_dropping_an_undeclared_double_dash_can_reject_what_the_original_accepted():
    # And its least obvious face, the only divergence that turns a working invocation into an error: where
    # `--` WAS the token filling a required slot, dropping it leaves the pattern unfilled. The original reads
    # the separator as an ordinary positional and accepts (`{'<a>': ['--']}`); docopt2 reads POSIX and exits.
    with raises(DocoptExit):
        docopt("Usage: prog <a>...", "--", help=False)


def test_repeating_positional_before_required_backtracks():
    # A greedy `<src>...` would swallow every token and starve `<dest>`; the matcher backs the
    # repetition off to fill the trailing required element. Vanilla rejects this argv outright.
    assert_that(docopt("usage: prog <src>... <dest>", "a b c", help=False)).is_equal_to(
        {"<src>": ["a", "b"], "<dest>": "c"}
    )


def test_optional_positional_before_required_backtracks():
    # The common `[<a>] <b>` shape: vanilla cannot match `prog x`; docopt2 skips <a> to fill <b>.
    assert_that(docopt("usage: prog [<a>] <b>", "x", help=False)).is_equal_to({"<a>": None, "<b>": "x"})


def test_repeating_option_argument_before_required_backtracks():
    # A repeating option argument followed by a required positional (`[-i X...] <out>`).
    assert_that(docopt("usage: prog [-i X...] <out>", "-i 1 2 out", help=False)).is_equal_to(
        {"-i": True, "X": ["1", "2"], "<out>": "out"}
    )


def test_either_repeat_does_not_duplicate_values():
    # An Either of the same element under `...` made vanilla over-count; the matcher does not.
    assert_that(docopt("usage: prog [<name> | <name>]...", "a b", help=False)["<name>"]).is_equal_to(["a", "b"])


def test_either_command_and_argument_do_not_double_count_a_token():
    # `[cmd | <name>]...`: vanilla counts a `cmd` token as BOTH the command and a <name> value;
    # docopt2 assigns each token to a single leaf, so `cmd` is the command and only `-a` is <name>.
    result = docopt("usage: prog [cmd | <name>] ...", "-- -a cmd", help=False)
    assert_that(result).is_equal_to({"cmd": 1, "<name>": ["-a"]})


_ABBREV_DOC = "usage: prog [--version]\n\noptions: --version  show version\n"


def test_long_option_de_abbreviates_by_default():
    # Default (vanilla) behaviour: an unambiguous prefix resolves to the full option.
    assert_that(docopt(_ABBREV_DOC, "--ver", help=False)).is_equal_to({"--version": True})


def test_allow_abbrev_false_requires_the_full_option_name():
    assert_that(docopt).raises(DocoptExit).when_called_with(_ABBREV_DOC, "--ver", help=False, allow_abbrev=False)
    # the full name still parses
    assert_that(docopt(_ABBREV_DOC, "--version", help=False, allow_abbrev=False)).is_equal_to({"--version": True})


def test_allow_abbrev_false_suggests_the_intended_option():
    with raises(DocoptExit) as exc_info:
        docopt(_ABBREV_DOC, "--ver", help=False, allow_abbrev=False, suggest=True)
    assert_that(str(exc_info.value)).contains("did you mean `--version`")


def test_allow_abbrev_false_still_suggests_a_typo():
    # A genuine typo (not a prefix) is still spellcheck-suggested when abbreviations are off.
    with raises(DocoptExit) as exc_info:
        docopt(_ABBREV_DOC, "--vesion", help=False, allow_abbrev=False, suggest=True)
    assert_that(str(exc_info.value)).contains("did you mean `--version`")
