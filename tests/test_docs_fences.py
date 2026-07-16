import ast
import io
import re
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest
from assertpy2 import assert_that

# test_docs_blocks.py pins the styled `.docopt2-term` blocks; nothing pinned the plain ```python fences whose
# `# ...` tail shows what the code returns - and one rotted exactly there: examples.md advertised an argv the
# sampler had stopped emitting, and the stale line contradicted the page's own prose. This runs every such
# block and holds its comment to what the code really produces.
#
# It compares MEANING, not text, so the docs stay written for the reader: a trailing `-> teaching note` is
# dropped, and a literal is compared as a VALUE (`literal_eval`), so a doc may show a dict in whatever key
# order reads best. Blocks with no `# ...` tail are still executed - they set up the names later ones use.

_ROOT = Path(__file__).parent.parent
_FENCE = re.compile(r"```python\n(.*?)```", re.S)
# A DSL reference page is a table of one-liners (`docopt("Usage: prog ship new <name>", ...)`); repeating an
# import above each would drown it. The reader is told once, in prose, so the runner supplies the same names.
_PREAMBLE = "from docopt2 import *  # noqa: F403"
# concepts/design-boundaries.md asks `"pydantic" in sys.modules`, and only a clean interpreter can answer:
# by the time this suite runs, other tests have imported pydantic. tests/test_import_cost.py pins that exact
# claim in a subprocess instead - a better guard than this one could ever be, so the block is skipped here.
_ANSWERED_IN_A_CLEAN_PROCESS = ('"pydantic" in sys.modules',)
_ANNOTATION = re.compile(r"\s+->\s.*\Z", re.S)


def _split_output(source: str) -> tuple[str, str | None]:
    """Split a block into its code and the trailing `# ...` lines that show what the code produces."""
    lines = source.splitlines()
    cut = len(lines)
    while cut > 0 and lines[cut - 1].strip().startswith("#"):
        cut -= 1
    code_lines, comment_lines = lines[:cut], lines[cut:]
    if not comment_lines or not any(line.strip() for line in code_lines):
        return source, None
    return "\n".join(code_lines), "\n".join(re.sub(r"^\s*#\s?", "", line) for line in comment_lines)


def _is_print(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "print"
    )


def _run(code: str, namespace: dict[str, Any]) -> tuple[str, str, Any]:
    """Execute a block: a bare final expression yields its repr, anything else yields what it printed.

    A `--help` block prints and raises SystemExit; that IS its output, so the exit is a normal ending here.
    """
    tree = ast.parse(code)
    if not tree.body:
        return "stdout", "", None
    *body, last = tree.body
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            if body:
                exec(compile(ast.Module(body, type_ignores=[]), "<doc>", "exec"), namespace)
            if isinstance(last, ast.Expr) and not _is_print(last):
                value = eval(compile(ast.Expression(last.value), "<doc>", "eval"), namespace)
                return "repr", repr(value), value
            exec(compile(ast.Module([last], type_ignores=[]), "<doc>", "exec"), namespace)
    except SystemExit:
        pass
    return "stdout", buffer.getvalue(), None


def _matches(mode: str, produced: str, expected: str, value: Any) -> bool:
    expected = _ANNOTATION.sub("", expected)
    if mode == "repr":
        try:  # a literal: compare values, so key order and line layout are the doc's to choose
            return bool(ast.literal_eval(expected) == value)
        except (ValueError, SyntaxError):  # a repr like `Args(host=...)`: compare the text, layout-insensitively
            return re.sub(r"\s+", " ", produced).strip() == re.sub(r"\s+", " ", expected).strip()
    return _lines(produced) == _lines(expected)


def _lines(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _checked_fences() -> list[tuple[str, str, str, dict[str, Any]]]:
    """Each checkable block paired with the page namespace as it stands when the block runs."""
    prepared = []
    for path in sorted(_ROOT.joinpath("docs").rglob("*.md")):
        namespace: dict[str, Any] = {}
        exec(_PREAMBLE, namespace)  # the import the reference pages state in prose rather than per block
        for index, block in enumerate(_FENCE.findall(path.read_text(encoding="utf-8")), start=1):
            code, expected = _split_output(block)
            where = f"{path.relative_to(_ROOT).as_posix()}#{index}"
            skipped = any(skip in code for skip in _ANSWERED_IN_A_CLEAN_PROCESS)
            if expected is not None and not skipped:
                prepared.append((where, code, expected, dict(namespace)))
            try:  # threading the page: a block that cannot run alone simply contributes no names
                _run(code, namespace)
            except Exception:  # a checkable block's own failure is reported by its own test, not here
                pass
    return prepared


_FENCES = _checked_fences()


@pytest.mark.parametrize(("where", "code", "expected", "namespace"), _FENCES, ids=[case[0] for case in _FENCES])
def test_a_documented_python_block_produces_what_it_shows(where, code, expected, namespace):
    mode, produced, value = _run(code, namespace)
    assert_that(_matches(mode, produced, expected, value)).described_as(
        f"{where}\n  the block shows: {expected!r}\n  the code produces: {produced!r}"
    ).is_true()


def test_the_docs_still_hold_python_blocks_worth_checking():
    # A guard on the guard: if a refactor silently stopped finding blocks, every test above would vacuously
    # pass. The count is a floor, not an exact number, so adding a documented block never fails this.
    assert_that(len(_FENCES)).described_as("checkable python blocks found in docs/").is_greater_than(15)
