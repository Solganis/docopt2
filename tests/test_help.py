from assertpy2 import assert_that
from pytest import raises

from docopt2 import Cli, docopt
from docopt2._help import render_help

_DOC = """Naval Fate.

Usage:
  naval ship new <name>...
  naval ship <name> move <x> <y> [--speed=<kn>]
  naval mine (set | remove) <x> <y>
  naval [options] status
  naval --help

Options:
  --speed=<kn>  Speed in knots [default: 10].
  --moored      Moored (anchored) mine.
"""


def test_no_path_renders_intro_all_usage_and_all_options():
    out = render_help(_DOC)
    assert_that(out).starts_with("Naval Fate.")  # intro kept
    assert_that(out).contains("Usage:").contains("ship new").contains("mine (set | remove)")
    assert_that(out).contains("--speed=<kn>").contains("Speed in knots").contains("[default: 10]")


def test_scopes_usage_and_options_to_the_command_path():
    out = render_help(_DOC, ("ship", "move"))
    assert_that(out).contains("ship <name> move")
    assert_that(out).does_not_contain("ship new").does_not_contain("mine")  # only the matched line
    assert_that(out).contains("--speed=<kn>")  # the option that line uses
    assert_that(out).does_not_contain("--moored")  # not used by the move line


def test_a_scoped_line_with_no_options_omits_the_options_block():
    out = render_help(_DOC, ("ship", "new"))
    assert_that(out).contains("ship new")
    assert_that(out).does_not_contain("Options:")


def test_options_shortcut_shows_every_option():
    out = render_help(_DOC, ("status",))
    assert_that(out).contains("[options] status")
    assert_that(out).contains("--speed=<kn>").contains("--moored")  # [options] expands to all


def test_a_path_matching_no_single_line_falls_back_to_the_whole_usage():
    # `ship` and `mine` are both literals but never share a line, so nothing matches -> show everything.
    out = render_help(_DOC, ("ship", "mine"))
    assert_that(out).contains("ship new").contains("mine (set | remove)")


def test_color_wraps_headers_in_ansi():
    plain = render_help(_DOC, ("ship", "move"))
    colored = render_help(_DOC, ("ship", "move"), color=True)
    assert_that("\x1b[" in plain).is_false()
    assert_that("\x1b[" in colored).is_true()


_PROV_DOC = (
    "Serve.\n\nUsage:\n  serve [--port=<n>] [--verbose]\n\nOptions:\n"
    "  --port=<n>  Port to bind [default: 8080] [env: PORT] [config: server.port].\n"
    "  --verbose   Log requests [env: DEBUG]."
)


def test_provenance_shows_the_resolution_chain():
    out = render_help(_PROV_DOC)
    assert_that(out).contains("[env: PORT, config: server.port, default: 8080]")  # chain in precedence order
    assert_that(out).contains("Port to bind.")  # description cleaned, trailing period tidied
    assert_that(out).does_not_contain("Port to bind [default")  # the annotations are no longer inline
    assert_that(out).contains("[env: DEBUG]")  # an env-only chain


def test_an_option_without_sources_has_no_provenance():
    out = render_help("Usage: prog [--x]\n\nOptions:\n  --x  Plain option.")
    assert_that(out).contains("Plain option.")
    assert_that(out).does_not_contain("[env:").does_not_contain("[config:").does_not_contain("[default:")


def test_a_usage_first_doc_has_no_intro():
    out = render_help("Usage: prog <x>\n\nOptions:\n  -v  V.")
    assert_that(out).starts_with("Usage:")


def test_render_help_does_not_crash_without_a_usage_section():
    # Defensive: only reachable by calling render_help directly on a malformed doc, never via docopt.
    assert_that(render_help("Options:\n  -v  V.")).contains("Usage:")


def test_rich_help_style_prints_scoped_help_and_exits(capsys):
    with raises(SystemExit):
        docopt(_DOC, "ship v move 1 2 --help", help_style="rich")
    out = capsys.readouterr().out
    assert_that(out).contains("ship <name> move").does_not_contain("ship new")


def test_raw_help_style_is_the_default_verbatim_dump(capsys):
    with raises(SystemExit):
        docopt(_DOC, "ship v move 1 2 --help")
    out = capsys.readouterr().out
    assert_that(out).contains("ship new").contains("mine (set | remove)")  # whole doc, unscoped


def test_an_unknown_help_style_raises_value_error():
    assert_that(docopt).raises(ValueError).when_called_with(_DOC, "--help", help_style="fancy")


def test_cli_parse_forwards_help_style(capsys):
    class Fate(Cli):
        __cli_doc__ = _DOC

    with raises(SystemExit):
        Fate.parse("ship v move 1 2 --help", help_style="rich")
    assert_that(capsys.readouterr().out).contains("ship <name> move").does_not_contain("ship new")
