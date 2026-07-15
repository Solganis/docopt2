import dataclasses

from assertpy2 import assert_that

from docopt2 import docopt
from docopt2._parser import parse_defaults

_DOC = (
    "Usage: prog [--port=<n>] [--verbose]\n\n"
    "Options:\n  --port=<n>  Port [default: 80] [env: APP_PORT].\n  --verbose  Loud [env: APP_VERBOSE]."
)


def test_cli_argument_wins_over_env(monkeypatch):
    monkeypatch.setenv("APP_PORT", "8080")
    assert_that(docopt(_DOC, "--port=99", complete=False)["--port"]).is_equal_to("99")


def test_env_fills_an_option_absent_from_argv(monkeypatch):
    monkeypatch.setenv("APP_PORT", "8080")
    monkeypatch.delenv("APP_VERBOSE", raising=False)
    assert_that(docopt(_DOC, "", complete=False)["--port"]).is_equal_to("8080")


def test_default_applies_when_env_is_unset(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    assert_that(docopt(_DOC, "", complete=False)["--port"]).is_equal_to("80")


def test_flag_reads_env_truthy_and_falsy(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    monkeypatch.setenv("APP_VERBOSE", "1")
    assert_that(docopt(_DOC, "", complete=False)["--verbose"]).is_true()
    monkeypatch.setenv("APP_VERBOSE", "0")
    assert_that(docopt(_DOC, "", complete=False)["--verbose"]).is_false()
    monkeypatch.setenv("APP_VERBOSE", "false")
    assert_that(docopt(_DOC, "", complete=False)["--verbose"]).is_false()


def test_cli_flag_wins_over_a_falsy_env(monkeypatch):
    monkeypatch.setenv("APP_VERBOSE", "0")
    assert_that(docopt(_DOC, "--verbose", complete=False)["--verbose"]).is_true()


def test_a_counted_flag_from_env_keeps_its_int_count_type(monkeypatch):
    # A repeating flag holds an int count everywhere else (`-vv` -> 2). An [env:] value used to collapse
    # it to a bool (`True`), so a `verbosity: int` schema would silently read 1. A number is the count.
    doc = "Usage: prog [-v...]\n\nOptions:\n  -v  Verbosity [env: V]."
    monkeypatch.setenv("V", "3")
    result = docopt(doc, [], complete=False)
    assert_that(result["-v"]).is_equal_to(3)
    assert_that(type(result["-v"])).is_equal_to(int)
    monkeypatch.setenv("V", "on")  # a non-numeric truthy value counts once
    assert_that(docopt(doc, [], complete=False)["-v"]).is_equal_to(1)
    monkeypatch.setenv("V", "0")  # a falsy value is zero, not False
    zero = docopt(doc, [], complete=False)["-v"]
    assert_that(zero).is_equal_to(0)
    assert_that(type(zero)).is_equal_to(int)


def test_env_value_coerces_through_the_schema(monkeypatch):
    monkeypatch.setenv("APP_PORT", "8080")
    monkeypatch.delenv("APP_VERBOSE", raising=False)

    @dataclasses.dataclass
    class Args:
        port: int
        verbose: bool

    args = docopt(_DOC, "", complete=False, schema=Args)
    assert_that(args.port).is_equal_to(8080)
    assert_that(type(args.port)).is_equal_to(int)


def test_env_annotation_does_not_break_default_extraction():
    option = next(o for o in parse_defaults(_DOC) if o.long == "--port")
    assert_that(option.value).is_equal_to("80")  # greedy [default: (.*)] must not swallow [env: ...]
    assert_that(option.env).is_equal_to("APP_PORT")


def test_env_on_an_option_absent_from_usage_is_ignored(monkeypatch):
    monkeypatch.setenv("GHOST", "x")
    doc = "Usage: prog [--a]\n\nOptions:\n  --a  A.\n  --ghost  Ghost [env: GHOST]."
    assert_that("--ghost" in docopt(doc, "", complete=False)).is_false()


def test_env_fallback_wraps_a_repeating_option_in_a_list(monkeypatch):
    # A repeating option holds a list everywhere (given -> [...], absent -> []); an env fallback must
    # keep that type, not assign a bare string, or the key's type is inconsistent across sources.
    monkeypatch.setenv("APP_TAGS", "ab")
    doc = "Usage: prog [--tag=<t>]...\n\nOptions:\n  --tag=<t>  a tag [env: APP_TAGS]."
    assert_that(docopt(doc, "", complete=False)["--tag"]).is_equal_to(["ab"])
