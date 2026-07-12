import dataclasses
import re
from pathlib import Path

from assertpy2 import assert_that
from pytest import raises

from docopt2 import DocoptExit, docopt

GETTING_STARTED = (Path(__file__).parent.parent / "docs" / "getting-started.md").read_text(encoding="utf-8")


def _naval_doc() -> str:
    # The naval_fate.py block embeds the usage message as a module docstring; run the real thing against it.
    match = re.search(r'"""(Naval Fate\..*?)"""', GETTING_STARTED, re.DOTALL)
    assert match is not None
    return match.group(1)


def test_every_python_block_is_valid_python():
    # A syntax typo in any getting-started example fails here before it ships.
    for block in re.findall(r"```python\n(.*?)```", GETTING_STARTED, re.DOTALL):
        compile(block, "<getting-started>", "exec")


def test_first_parse_positional_values_match_the_tool():
    result = docopt("Usage: prog <host> <port>", "127.0.0.1 8080", complete=False)
    assert_that(result["<host>"]).is_equal_to("127.0.0.1")
    assert_that(result["<port>"]).is_equal_to("8080")


def test_option_with_default_matches_the_tool():
    doc = "Usage: prog <host> [--port=<n>]\n\nOptions:\n  --port=<n>  [default: 8000]"
    assert_that(docopt(doc, "localhost", complete=False)["--port"]).is_equal_to("8000")  # default fills in
    assert_that(docopt(doc, "localhost --port=9000", complete=False)["--port"]).is_equal_to("9000")  # argument wins


def test_flag_is_true_when_present_and_false_when_absent():
    doc = "Usage: prog [--verbose] <host>"
    assert_that(docopt(doc, "--verbose example.com", complete=False)["--verbose"]).is_true()
    assert_that(docopt(doc, "example.com", complete=False)["--verbose"]).is_false()


def test_command_bool_and_repeatable_list_match_the_tool():
    result = docopt("Usage: prog add <file>...", "add a.txt b.txt", complete=False)
    assert_that(result["add"]).is_true()
    assert_that(result["<file>"]).is_equal_to(["a.txt", "b.txt"])


def test_naval_dict_output_matches_the_tool():
    result = docopt(_naval_doc(), "ship new Titanic Bismarck", complete=False)
    assert_that(result["ship"]).is_true()
    assert_that(result["new"]).is_true()
    assert_that(result["<name>"]).is_equal_to(["Titanic", "Bismarck"])
    assert_that(result["--speed"]).is_equal_to("10")  # [default: 10]
    assert_that(result["<x>"]).is_none()
    # the shown dict block is `print(arguments)` verbatim, so pin it to the real repr
    assert_that(GETTING_STARTED).contains(repr(result))


def test_second_invocation_values_match_the_tool():
    result = docopt(_naval_doc(), "ship Titanic move 1 2 --speed=15", complete=False)
    assert_that(result["ship"]).is_true()
    assert_that(result["move"]).is_true()
    assert_that(result["<name>"]).is_equal_to(["Titanic"])
    assert_that(result["<x>"]).is_equal_to("1")
    assert_that(result["--speed"]).is_equal_to("15")


def test_error_caret_matches_the_tool():
    with raises(DocoptExit) as exc_info:
        docopt(_naval_doc(), "ship Titanic move 1", complete=False)
    message = str(exc_info.value)
    # the tool produces the near-miss caret under the closest line's <y> (the ship/move line)
    assert_that(message).contains("missing required `<y>`").contains("closest of 6 usage patterns")
    assert_that(message).contains("naval_fate ship <name> move <x> <y> [--speed=<kn>]").contains("^^^ required here")
    # the colored .docopt2-term block in the doc mirrors that output, HTML-escaped
    assert_that(GETTING_STARTED).contains("missing required `&lt;y&gt;`").contains("closest of 6 usage patterns")
    assert_that(GETTING_STARTED).contains("naval_fate ship &lt;name&gt; move &lt;x&gt; &lt;y&gt; [--speed=&lt;kn&gt;]")
    assert_that(GETTING_STARTED).contains('<span class="dt-caret">^^^</span>')


def test_version_output_matches_the_tool(capsys):
    with raises(SystemExit):
        docopt(_naval_doc(), "--version", version="Naval Fate 2.0", complete=False)
    assert_that(capsys.readouterr().out.strip()).is_equal_to("Naval Fate 2.0")
    assert_that(GETTING_STARTED).contains("Naval Fate 2.0")


@dataclasses.dataclass
class Args:
    host: str
    port: int  # coerced from the parsed string; module-level so repr reads `Args(...)` as the doc shows


def test_typed_result_repr_matches_the_tool():
    result = docopt("Usage: prog <host> <port>", "127.0.0.1 8080", schema=Args, complete=False)
    assert_that(repr(result)).is_equal_to("Args(host='127.0.0.1', port=8080)")
    assert_that(GETTING_STARTED).contains("Args(host='127.0.0.1', port=8080)")
