from __future__ import annotations


def format_usage(doc: str) -> str:
    """Reformat a usage message's ``Options:`` lines: align every description into one column, tidy each
    option spec (comma separators to spaces, runs of whitespace collapsed), and strip trailing whitespace.

    Idempotent and semantics-preserving - the parsed options are identical, only the layout changes; the
    ``Usage:`` patterns are left untouched. It is to `check` what a formatter is to a linter: `check` finds
    defects, ``format_usage`` (and ``docopt2 fmt``) tidies the layout of an otherwise valid usage.
    """
    lines = doc.splitlines()
    entries: dict[int, tuple[int, str, str]] = {}
    for index, line in enumerate(lines):
        if line.lstrip().startswith("-"):  # an option-description line (a Usage line always leads with the prog name)
            indent = len(line) - len(line.lstrip())
            spec, _, description = line.strip().partition("  ")
            entries[index] = (indent, " ".join(spec.replace(",", " ").split()), description.strip())
    width = max((len(spec) for _, spec, _ in entries.values()), default=0)
    out = [line.rstrip() for line in lines]
    for index, (indent, spec, description) in entries.items():
        out[index] = " " * indent + (f"{spec.ljust(width)}  {description}" if description else spec)
    return "\n".join(out) + ("\n" if doc.endswith("\n") else "")
