import dataclasses
import html
import re
from pathlib import Path

from assertpy2 import assert_that
from pytest import raises

from docopt2 import (
    DocoptExit,
    DocoptLanguageError,
    check,
    check_compat,
    docopt,
    format_usage,
    generate_config_template,
    generate_examples,
)
from docopt2._help import render_help
from docopt2._typed import _scalar_coercers

# Every `.docopt2-term` block in the docs is verbatim tool output, and almost nothing checked it: only
# README.md and getting-started.md had guards, so the guides quietly kept a stale bash completion script
# and `help:` labels the tool had stopped emitting. This pins the lot, and it is exhaustive by
# construction: a block that no registered command produces fails the suite, so one cannot be added
# unguarded either.

_ROOT = Path(__file__).parent.parent
_BLOCK = re.compile(r'<div class="docopt2-term">(.*?)</div>', re.S)


def _visible(markup: str) -> str:
    """The text a reader actually sees in a terminal block: tags dropped, entities decoded."""
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


def _normalise(text: str) -> str:
    """Compare on content, not on the trailing whitespace the markup happens to carry."""
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _documented_blocks() -> list[tuple[str, str]]:
    """Every terminal block in the docs, as ``(where, visible text)``."""
    files = [*sorted(_ROOT.joinpath("docs").rglob("*.md")), _ROOT / "README.md"]
    return [
        (f"{path.relative_to(_ROOT).as_posix()}#{index}", _normalise(_visible(match.group(1))))
        for path in files
        for index, match in enumerate(_BLOCK.finditer(path.read_text(encoding="utf-8")), start=1)
    ]


def _fails(doc: str, argv: str, **kwargs: object) -> str:
    """The diagnostic a failing parse renders, without the usage block appended after it."""
    with raises(DocoptExit) as exit_info:
        docopt(doc, argv, complete=False, **kwargs)  # ty: ignore[invalid-argument-type] - kwargs are docopt's own
    exit_signal = exit_info.value
    return str(exit_signal).removesuffix("\n" + exit_signal.usage)


def _rejects(doc: str, argv: str) -> str:
    """The diagnostic a malformed usage message renders."""
    with raises(DocoptLanguageError) as exit_info:
        docopt(doc, argv, complete=False)
    return str(exit_info.value)


@dataclasses.dataclass
class _Port:
    port: int


_GIT_PUSH = "Git push.\n\nUsage:\n  git push [--force] <remote>\n\nOptions:\n  --force  Force the push.\n"
_GIT_MULTI = (
    "Usage:\n  git push [--force] <remote>\n  git commit --message=<msg>\n  git add <path>...\n\n"
    "Options:\n  --force          Force.\n  --message=<msg>  Message."
)
_CLI_PY = (
    "Usage: greet --name=<who>\n\nOptions:\n"
    "  --name=<who>  Who to greet [default: world].\n  --shout       Upper-case the greeting.\n"
)
_NAVAL = (_ROOT / "examples" / "naval_fate.py").read_text(encoding="utf-8").split('"""')[1]
_NAVAL_EXAMPLES = (
    "Usage:\n"
    "  naval ship new <name>...\n"
    "  naval ship <name> move <x> <y> [--speed=<kn>]\n"
    "  naval mine (set | remove) <x> <y>\n"
    "  naval --help\n\n"
    "Options:\n"
    "  --speed=<kn>  Speed in knots [default: 10]."
)
_FMT_BEFORE = (
    "Usage:\n  serve [--port=<n>] [--host=<h>] <root>\n\n"
    "Options:\n  --port=<n>  Port [default: 8080].\n"
    "  --host=<h>   Interface [default: 127.0.0.1].\n"
    "  -v, --verbose  Be loud.\n"
)
_RICH_SERVE = (
    "Serve a directory over HTTP.\n\n"
    "Usage:\n  serve [--port=<n>] [--host=<h>] [--log=<lvl>] <root>\n\n"
    "Options:\n"
    "  --port=<n>  Port to bind [default: 8080] [env: PORT] [config: server.port].\n"
    "  --host=<h>  Interface to bind [default: 127.0.0.1] [env: HOST].\n"
    "  --log=<lvl>  Log verbosity [default: info] [config: logging.level].\n"
)
_RICH_GIT = (
    "Git.\n\nUsage:\n  git commit [--message=<msg>] [--amend]\n\n"
    "Options:\n  --message=<msg>  Commit message to record.\n  --amend          Amend the last commit.\n"
)
_CONFIG_DOC = (
    "Usage: prog [options]\n\nOptions:\n"
    "  --host=<h>   Bind address [default: 0.0.0.0] [config: server.host].\n"
    "  --port=<n>   Port [default: 8080] [env: APP_PORT] [config: server.port].\n"
    "  --verbose    Log verbosely [config: logging.verbose]."
)


def _checked(doc: str) -> str:
    return check(doc)[0].render()


