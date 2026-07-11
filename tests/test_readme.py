import dataclasses
import re
from pathlib import Path

from assertpy2 import assert_that
from pytest import raises

from docopt2 import DocoptExit, check, complete, docopt, generate_examples, generate_stub
from docopt2._help import render_help

README = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")


def _python_blocks() -> list[str]:
    return re.findall(r"```python\n(.*?)```", README, re.DOTALL)


def _block_containing(needle: str) -> str:
    blocks = [block for block in _python_blocks() if needle in block]
    assert_that(blocks).described_as(f"README python block containing {needle!r}").is_not_empty()
    return blocks[0]


def _naval_doc() -> str:
    # The Quick start block embeds the usage message as a module docstring.
    match = re.search(r'"""(.*?)"""', _block_containing("Naval Fate."), re.DOTALL)
    assert match is not None
    return match.group(1)


def test_every_readme_python_block_is_valid_python():
    # A syntax typo in an example (a stray bracket, a bad indent) fails here before it ships.
    for block in _python_blocks():
        compile(block, "<readme>", "exec")


def test_stub_output_block_matches_generate_stub():
    # The README trims the leading `import dataclasses` for compactness, so the shown block is the
    # tail of the real output; the schema body (fields and types) must still match the tool exactly.
    shown = _block_containing("ship: bool").strip()
    assert_that(generate_stub(_naval_doc()).strip()).ends_with(shown)


def test_quick_start_result_shape_matches_the_tool():
    # The Quick start comment claims {"ship": True, "<name>": ["titanic"], "move": True, "--speed": "10", ...}.
    result = docopt(_naval_doc(), "ship titanic move 1 2", complete=False)
    assert_that(result["ship"]).is_true()
    assert_that(result["<name>"]).is_equal_to(["titanic"])
    assert_that(result["move"]).is_true()
    assert_that(result["--speed"]).is_equal_to("10")


def test_examples_demo_block_matches_the_tool():
    # The Example generation section shows `docopt2 examples ... --seed=5`; pin its lines to the tool.
    expected = [["--help"], ["ship", "v1", "move", "v2", "v3"], ["ship", "new", "v4", "v5"], ["ship", "new", "v6"]]
    assert_that(generate_examples(_naval_doc(), count=4, seed=5)).is_equal_to(expected)


def test_env_fallback_readme_example_matches_the_tool(monkeypatch):
    # The Environment-variable fallback section shows [env: APP_PORT] with CLI > env > default.
    doc = "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [default: 80] [env: APP_PORT]."
    monkeypatch.setenv("APP_PORT", "8080")
    assert_that(docopt(doc, "", complete=False)["--port"]).is_equal_to("8080")  # env fills it
    assert_that(docopt(doc, "--port=9000", complete=False)["--port"]).is_equal_to("9000")  # argument wins
    assert_that(README).contains("[env: APP_PORT]")


def test_layered_fallback_readme_example_matches_the_tool(monkeypatch):
    # The Layered value resolution section shows CLI > env > config > default.
    doc = (
        "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [default: 80] [env: APP_PORT] [config: server.port]."
    )
    cfg = {"server": {"port": 8080}}
    monkeypatch.delenv("APP_PORT", raising=False)
    assert_that(docopt(doc, "", complete=False, config=cfg)["--port"]).is_equal_to("8080")  # config
    monkeypatch.setenv("APP_PORT", "7000")
    assert_that(docopt(doc, "", complete=False, config=cfg)["--port"]).is_equal_to("7000")  # env wins
    assert_that(docopt(doc, "--port=9000", complete=False, config=cfg)["--port"]).is_equal_to("9000")  # cli wins
    assert_that(README).contains("[config: server.port]")


_RICH_HELP_DOC = (
    "Serve a directory over HTTP.\n\nUsage:\n  serve [--port=<n>] [--host=<h>] [--log=<lvl>] <root>\n\n"
    "Options:\n  --port=<n>  Port to bind [default: 8080] [env: PORT] [config: server.port].\n"
    "  --host=<h>  Interface to bind [default: 127.0.0.1] [env: HOST].\n"
    "  --log=<lvl>  Log verbosity [default: info] [config: logging.level]."
)


def test_rich_help_screenshot_matches_the_tool():
    # docs/assets/rich-help.png is rendered from this exact output, with the value-provenance chains.
    out = render_help(_RICH_HELP_DOC)
    assert_that(out).starts_with("Serve a directory over HTTP.")
    assert_that(out).contains("serve [--port=<n>] [--host=<h>] [--log=<lvl>] <root>")
    assert_that(out).contains("Port to bind.").contains("[env: PORT, config: server.port, default: 8080]")
    assert_that(out).contains("[env: HOST, default: 127.0.0.1]").contains("[config: logging.level, default: info]")
    assert_that(README).contains('help_style="rich"')


