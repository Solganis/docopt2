from __future__ import annotations

import re

from docopt2._core import docopt
from docopt2._errors import DocoptExit, DocoptLanguageError
from docopt2._generate import _usage_pattern, generate_examples
from docopt2._parser import Command, Option, Pattern

_MAX_EXAMPLES = 5  # distinct counterexample shapes to report; the report stays scannable, not a wall of argvs


def _usable(doc: str, kind: type[Pattern]) -> set[str]:
    """The names of the leaves of ``kind`` actually usable in ``doc`` (its ``[options]`` shortcut expanded)."""
    return {leaf.name for leaf in _usage_pattern(doc).flat(kind) if leaf.name is not None}


def check_compat(old_doc: str, new_doc: str, *, samples: int = 300) -> list[str]:
    """Report backward-incompatible changes from ``old_doc`` to ``new_doc``, most reliable part first.

    Every entry is a *definite* break - an invocation the old usage accepts that the new one rejects: a
    removed option or command (named, structural), or a concrete argument vector the new grammar no longer
    accepts (found by sampling the old grammar's accepted set and replaying it against the new).

    An empty list means **no break was found**, not a proof of compatibility: the accepted set is infinite
    and only ``samples`` invocations are checked, so read it like a passing test ("no breakage detected"),
    never as a guarantee. It never claims "compatible" - it only surfaces breaks it can prove.
    """
    removed_options = _usable(old_doc, Option) - _usable(new_doc, Option)
    removed_commands = _usable(old_doc, Command) - _usable(new_doc, Command)
    breaks = [f"option `{name}` removed" for name in sorted(removed_options)]
    breaks += [f"command `{name}` removed" for name in sorted(removed_commands)]
    removed = removed_options | removed_commands
    seen_shapes: set[tuple[str, ...]] = set()
    examples: list[str] = []
    for argv in generate_examples(old_doc, count=samples, seed=0):
        shape = tuple(re.sub(r"v\d+", "<val>", token) for token in argv)  # collapse placeholder values
        if shape in seen_shapes or _explained(argv, removed):  # one example per shape; skip structural repeats
            seen_shapes.add(shape)
            continue
        seen_shapes.add(shape)
        try:
            docopt(new_doc, argv, help=False, complete=False)
        except (DocoptExit, DocoptLanguageError):
            examples.append(f"`{' '.join(argv)}` no longer accepted")
            if len(examples) >= _MAX_EXAMPLES:
                break
    return breaks + examples


def _explained(argv: list[str], removed: set[str]) -> bool:
    """Whether the argv uses a removed option or command - so a named structural break already covers it."""
    return any(token.split("=", 1)[0] in removed or token in removed for token in argv)
