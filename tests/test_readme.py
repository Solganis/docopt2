import dataclasses
import re
from pathlib import Path

from assertpy2 import assert_that
from pytest import raises

from docopt2 import DocoptExit, check, docopt, generate_stub

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
    # The shown `docopt2 stub` output must be exactly what the tool emits for the shown usage.
    shown = _block_containing("ship: bool").strip()
    assert_that(generate_stub(_naval_doc()).strip()).is_equal_to(shown)


def test_quick_start_result_shape_matches_the_tool():
    # The Quick start comment claims {"ship": True, "<name>": ["titanic"], "move": True, "--speed": "10", ...}.
    result = docopt(_naval_doc(), "ship titanic move 1 2", complete=False)
    assert_that(result["ship"]).is_true()
    assert_that(result["<name>"]).is_equal_to(["titanic"])
    assert_that(result["move"]).is_true()
    assert_that(result["--speed"]).is_equal_to("10")


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
