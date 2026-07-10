import dataclasses

from assertpy2 import assert_that
from pytest import raises

from docopt2 import Arguments, DocoptExit, docopt
from docopt2._parser import parse_argument_defaults

# --- configurable exit code ---------------------------------------------------------------------


def test_default_exit_code_keeps_the_message_as_the_systemexit_code():
    # The default passes the text as the SystemExit code, so an uncaught error auto-prints it and
    # exits with status 1 - byte-for-byte the historical behavior.
    with raises(DocoptExit) as exc_info:
        docopt("usage: prog <a>", "")
    assert_that(exc_info.value.code).is_instance_of(str)
    assert_that(exc_info.value.exit_code).is_equal_to(1)
    assert_that(str(exc_info.value)).contains("usage")


def test_custom_exit_code_becomes_the_process_status():
    # A custom code becomes the SystemExit code (the real process status); the message still rides
    # on the exception for a caller that catches and prints it.
    with raises(DocoptExit) as exc_info:
        docopt("usage: prog <a>", "", exit_code=2)
    assert_that(exc_info.value.code).is_equal_to(2)
    assert_that(str(exc_info.value)).contains("usage requires").contains("<a>")


# --- value provenance: provided / was_given -----------------------------------------------------


def test_provided_distinguishes_given_from_defaulted():
    doc = "usage: prog [--count=<n>] <file>\n\nOptions:\n  --count=<n>  [default: 10].\n"
    args = docopt(doc, "data.txt")
    assert_that(dict(args)).is_equal_to({"--count": "10", "<file>": "data.txt"})
    assert_that(args.provided).contains("<file>").does_not_contain("--count")
    assert_that(args.was_given("<file>")).is_true()
    assert_that(args.was_given("--count")).is_false()


def test_was_given_is_true_for_an_explicitly_passed_option():
    doc = "usage: prog [--count=<n>] <file>\n\nOptions:\n  --count=<n>  [default: 10].\n"
    args = docopt(doc, "--count=5 data.txt")
    assert_that(args.was_given("--count")).is_true()
    assert_that(args["--count"]).is_equal_to("5")


def test_bare_arguments_have_empty_provenance_defaults():
    empty = Arguments()
    assert_that(empty.provided).is_equal_to(frozenset())
    assert_that(empty.extra).is_equal_to([])
    assert_that(empty.was_given("--anything")).is_false()


# --- allow_extra: tolerate surplus tokens (the parse_known_args idiom) ---------------------------


def test_allow_extra_returns_surplus_positionals_instead_of_failing():
    args = docopt("usage: prog <a>", "x y z", allow_extra=True)
    assert_that(args["<a>"]).is_equal_to("x")
    assert_that(args.extra).is_equal_to(["y", "z"])


def test_allow_extra_returns_unknown_options_and_positionals():
    # An unknown option and a stray positional both survive as raw tokens (option by name).
    args = docopt("usage: prog [-v]\n\nOptions:\n  -v  Verbose.\n", "-v --unknown pos", allow_extra=True)
    assert_that(args["-v"]).is_true()
    assert_that(args.extra).is_equal_to(["--unknown", "pos"])


def test_allow_extra_with_a_complete_match_leaves_extra_empty():
    args = docopt("usage: prog <a>", "x", allow_extra=True)
    assert_that(args["<a>"]).is_equal_to("x")
    assert_that(args.extra).is_equal_to([])


def test_allow_extra_still_fails_on_a_missing_required_element():
    # allow_extra tolerates surplus, not gaps: a required element that is absent still fails.
    with raises(DocoptExit):
        docopt("usage: prog <a>", "", allow_extra=True)


def test_allow_extra_composes_with_a_schema():
    @dataclasses.dataclass
    class Only:
        a: str

    result = docopt("usage: prog <a>", "x y", allow_extra=True, schema=Only)
    assert_that(result.a).is_equal_to("x")


# --- positional-argument defaults ----------------------------------------------------------------

_ARG_DEFAULT_DOC = (
    "usage: prog [<host>] [<port>]\n\n"
    "Arguments:\n"
    "  <host>  Host [default: localhost].\n"
    "  <port>  Port [default: 8080].\n"
)


def test_positional_default_fills_an_unmatched_argument():
    assert_that(dict(docopt(_ARG_DEFAULT_DOC, ""))).is_equal_to({"<host>": "localhost", "<port>": "8080"})


def test_a_given_positional_wins_over_its_default():
    assert_that(dict(docopt(_ARG_DEFAULT_DOC, "example.com"))).is_equal_to({"<host>": "example.com", "<port>": "8080"})


def test_a_defaulted_positional_is_not_reported_as_provided():
    args = docopt(_ARG_DEFAULT_DOC, "example.com")
    assert_that(args.was_given("<host>")).is_true()
    assert_that(args.was_given("<port>")).is_false()


def test_positional_default_declared_for_an_absent_argument_is_ignored():
    # A default for an argument the usage never mentions must not inject a spurious key.
    doc = "usage: prog <a>\n\nArguments:\n  <b>  Unused [default: x].\n"
    result = dict(docopt(doc, "value"))
    assert_that(result).is_equal_to({"<a>": "value"})
    assert_that(result).does_not_contain_key("<b>")


def test_positional_default_feeds_schema_coercion():
    @dataclasses.dataclass
    class Cfg:
        host: str
        port: int

    cfg = docopt(_ARG_DEFAULT_DOC, "", schema=Cfg)
    assert_that(cfg.host).is_equal_to("localhost")
    assert_that(cfg.port).is_equal_to(8080)


def test_parse_argument_defaults_reads_angle_and_upper_names_and_skips_the_rest():
    # <angle> and UPPER names with a [default:] are collected; a prose line and an arg line without
    # a default are both skipped, and the leading blank line from the section body is ignored.
    doc = (
        "usage: prog\n\n"
        "Arguments:\n"
        "  <host>  Host [default: localhost].\n"
        "  <port>  Port with no default here.\n"
        "  NAME    A name [default: anon].\n"
        "  a prose continuation line without a leading argument token\n"
    )
    assert_that(parse_argument_defaults(doc)).is_equal_to({"<host>": "localhost", "NAME": "anon"})


def test_parse_argument_defaults_absent_section_returns_empty():
    assert_that(parse_argument_defaults("usage: prog <a>")).is_equal_to({})
