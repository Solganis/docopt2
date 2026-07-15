from __future__ import annotations

import re

from docopt2._parser import section_line_numbers

# What the parser calls an option line: a dash followed by a non-space (`-v`, `--speed=<kn>`). A dash
# followed by a SPACE is a prose bullet - `- fast, quick` - and the option tidier would eat its commas.
_OPTION_LINE = re.compile(r"-\S")


def format_usage(doc: str) -> str:
    """Reformat the ``Options:`` lines of a usage message: align every description into one column, tidy each
    option spec (comma separators to spaces, runs of whitespace collapsed), and strip trailing whitespace.

    Only the lines the parser reads options from are re-aligned: inside an ``options:`` section, and led by a
    dash and a non-space. Anything else - a ``Usage:`` pattern, a prose bullet, a wrapped description - keeps
    every character (trailing whitespace aside). Idempotent and semantics-preserving: the parsed options are
    identical, only the layout changes. It is to `check` what a formatter is to a linter: `check` finds
    defects, ``format_usage`` (and ``docopt2 fmt``) tidies the layout of an otherwise valid usage.
    """
    lines = doc.splitlines()
    in_options = section_line_numbers("options:", doc)
    entries: dict[int, tuple[int, str, str]] = {}
    for index, line in enumerate(lines):
        if index in in_options and _OPTION_LINE.match(line.lstrip()):
            indent = len(line) - len(line.lstrip())
            spec, _, description = line.strip().partition("  ")
            entries[index] = (indent, " ".join(spec.replace(",", " ").split()), description.strip())
    width = max((len(spec) for _, spec, _ in entries.values()), default=0)
    # A whitespace-only spacer line holds the section together for the parser; rstripping it to empty would
    # end the section early and drop the options after it. Leave such lines verbatim (semantics over tidy).
    out = [line if line and not line.strip() else line.rstrip() for line in lines]
    for index, (indent, spec, description) in entries.items():
        out[index] = " " * indent + (f"{spec.ljust(width)}  {description}" if description else spec)
    return "\n".join(out) + ("\n" if doc.endswith("\n") else "")