def _produced() -> dict[str, str]:
    """Each documented block, keyed by where it lives, paired with the command that must still produce it."""
    return {
        # docs/guides/check.md - one block per lint rule, plus the CLI transcript
        "check: unusable option": _checked("Usage: prog\n\nOptions:\n  --verbose  Extra logging."),
        "check: dead option default": _checked("Usage: prog --port=<n>\n\nOptions:\n  --port=<n>  Port [default: 80]."),
        "check: dead argument default": _checked(
            "Usage: prog <host>\n\nArguments:\n  <host>  Host name [default: localhost]."
        ),
        "check: ambiguous variadics": _checked("Usage: prog <a>... <b>..."),
        "check: redundant alternative": _checked("Usage: prog (add | add)"),
        "check: empty [options]": _checked("Usage: prog [options] <f>"),
        "check: the CLI": "$ docopt2 check cli.py\n" + "\n".join(w.render() for w in check(_CLI_PY)),
        # docs/guides/diagnostics.md
        "diag: unknown option, suggested": _fails(_GIT_PUSH, "push --forcce origin", suggest=True),
        "diag: unknown option, unsuggested": _fails(
            "Usage:\n  git push [--force] <remote>\n\nOptions:\n  --force  Force.\n", "push --forcce origin"
        ),
        "diag: mutually exclusive": _fails(
            "Usage: prog (--fast | --slow)\n\nOptions:\n  --fast  Fast.\n  --slow  Slow.", "--fast --slow"
        ),
        "diag: near miss": _fails(_GIT_MULTI, "push"),
        "diag: bad value": _fails("Usage: prog --port=<n>", "--port=abc", schema=_Port),
        "diag: unclosed group": _rejects("Usage: prog [--force <remote>", "push"),
        "diag: mismatched delimiters": _rejects("Usage: prog (a | b]", "a"),
        # docs/guides/typed-results.md
        "typed: bad value": _fails("Usage: prog <port>", "eighty", schema=_Port),
        # docs/getting-started.md
        "getting-started: near miss": "$ python naval_fate.py ship Titanic move 1\n"
        + _fails(_NAVAL, "ship Titanic move 1"),
        # docs/guides/compat.md
        "compat: the CLI": "$ docopt2 compat old-usage.txt new-usage.txt\n"
        + "\n".join(check_compat("Usage: git push [--force] <remote>", "Usage: git push <remote> <branch>")),
        # docs/guides/examples.md
        "examples: valid": "$ docopt2 examples naval.txt --count=5 --seed=7\n"
        + "\n".join(" ".join(argv) for argv in generate_examples(_NAVAL_EXAMPLES, count=5, seed=7)),
        "examples: invalid": "$ docopt2 examples naval.txt --count=3 --invalid --seed=7\n"
        + "\n".join(" ".join(argv) for argv in generate_examples(_NAVAL_EXAMPLES, count=3, valid=False, seed=7)),
        # docs/guides/fmt.md
        "fmt: the CLI": "$ docopt2 fmt serve.py\n" + format_usage(_FMT_BEFORE),
        # docs/guides/help.md
        "help: rich, with provenance": render_help(_RICH_SERVE),
        "help: rich, plain options": render_help(_RICH_GIT),
        # docs/guides/usage-dsl.md
        "usage-dsl: config template": "$ docopt2 config-template serve.py\n\n" + generate_config_template(_CONFIG_DOC),
    }


def test_the_docs_show_only_output_the_tool_really_produces():
    produced = {_normalise(text) for text in _produced().values()}
    unguarded = [(where, text) for where, text in _documented_blocks() if text not in produced]
    detail = "\n\n".join(f"--- {where} ---\n{text}" for where, text in unguarded)
    assert_that(unguarded).described_as(f"blocks no registered command produces:\n{detail}").is_empty()


# The block guard above only sees verbatim TOOL OUTPUT. A prose claim drifts silently, and one did: the
# coercion table in typed-results.md calls its set CLOSED, yet `datetime.time` was added to the code and
# never to the table. This holds the two together in BOTH directions - a type the code coerces but the
# docs omit, and a row the docs invent - which is why `_scalar_coercers()` is data and not an if-chain.
# `[^`]+`, not `.+?`: a backtick-quoted token cannot contain a backtick, and a lazy `.` that can match one
# lets a run of them be grouped exponentially many ways - catastrophic backtracking (CodeQL py/redos).
_TABLE_ROW = re.compile(r"^\| (`[^`]+`(?:, `[^`]+`)*)(?: subclass)? \|", re.M)
# The forms whose coercion carries its own semantics, so they are spelled out in `_coerce`, not in the map.
_SPELLED_OUT = {
    "str",
    "bool",
    "list[T]",
    "list",
    "T | None",
    "T | U",
    "Annotated[T, ...]",
    'Literal["a", "b"]',
    "enum.Enum",
}


def _documented_annotations() -> set[str]:
    table = (_ROOT / "docs/guides/typed-results.md").read_text(encoding="utf-8")
    cells = _TABLE_ROW.findall(table)
    return {token.replace(r"\|", "|") for cell in cells for token in re.findall(r"`([^`]+)`", cell)}


def _documented_name(annotation: type) -> str:
    # The public module, not __module__: on 3.13 pathlib is split and reports `Path` as `pathlib._local`,
    # which is an implementation detail no table would ever print.
    module = annotation.__module__.split(".", 1)[0]
    return annotation.__name__ if module == "builtins" else f"{module}.{annotation.__name__}"


def test_the_coercion_table_documents_exactly_the_types_the_code_coerces():
    documented = _documented_annotations()
    coercible = {_documented_name(annotation) for annotation in _scalar_coercers()}
    assert_that(coercible - documented).described_as("coerced by the code, missing from the table").is_empty()
    assert_that(documented - _SPELLED_OUT - coercible).described_as("in the table, coerced by nothing").is_empty()
