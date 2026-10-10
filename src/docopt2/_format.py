from __future__ import annotations

from typing import TYPE_CHECKING

from docopt2._core import Arguments, Source, docopt
from docopt2._errors import DocoptExit, DocoptLanguageError
from docopt2._generate import _usage_pattern
from docopt2._parser import (
    Argument,
    Command,
    Either,
    OneOrMore,
    Option,
    Optional,
    OptionsShortcut,
    Required,
    _usage_lines,
)

if TYPE_CHECKING:
    from collections.abc import Collection

    from docopt2._parser import Pattern


def _is_present(value: object) -> bool:
    """Whether a value puts a token on the argv: an off flag, a zero count or an empty list emit nothing."""
    return value is not None and value is not False and value != 0 and value != []


def _int_value(value: object) -> int | None:
    """The value read as a repetition count (a bare ``int``, never a ``bool`` flag)."""
    return value if type(value) is int else None


def _get(result: Arguments, name: str | None) -> object:
    """A leaf's value by its name, treating an unnamed leaf (``name is None``) as absent."""
    return None if name is None else result.get(name)


def _leaves_provided(node: Pattern, provided: Collection[str]) -> bool:
    """Whether any element under ``node`` carries a value (from argv, env or config)."""
    return any(leaf.name in provided for leaf in node.flat(Argument, Command, Option))


class _Emitted:
    """What one usage line emits: its tokens in usage order, and the positionals kept apart from the options."""

    def __init__(self) -> None:
        self.ordered: list[str] = []
        self.options: list[str] = []
        self.positionals: list[str] = []
        self.consumed: dict[str | None, int] = {}

    def option(self, tokens: list[str]) -> None:
        self.ordered += tokens
        self.options += tokens

    def positional(self, token: str) -> None:
        self.ordered.append(token)
        self.positionals.append(token)

    def behind_separator(self) -> list[str] | None:
        """The same tokens with every positional behind a ``--``, or None when no positional starts with a dash."""
        if not any(token.startswith("-") for token in self.positionals):
            return None
        return [*self.options, "--", *self.positionals]


def _emit_option(option: Option, result: Arguments, emitted: _Emitted) -> None:
    """Append an option in canonical long form (``--name=value``), or ``-x value`` when it has no long form
    (``-x=--`` for the one value that cannot stand as a token of its own)."""
    name = option.long or option.short or ""
    value = _get(result, option.name)
    if option.argcount:
        for item in value if isinstance(value, list) else [value]:
            # a short option reads its value from the next token, and a `--` there ends the options instead
            attached = name.startswith("--") or item == "--"
            emitted.option([f"{name}={item}"] if attached else [name, str(item)])
    else:
        emitted.option([name] * (_int_value(value) or 1))  # a repeatable flag with a count emits that many


def _multi(value: object) -> bool:
    """Whether a value carries more than one occurrence: a multi-element list, or a count above one."""
    return (isinstance(value, list) and len(value) > 1) or (type(value) is int and value > 1)


def _pick_branch(branches: list[Pattern], result: Arguments, provided: Collection[str]) -> Pattern | None:
    """The alternation branch the result took: its commands are set, it can hold any repeated value, and it
    covers the most provided leaves."""
    scored: list[tuple[int, int, int, Pattern]] = []
    for branch in branches:
        commands = branch.flat(Command)
        if commands and not any(_get(result, command.name) for command in commands):
            continue  # a command alternative was expected but none of this branch's commands is set
        names = {leaf.name for leaf in branch.flat(Argument, Command, Option)}
        overlap = len(names & set(provided))
        # a value with several occurrences needs a branch that repeats its name (a `...`), not a lone leaf
        repeated = {leaf.name for group in branch.flat(OneOrMore) for leaf in group.flat(Argument, Command)}
        multi = sum(1 for name in names if name in repeated and _multi(_get(result, name)))
        scored.append((len(commands), multi, overlap, branch))
    scored.sort(key=lambda entry: (entry[0], entry[1], entry[2]), reverse=True)
    return scored[0][3] if scored else None


def _positional_tokens(node: Pattern, result: Arguments) -> list[str]:
    """Every token a positional contributes, to be spread across its occurrences.

    A command contributes its name once per count; a positional argument its value, or each element of an
    accumulated list. Options are excluded - they float, so order relative to positionals does not matter.
    """
    value = result.get(node.name) if node.name is not None else None
    if isinstance(node, Command):
        return [str(node.name)] * (_int_value(value) or (1 if value else 0))
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)] if value is not None else []


def _emit_positional(node: Argument, result: Arguments, emitted: _Emitted) -> None:
    """Emit the next token of a positional (argument or command), advancing its cursor.

    A positional repeated across a line (``<name> <path> <name>``, ``cmd <x> cmd``) accumulates into one
    result value; emitting it whole at the first leaf would misorder it against the positionals between, so
    each leaf takes the next token in turn.
    """
    name = node.name
    if name is None:  # pragma: no cover - a positional leaf always carries a name; the guard only narrows the type
        return
    full = _positional_tokens(node, result)
    cursor = emitted.consumed.get(name, 0)
    if cursor < len(full):
        emitted.positional(full[cursor])
        emitted.consumed[name] = cursor + 1


