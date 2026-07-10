from assertpy2 import assert_that
from pytest import raises

from docopt2 import DocoptExit, Option, docopt
from docopt2._spellcheck import _closest, _levenshtein, suggest_option

DOC = """Usage: prog [--verbose] [--version] <file>

Options:
  --verbose  Be verbose.
  --version  Show version.
"""


def test_suggest_hints_close_option():
    with raises(DocoptExit) as exc_info:
        docopt(DOC, ["--verbso", "x"], suggest=True)
    message = str(exc_info.value)
    assert_that(message).contains("did you mean `--verbose`")
    # the mistyped option is underlined with a caret in the reproduced argv
    assert_that(message).contains("--verbso x").contains("^")


def test_suggest_hints_on_option_with_inline_value():
    # A typo carrying an inline "=value" must be split on "=" so the bare option name is
    # what gets matched; the reported name is the option, not the whole "name=value" token.
    with raises(DocoptExit) as exc_info:
        docopt(DOC, ["--verbso=1", "x"], suggest=True)
    assert_that(str(exc_info.value)).contains("unknown option `--verbso`")
    assert_that(str(exc_info.value)).contains("did you mean `--verbose`")


def test_suggest_hints_when_the_option_is_only_in_the_options_section():
    # The suggested option is declared in `options:` but not written in the usage pattern, so there
    # is no usage span to cross-reference; the hint degrades to the argv caret plus the "did you mean".
    doc = "Usage: prog <file>\n\nOptions:\n  --verbose  Be verbose.\n"
    with raises(DocoptExit) as exc_info:
        docopt(doc, ["--verbse", "x"], suggest=True)
    message = str(exc_info.value)
    assert_that(message).contains("did you mean `--verbose`").contains("--verbse")


def test_suggest_off_by_default_gives_no_hint():
    with raises(DocoptExit) as exc_info:
        docopt(DOC, "--verbso x")
    assert_that(str(exc_info.value)).does_not_contain("did you mean")


def test_suggest_gives_no_hint_when_nothing_is_close():
    with raises(DocoptExit) as exc_info:
        docopt(DOC, "--zzzzzz x", suggest=True)
    assert_that(str(exc_info.value)).does_not_contain("did you mean")


def test_valid_prefix_still_de_abbreviates():
    assert_that(docopt(DOC, "--verb x")["--verbose"]).is_true()


def test_levenshtein_distance():
    # Pin every transition of the Wagner-Fischer matrix: the empty-string base row and
    # column, a single insertion, a single deletion, a single substitution, and a
    # multi-edit classic. Thin coverage here lets matrix mutations survive silently.
    cases = [
        ("kitten", "sitting", 3),
        ("abc", "abc", 0),
        ("", "", 0),
        ("", "a", 1),
        ("a", "", 1),
        ("", "abc", 3),
        ("abc", "", 3),
        ("ab", "abc", 1),  # insertion
        ("abc", "ab", 1),  # deletion
        ("ab", "a", 1),  # deletion (exercises the deletion transition on its own)
        ("abc", "abd", 1),  # substitution
        ("flaw", "lawn", 2),
    ]
    for source, target, expected in cases:
        assert_that(_levenshtein(source, target)).described_as(f"{source!r} -> {target!r}").is_equal_to(expected)


def test_closest_returns_none_when_no_candidates():
    assert_that(_closest("--foo", [])).is_none()


def test_closest_returns_none_when_nothing_within_threshold():
    assert_that(_closest("--foobar", ["--zzzzzz"])).is_none()


def test_closest_returns_match_within_threshold():
    assert_that(_closest("--verbso", ["--verbose", "--version"])).is_equal_to("--verbose")


def test_suggest_option_skips_positionals_double_dash_and_valid_prefixes():
    # -x has no long form, so it is filtered out of the known set.
    options = [Option(None, "--verbose"), Option("-x", None)]
    tokens = ["file", "--", "--verb", "--verbso"]
    assert_that(suggest_option(tokens, options)).is_equal_to(("--verbso", "--verbose"))


def test_suggest_option_returns_none_when_all_known_or_prefix():
    options = [Option(None, "--verbose")]
    assert_that(suggest_option(["--verbose", "--verb"], options)).is_none()


def test_suggest_option_returns_none_without_a_close_match():
    options = [Option(None, "--verbose")]
    assert_that(suggest_option(["--zzzzzz"], options)).is_none()
