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


def _spellings(doc: str) -> set[str]:
    """Every option spelling ``doc`` accepts, short AND long.

    An option's identity here is what a caller can type, not its canonical name: ``Option.name`` is
    ``long or short``, so adding ``--verbose`` to a lone ``-v`` renames the option and would read as ``-v``
    having been deleted - a break reported for a change that breaks nobody.
    """
    return {
        name
        for leaf in _usage_pattern(doc).flat(Option)
        for name in (getattr(leaf, "short", None), getattr(leaf, "long", None))
        if name is not None
    }


def check_compat(old_doc: str, new_doc: str, *, samples: int = 300) -> list[str]:
    """Report backward-incompatible changes from ``old_doc`` to ``new_doc``, most reliable part first.

    Every entry is a *definite* break - an invocation the old usage accepts that the new one rejects: a
    removed option, a removed command, or a concrete argument vector the new grammar no longer accepts
    (found by sampling the old grammar's accepted set and replaying it against the new).

    An empty list means **no break was found**, not a proof of compatibility. The accepted set is infinite
    and only ``samples`` invocations are checked, so read it like a passing test ("no breakage detected"),
    never as a guarantee. It never claims "compatible", it only surfaces breaks it can prove.

    Args:
        old_doc: The usage message as it stands today.
        new_doc: The usage message as it would be after the change.
        samples: How many invocations to draw from the old grammar when hunting for counterexamples.
            More samples widen the search, and never turn an empty result into a guarantee.
    """
    old_examples = generate_examples(old_doc, count=samples, seed=0)
    removed_options = _spellings(old_doc) - _spellings(new_doc)
    # A command literal absent from new is only a break if it actually rejects something. `(add|rm) <p>`
    # generalized to `<cmd> <p>` drops the `add`/`rm` literals, yet new accepts every old invocation (they
    # match `<cmd>`). Report a command only when a sampled old invocation that used it is rejected by new.
    gone = _usable(old_doc, Command) - _usable(new_doc, Command)
    removed_commands = {name for name in gone if _command_removal_breaks(new_doc, name, old_examples)}
    breaks = [f"option `{name}` removed" for name in sorted(removed_options)]
    breaks += [f"command `{name}` removed" for name in sorted(removed_commands)]
    removed = removed_options | removed_commands
    seen_shapes: set[tuple[str, ...]] = set()
    examples: list[str] = []
    for argv in old_examples:
        shape = tuple(re.sub(r"v\d+", "<val>", token) for token in argv)  # collapse placeholder values
        if shape in seen_shapes or _explained(argv, removed):  # one example per shape; skip structural repeats
            seen_shapes.add(shape)
            continue
        seen_shapes.add(shape)
        if _rejects(new_doc, argv):
            examples.append(f"`{' '.join(argv)}` no longer accepted")
            if len(examples) >= _MAX_EXAMPLES:
                break
    return breaks + examples


def _rejects(doc: str, argv: list[str]) -> bool:
    """Whether ``doc`` refuses ``argv`` (the shape a break takes: old accepted it, new does not)."""
    try:
        docopt(doc, argv, help=False, complete=False)
    except (DocoptExit, DocoptLanguageError):
        return True
    return False


def _command_removal_breaks(new_doc: str, name: str, old_examples: list[list[str]]) -> bool:
    """Whether dropping the command literal ``name`` rejects some invocation the old grammar accepted.

    False when new absorbed the command into a positional (it still accepts those invocations); True when
    the command is genuinely gone. ``generate_examples`` emits positional values as ``v1``, ``v2``... and
    a command only by its name, so a command literal appears in a sampled argv iff it matched as that
    command - a plain ``name in argv`` is enough. Bounded by the sampled examples, like the rest.
    """
    return any(name in argv and _rejects(new_doc, argv) for argv in old_examples)


def _explained(argv: list[str], removed: set[str]) -> bool:
    """Whether the argv uses a removed option or command - so a named structural break already covers it."""
    return any(token.split("=", 1)[0] in removed or token in removed for token in argv)