def _emit_repeated(child: Pattern, result: Arguments, provided: Collection[str], emitted: _Emitted) -> None:
    """Emit a ``...`` repetition: walk the child once per still-unconsumed positional token under it.

    Repeating the walk (rather than dumping each leaf whole) keeps grouped repetitions like ``(<a> <b>)...``
    interleaved correctly; a repetition with no repeated positionals runs once.
    """
    counts = [
        len(_positional_tokens(leaf, result)) - emitted.consumed.get(leaf.name, 0)
        for leaf in child.flat(Argument, Command)
    ]
    for _ in range(max(1, max(counts, default=0))):
        _emit(child, result, provided, emitted)


def _emit(node: Pattern, result: Arguments, provided: Collection[str], emitted: _Emitted) -> None:
    """Walk the pattern tree, appending the tokens the result supplied (positionals in order, once each)."""
    if isinstance(node, Required):
        for child in node.children:
            _emit(child, result, provided, emitted)
    elif isinstance(node, Either):
        branch = _pick_branch(node.children, result, provided)
        if branch is not None:
            _emit(branch, result, provided, emitted)
    elif isinstance(node, OneOrMore):
        _emit_repeated(node.children[0], result, provided, emitted)
    elif isinstance(node, (Optional, OptionsShortcut)):
        for child in node.children:
            if _leaves_provided(child, provided):
                _emit(child, result, provided, emitted)
    elif isinstance(node, Argument):  # Command is an Argument subclass; both are positional
        _emit_positional(node, result, emitted)
    elif (
        isinstance(node, Option)
        and node.name is not None
        and node.name in provided
        and node.name not in emitted.consumed
    ):
        emitted.consumed[node.name] = 1  # stacked or duplicate leaves of one flag emit once, with the full count
        _emit_option(node, result, emitted)


def _round_trips(doc: str, tokens: list[str], result: Arguments) -> bool:
    """Whether ``tokens`` parse back to exactly ``result`` (a rejected argv is simply not a round-trip)."""
    try:
        return docopt(doc, tokens, help=False, complete=False) == result
    except (DocoptExit, DocoptLanguageError):
        return False


def _candidates(doc: str, result: Arguments, written: Collection[str]) -> list[list[str]]:
    """Every argv worth trying for the elements in ``written``: each usage line as it reads, then each one
    with its positionals behind a ``--``."""
    lines: list[_Emitted] = []
    for line in _usage_lines(_usage_pattern(doc)):
        emitted = _Emitted()
        _emit(line, result, written, emitted)
        lines.append(emitted)
    candidates = [emitted.ordered for emitted in lines]
    # tried only after every plain candidate, so an argv that formatted before still formats the same
    candidates += [separated for emitted in lines if (separated := emitted.behind_separator()) is not None]
    return candidates


def format_argv(result: Arguments, doc: str) -> list[str]:
    """Synthesize a canonical argv that [`docopt`][docopt2.docopt] parses back to ``result``.

    This is the inverse of parsing. Given an [`Arguments`][docopt2.Arguments] mapping returned by
    ``docopt(doc, ...)``, return an argv token list (no program name) that round-trips:
    ``docopt(doc, format_argv(result, doc), help=False, complete=False) == result``.

    The canonical form emits every element that *carries* a value, in usage order, with options in long
    ``--name=value`` form. That is what the user supplied, plus whatever ``[env:]`` or ``[config:]`` resolved.
    It is *a* valid argv, not necessarily the shortest or the one originally typed. A positional that would
    read back as an option (``-x``, ``--``) is written behind a ``--``, with the options in front of it.

    An env- or config-sourced value is emitted rather than skipped, so the argv reproduces the result on its
    own, without that environment. A persisted command that silently depended on an unrecorded variable would
    not reproduce the run. An off flag and a zero count are the exception: no token says them, so that part
    of the result is read from its source again.

    Two things are omitted: an element left at its ``[default: ...]``, and one whose value is absent (an off
    flag, a zero count). A source other than ``DEFAULT`` is not enough on its own, since an ``[env: V]`` flag
    read as off has source ``ENV`` and value ``False``, and emitting its name would parse back to ``True``.
    Where the omission does not parse back (the environment changed since the parse, or the mapping was built
    by hand and records no sources), the defaults are written out as well.

    The round trip is promised for one replay, the one the answer is checked with: ``help=False`` and
    every other setting at its default. So a result that carries ``--help`` formats, and its argv parses
    back only where ``--help`` is not acted on. A result that took another setting to produce
    (``options_first=True``, ``negative_numbers=True``) is formatted to parse back under the defaults.

    Args:
        result: An [`Arguments`][docopt2.Arguments] mapping returned by ``docopt(doc, ...)``.
        doc: The same usage message that produced ``result``.

    Returns:
        An argv token list, without the program name. Each candidate usage line is generated and then
        re-parsed to verify it round-trips, so the output is never a *wrong* argv, only a valid one.

    Raises:
        ValueError: No usage pattern reproduces ``result``. That means an inconsistent mapping,
            a degenerate grammar where one value is reachable through differently-shaped positions
            (``(<name> | <name> ...)``, ``(-a | -b)...``, ``[<name>] <path> <name>``), or a value that only a
            parser setting put there and no ``--`` can protect: a ``-5`` read as a positional by
            ``negative_numbers=True`` in front of a ``--`` the usage itself declares.
    """
    carried = {name for name in result if _is_present(result[name])}
    provided = {name for name in carried if result.source(name) is not Source.DEFAULT}
    for written in [provided] if provided == carried else [provided, carried]:
        for tokens in _candidates(doc, result, written):  # generate-and-verify: the first that parses back
            if _round_trips(doc, tokens, result):
                return tokens
    raise ValueError("cannot format: the result matches no usage pattern in the doc")
