from __future__ import annotations

import re

from docopt2._parser import section_line_numbers

# What the parser calls an option line: a dash followed by a non-space (`-v`, `--speed=<kn>`). A dash
# followed by a SPACE is a prose bullet - `- fast, quick` - and the option tidier would eat its commas.
_OPTION_LINE = re.compile(r"-\S")
_BLANKS = " \t"  # what indents a line for the parser: str.strip() would also take a form feed, U+0085 and their kin
_KEYWORD = re.compile(r"options:", re.IGNORECASE)


def _shares_the_header(line: str) -> bool:
    """Whether ``line`` holds the section keyword and more after it: the parser reads a header there, and an option
    on such a line ends its spec by blanks that are the line's own."""
    return bool(_KEYWORD.search(line)) and not line.rstrip().lower().endswith("options:")


def _continued(lines: list[str], index: int, in_options: set[int]) -> bool:
    """Whether the option on line ``index`` has a description that starts on a later line: the first line under
    it that is not blank is in the section and is no option."""
    for later in range(index + 1, len(lines)):
        body = lines[later].lstrip(_BLANKS)
        if later not in in_options or body:
            return later in in_options and not _OPTION_LINE.match(body)
    return False


def format_usage(doc: str) -> str:
    """Reformat the ``Options:`` lines of a usage message: align every description into one column, tidy each
    option spec (comma separators to spaces, runs of whitespace collapsed), and strip trailing whitespace.

    Only the lines the parser reads options from are re-aligned: those inside an ``options:`` section, led by
    a dash and a non-space. Anything else keeps every character, trailing whitespace aside, whether it is a
    ``Usage:`` pattern, a prose bullet or a wrapped description.

    It is idempotent and semantics-preserving. The parsed options are identical and only the layout changes.
    So the whitespace the parser reads is kept: a line of blanks alone, which holds a section together, and the
    two blanks that end an option's spec where its description starts on a later line. A line is left whole
    where the parser reads it in a second way too: it holds the word ``options:`` and more after it, or it is
    an option that also stands in a ``usage:`` or an ``arguments:`` section. A spec is left as written where
    tidying it would make the line no option.

    It is to [`check`][docopt2.check] what a formatter is to a linter: ``check`` finds defects, ``format_usage`` (and
    ``docopt2 fmt``) tidies the layout of an otherwise valid usage.
    """
    lines = [line.removesuffix("\r") for line in doc.split("\n")]  # splitlines() breaks at a form feed too
    in_options = section_line_numbers("options:", doc)
    read_twice = section_line_numbers("usage:", doc) | section_line_numbers("arguments:", doc)
    whole = {index for index, line in enumerate(lines) if _shares_the_header(line)}
    entries: dict[int, tuple[int, str, str]] = {}
    for index, line in enumerate(lines):
        body = line.lstrip(_BLANKS)
        if index not in in_options or not _OPTION_LINE.match(body):
            continue
        if index in read_twice or index in whole:
            whole.add(index)
            continue
        spec, separator, description = body.partition("  ")
        tidy = " ".join(spec.replace(",", " ").split())
        if not _OPTION_LINE.match(tidy):  # `-, --all` would become `- --all`, a prose bullet
            tidy = spec
        if separator and not description.strip() and _continued(lines, index, in_options):
            tidy += "  "  # the two blanks end the spec: stripped, the description below would join it
        entries[index] = (len(line) - len(body), tidy, description.strip())
    width = max((len(spec.rstrip()) for _, spec, _ in entries.values()), default=0)
    # A whitespace-only spacer line holds the section together for the parser; rstripping it to empty would
    # end the section early and drop the options after it. Leave such lines verbatim (semantics over tidy).
    out = [line if (line and not line.strip()) or index in whole else line.rstrip() for index, line in enumerate(lines)]
    for index, (indent, spec, description) in entries.items():
        out[index] = " " * indent + (f"{spec.ljust(width)}  {description}" if description else spec)
    return "\n".join(out)
