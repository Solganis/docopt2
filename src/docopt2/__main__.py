from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

from docopt2 import (
    Dispatch,
    __version__,
    check,
    check_compat,
    format_usage,
    generate_config_template,
    generate_examples,
    generate_stub,
)
from docopt2._diagnostics import use_color
from docopt2._errors import DocoptLanguageError

_STYLES = ("dataclass", "typeddict", "cli")

# The tool's own interface is a docopt usage message parsed by docopt2 itself (via Dispatch): the
# command line is described here, not built imperatively - the library dogfooding its own model.
_DOC = """\
docopt2 - typed tooling for docopt usage messages.

Usage:
  docopt2 stub <source> [--name=<name>] [--style=<style>]
  docopt2 check <source>
  docopt2 examples <source> [--count=<n>] [--invalid] [--seed=<n>]
  docopt2 config-template <source>
  docopt2 compat <old-source> <new-source>
  docopt2 fmt <source>
  docopt2 (-h | --help)
  docopt2 --version

<source> is a Python file (its module docstring is read, without importing it), a text
file of raw usage, or - for standard input.

Options:
  --name=<name>    Class name for the generated schema [default: Args].
  --style=<style>  Schema style: dataclass, typeddict, or cli [default: dataclass].
  --count=<n>      How many example invocations to generate [default: 10].
  --invalid        Generate argument vectors the usage rejects, not ones it accepts.
  --seed=<n>       Seed the generator for reproducible output.
  -h --help        Show this help and exit.
  --version        Show the docopt2 version and exit.
"""


class _CliError(Exception):
    """A user-facing CLI error (bad --style, no readable usage); reported as ``error: ...``, exit 1."""


def _read_usage(source: str) -> str:
    """Load the usage message from ``source``: stdin (``-``), a ``.py`` module docstring, or a text file."""
    if source == "-":
        return sys.stdin.read()
    path = Path(source)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise _CliError(f"{source}: not a UTF-8 text file") from error
    if path.suffix != ".py":
        return text
    docstring = ast.get_docstring(ast.parse(text))
    if docstring is None:
        raise _CliError(f"{source}: no module docstring to read a usage message from")
    return docstring


def _run_stub(arguments: Any) -> int:
    style = arguments["--style"]
    if style not in _STYLES:
        raise _CliError(f"--style must be dataclass, typeddict, or cli, not {style!r}")
    print(generate_stub(_read_usage(arguments["<source>"]), name=arguments["--name"], style=style), end="")
    return 0


def _run_check(arguments: Any) -> int:
    warnings = check(_read_usage(arguments["<source>"]))
    for warning in warnings:
        print(warning.render(color=use_color(sys.stderr)), file=sys.stderr)
    return 1 if warnings else 0


def _as_int(value: str, flag: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise _CliError(f"{flag} must be an integer, not {value!r}") from None


def _run_examples(arguments: Any) -> int:
    seed = None if arguments["--seed"] is None else _as_int(arguments["--seed"], "--seed")
    examples = generate_examples(
        _read_usage(arguments["<source>"]),
        count=_as_int(arguments["--count"], "--count"),
        valid=not arguments["--invalid"],
        seed=seed,
    )
    for argv in examples:
        print(" ".join(argv))
    return 0


def _run_config_template(arguments: Any) -> int:
    print(generate_config_template(_read_usage(arguments["<source>"])), end="")
    return 0


def _run_compat(arguments: Any) -> int:
    breaks = check_compat(_read_usage(arguments["<old-source>"]), _read_usage(arguments["<new-source>"]))
    for entry in breaks:
        print(entry, file=sys.stderr)
    return 1 if breaks else 0  # like `check`: silent and 0 when no breakage is found, else the breaks and 1


def _run_fmt(arguments: Any) -> int:
    print(format_usage(_read_usage(arguments["<source>"])), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``docopt2`` console command and ``python -m docopt2``."""
    app = Dispatch(_DOC)
    app.on("stub")(_run_stub)
    app.on("check")(_run_check)
    app.on("examples")(_run_examples)
    app.on("config-template")(_run_config_template)
    app.on("compat")(_run_compat)
    app.on("fmt")(_run_fmt)
    try:
        result: int = app.run(argv, version=__version__, complete=False)
    except (_CliError, DocoptLanguageError, OSError, SyntaxError, ValueError) as exc:
        # ValueError also covers generate_stub rejecting a bad --name and a NUL byte in a source file.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return result


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
