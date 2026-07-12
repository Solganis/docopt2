from __future__ import annotations

from typing import TYPE_CHECKING

from docopt2._core import Arguments, docopt
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


def _int_value(value: object) -> int | None:
    """The value read as a repetition count (a bare ``int``, never a ``bool`` flag)."""
    return value if type(value) is int else None


def _get(result: Arguments, name: str | None) -> object:
    """A leaf's value by its name, treating an unnamed leaf (``name is None``) as absent."""
    return None if name is None else result.get(name)


def _leaves_provided(node: Pattern, provided: Collection[str]) -> bool:
    """Whether any element under ``node`` was supplied on the command line."""
    return any(leaf.name in provided for leaf in node.flat(Argument, Command, Option))


def _emit_option(option: Option, result: Arguments, tokens: list[str]) -> None:
    """Append an option in canonical long form (``--name=value``), or ``-x value`` when it has no long form."""
    name = option.long or option.short or ""
    value = _get(result, option.name)
    if option.argcount:
        for item in value if isinstance(value, list) else [value]:
            tokens.extend([f"{name}={item}"] if name.startswith("--") else [name, str(item)])
    else:
        tokens.extend([name] * (_int_value(value) or 1))  # a repeatable flag with a count emits that many


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


def _emit_positional(node: Argument, result: Arguments, tokens: list[str], consumed: dict[str | None, int]) -> None:
    """Emit the next token of a positional (argument or command), advancing its cursor.

    A positional repeated across a line (``<name> <path> <name>``, ``cmd <x> cmd``) accumulates into one
    result value; emitting it whole at the first leaf would misorder it against the positionals between, so
    each leaf takes the next token in turn.
    """
    name = node.name
    if name is None:  # pragma: no cover - a positional leaf always carries a name; the guard only narrows the type
        return
    full = _positional_tokens(node, result)
    cursor = consumed.get(name, 0)
    if cursor < len(full):
        tokens.append(full[cursor])
        consumed[name] = cursor + 1


def _emit_repeated(
    child: Pattern, result: Arguments, provided: Collection[str], tokens: list[str], consumed: dict[str | None, int]
) -> None:
    """Emit a ``...`` repetition: walk the child once per still-unconsumed positional token under it.

    Repeating the walk (rather than dumping each leaf whole) keeps grouped repetitions like ``(<a> <b>)...``
    interleaved correctly; a repetition with no repeated positionals runs once.
    """
    counts = [
        len(_positional_tokens(leaf, result)) - consumed.get(leaf.name, 0) for leaf in child.flat(Argument, Command)
    ]
    for _ in range(max(1, max(counts, default=0))):
        _emit(child, result, provided, tokens, consumed)


def _emit(
    node: Pattern, result: Arguments, provided: Collection[str], tokens: list[str], consumed: dict[str | None, int]
) -> None:
    """Walk the pattern tree, appending the tokens the result supplied (positionals in order, once each)."""
    if isinstance(node, Required):
        for child in node.children:
            _emit(child, result, provided, tokens, consumed)
    elif isinstance(node, Either):
        branch = _pick_branch(node.children, result, provided)
        if branch is not None:
            _emit(branch, result, provided, tokens, consumed)
    elif isinstance(node, OneOrMore):
        _emit_repeated(node.children[0], result, provided, tokens, consumed)
    elif isinstance(node, (Optional, OptionsShortcut)):
        for child in node.children:
            if _leaves_provided(child, provided):
                _emit(child, result, provided, tokens, consumed)
    elif isinstance(node, Argument):  # Command is an Argument subclass; both are positional
        _emit_positional(node, result, tokens, consumed)
    elif isinstance(node, Option) and node.name is not None and node.name in provided and node.name not in consumed:
        consumed[node.name] = 1  # stacked or duplicate leaves of one flag emit once, with the full count
        _emit_option(node, result, tokens)


def _round_trips(doc: str, tokens: list[str], result: Arguments) -> bool:
    """Whether ``tokens`` parse back to exactly ``result`` (a rejected argv is simply not a round-trip)."""
    try:
        return docopt(doc, tokens, help=False, complete=False) == result
    except (DocoptExit, DocoptLanguageError):
        return False


def format_argv(result: Arguments, doc: str) -> list[str]:
    """Synthesize a canonical argument vector that :func:`docopt` parses back to ``result`` - the inverse of parsing.

    Given an :class:`Arguments` mapping returned by ``docopt(doc, ...)``, return an argv token list (no program
    name) that round-trips: ``docopt(doc, format_argv(result, doc)) == result``. The canonical form emits exactly
    the elements the user supplied (``result.provided``), in usage order, options in long ``--name=value`` form.
    It is *a* valid argv, not necessarily the shortest or the one originally typed.

    Each candidate usage line is generated and then re-parsed to verify it round-trips, so the output is never
    a *wrong* argv - only ever a valid one or none. Raises :class:`ValueError` when no usage pattern reproduces
    ``result``: every result from a conventional grammar round-trips, so this fires only on a hand-built or
    inconsistent mapping, or a degenerate grammar where one value is reachable through differently-shaped
    positions (``(<name> | <name> ...)``, ``(-a | -b)...``, ``[<name>] <path> <name>``) - constructs that do
    not arise in practice.
    """
    provided = result.provided
    candidates: list[list[str]] = []
    for line in _usage_lines(_usage_pattern(doc)):
        tokens: list[str] = []
        _emit(line, result, provided, tokens, {})
        candidates.append(tokens)
    for tokens in candidates:  # generate-and-verify: return the first line whose argv parses back to result
        if _round_trips(doc, tokens, result):
            return tokens
    raise ValueError("cannot format: the result matches no usage pattern in the doc")
