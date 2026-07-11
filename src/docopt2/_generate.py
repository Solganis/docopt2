from __future__ import annotations

import itertools
import random
from typing import TYPE_CHECKING

from docopt2._parser import (
    Argument,
    Command,
    Either,
    OneOrMore,
    Option,
    Optional,
    OptionsShortcut,
    Pattern,
    Required,
    expand_options_shortcut,
    formal_usage,
    parse_defaults,
    parse_pattern,
    single_usage_section,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Protocol

    class _Chooser(Protocol):
        """The random decisions the pattern walk makes: pick a branch, a repeat count, a coin flip.

        Typing-only. Abstracting the choices lets the same walk run off a seeded ``random.Random``
        (:class:`_RandomChooser`) or off a Hypothesis draw (in :mod:`docopt2.hypothesis`), with no
        second copy of the tree walk.
        """

        def choice(self, options: list[Pattern]) -> Pattern: ...
        def integer(self, low: int, high: int) -> int: ...
        def boolean(self) -> bool: ...


class _RandomChooser:
    """Drives the walk from a seeded ``random.Random``; used by :func:`generate_examples`."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def choice(self, options: list[Pattern]) -> Pattern:
        return self._rng.choice(options)

    def integer(self, low: int, high: int) -> int:
        return self._rng.randint(low, high)

    def boolean(self) -> bool:
        return self._rng.random() < 0.5


def _usage_pattern(doc: str) -> Pattern:
    """Build the usage-pattern tree, the same one :func:`docopt` matches against."""
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_usage(single_usage_section(doc)), options)
    expand_options_shortcut(pattern, options)
    return pattern


def _sample(node: Pattern, chooser: _Chooser, counter: Iterator[int]) -> list[str]:
    """Walk the pattern into one argv the usage accepts.

    A required sequence emits all children; an alternation picks one branch; a repetition repeats once
    or twice; an optional group is taken with even odds; a positional gets a synthetic value; a command
    emits its literal; a valued option emits a synthetic value. Every choice comes from ``chooser``, so
    the same walk serves both the seeded generator and the Hypothesis strategy.
    """
    if isinstance(node, Required):
        return [token for child in node.children for token in _sample(child, chooser, counter)]
    if isinstance(node, Either):
        return _sample(chooser.choice(node.children), chooser, counter)
    if isinstance(node, OneOrMore):
        return [token for _ in range(chooser.integer(1, 2)) for token in _sample(node.children[0], chooser, counter)]
    if isinstance(node, (Optional, OptionsShortcut)):
        if chooser.boolean():
            return [token for child in node.children for token in _sample(child, chooser, counter)]
        return []
    if isinstance(node, Command):
        return [str(node.name)]
    if isinstance(node, Argument):
        return [f"v{next(counter)}"]
    if isinstance(node, Option):
        name = str(node.long or node.short)
        if node.argcount:
            return [f"{name}=v{next(counter)}"] if name.startswith("--") else [name, f"v{next(counter)}"]
        return [name]
    raise TypeError(f"unexpected pattern node {type(node).__name__}")  # pragma: no cover - closed node hierarchy


def _unknown_option(doc: str) -> str:
    """A long option the doc does not define, so appending it turns an accepted argv into a rejected one."""
    defined = {option.long for option in parse_defaults(doc) if option.long is not None}
    name = "--unknown"
    while name in defined:
        name += "-x"
    return name


def generate_examples(doc: str, *, count: int = 10, valid: bool = True, seed: int | None = None) -> list[list[str]]:
    """Generate example argument vectors derived from the usage message.

    Each returned item is an argv token list (no program name). A ``valid`` example is one ``docopt``
    accepts; an invalid one (``valid=False``) is a valid argv with an unknown option appended, which
    ``docopt`` rejects. Duplicates are dropped, so a small grammar may yield fewer than ``count``.
    ``seed`` makes the output reproducible. Everything is derived from the ``Usage:`` and ``Options:``
    blocks, so the examples cannot drift from what :func:`docopt` parses.
    """
    single_usage_section(doc)  # fail loudly here on a malformed usage, not mid-walk
    pattern = _usage_pattern(doc)
    chooser = _RandomChooser(random.Random(seed))
    counter = itertools.count(1)
    unknown = _unknown_option(doc)
    seen: set[tuple[str, ...]] = set()
    examples: list[list[str]] = []
    for _ in range(max(count, 0) * 20):
        if len(examples) >= count:
            break
        argv = _sample(pattern, chooser, counter)
        if not valid:
            argv.append(unknown)
        if tuple(argv) not in seen:
            seen.add(tuple(argv))
            examples.append(argv)
    return examples
