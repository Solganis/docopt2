from __future__ import annotations

from docopt2._parser import section_line_numbers


def format_usage(doc: str) -> str:
    """Reformat the ``Options:`` lines of a usage message: align every description into one column, tidy each
    option spec (comma separators to spaces, runs of whitespace collapsed), and strip trailing whitespace.

    Only lines inside an ``options:`` section are re-aligned - the same lines the parser reads options from.
    A ``-``-led line anywhere else is prose, and prose is left alone. Trailing whitespace is stripped
    throughout. Idempotent and semantics-preserving: the parsed options are identical, only the layout
    changes, and the ``Usage:`` patterns keep their text. It is to `check` what a formatter is to a linter:
    `check` finds defects, ``format_usage`` (and ``docopt2 fmt``) tidies the layout of an otherwise valid usage.
    """
    lines = doc.splitlines()
    # Only `options:` sections, as the parser reads them: an option spec turns `,` into a separator, so a
    # prose bullet matched as an option would come back with its commas deleted.
    in_options = section_line_numbers("options:", doc)
    entries: dict[int, tuple[int, str, str]] = {}
    for index, line in enumerate(lines):
        if index in in_options and line.lstrip().startswith("-"):
            indent = len(line) - len(line.lstrip())
            spec, _, description = line.strip().partition("  ")
            entries[index] = (indent, " ".join(spec.replace(",", " ").split()), description.strip())
    width = max((len(spec) for _, spec, _ in entries.values()), default=0)
    out = [line.rstrip() for line in lines]
    for index, (indent, spec, description) in entries.items():
        out[index] = " " * indent + (f"{spec.ljust(width)}  {description}" if description else spec)
    return "\n".join(out) + ("\n" if doc.endswith("\n") else "")