def test_completion_candidates_match_the_tool():
    # The Shell completion block shows the Tab candidates; pin them to complete() on the naval usage.
    doc = _naval_doc()
    assert_that(complete(doc, [""])).is_equal_to(["--help", "--speed", "ship"])
    assert_that(complete(doc, ["ship", ""])).is_equal_to(["--speed", "new"])
    assert_that(complete(doc, ["ship", "titanic", "move", "1", "2", ""])).is_equal_to(["--speed"])


def test_typed_example_actually_types_and_coerces():
    # The "Why typed" example: host: str, port: int (coerced), verbose: bool - and the doc is really in the README.
    doc = "Usage: app <host> <port> [--verbose]"
    assert_that(README).contains(doc)

    @dataclasses.dataclass
    class Args:
        host: str
        port: int
        verbose: bool

    result = docopt(doc, "localhost 8080 --verbose", complete=False, schema=Args)
    assert_that(result.host).is_equal_to("localhost")
    assert_that(result.port).is_equal_to(8080)
    assert_that(type(result.port)).is_equal_to(int)
    assert_that(result.verbose).is_true()


# The diagnostics/check screenshots in the README are rendered from this exact tool output. Pin it, so a
# change to the renderer fails here (a reminder to regenerate docs/assets/*.png) instead of drifting silently.
_DIAGNOSTIC_DOC = (
    "Usage:\n  git commit [--message=<msg>] [--amend]\n  git push [--force] <remote>\n\n"
    "Options:\n  --message=<msg>  Commit message.\n  --amend          Amend the last commit.\n"
    "  --force          Force the push.\n"
)
_EXPECTED_DIAGNOSTIC = (
    "error: unknown option `--forcce`\n"
    "   |\n"
    "   |  in the arguments:\n"
    "   |    push --forcce origin\n"
    "   |         ^^^^^^^^ not a known option\n"
    "   |\n"
    "   |  in the usage:\n"
    "   |      git push [--force] <remote>\n"
    "   |                ^^^^^^^ `--force` is defined here\n"
    "   |\n"
    "   = help: did you mean `--force`?"
)

_CHECK_DOC = (
    "Naval Fate.\n\nUsage:\n  naval ship new <name>...\n  naval ship <name> move <x> <y> [--speed=<kn>]\n"
    "  naval --help\n\nOptions:\n  --speed=<kn>  Speed in knots [default: 10].\n  --verbose     Extra logging.\n"
)
_EXPECTED_CHECK = (
    "warning: option `--verbose` is declared but never used\n"
    "   |\n"
    "   |  in the options:\n"
    "   |      --verbose     Extra logging.\n"
    "   |      ^^^^^^^^^ declared here\n"
    "   |\n"
    "   = help: add `--verbose` to a usage line, or add `[options]` to accept it"
)


def test_diagnostic_screenshot_text_still_matches_the_tool():
    with raises(DocoptExit) as exit_info:
        docopt(_DIAGNOSTIC_DOC, "push --forcce origin", suggest=True, complete=False)
    assert_that(str(exit_info.value)).starts_with(_EXPECTED_DIAGNOSTIC)


def test_check_screenshot_text_still_matches_the_tool():
    warnings = check(_CHECK_DOC)
    assert_that(warnings).is_length(1)
    assert_that(warnings[0].render()).is_equal_to(_EXPECTED_CHECK)


_COERCION_DOC = "Usage: prog --port=<n>\n\nOptions:\n  --port=<n>  Port."
_EXPECTED_COERCION = (
    "error: invalid value for `--port`\n"
    "   |\n"
    "   |  in the arguments:\n"
    "   |    --port=abc\n"
    "   |           ^^^ expected int\n"
    "   |\n"
    "   |  in the usage:\n"
    "   |    Usage: prog --port=<n>\n"
    "   |                ^^^^^^^^^^ typed as int\n"
    "   |\n"
    "   = help: `abc` is not a valid int"
)


def test_coercion_screenshot_text_still_matches_the_tool():
    @dataclasses.dataclass
    class Port:
        port: int

    with raises(DocoptExit) as exit_info:
        docopt(_COERCION_DOC, "--port=abc", complete=False, schema=Port)
    assert_that(str(exit_info.value)).starts_with(_EXPECTED_COERCION)
