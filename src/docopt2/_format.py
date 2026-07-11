from __future__ import annotations

from typing import TYPE_CHECKING

from docopt2._core import Arguments, docopt
from docopt2._errors import DocoptExit, DocoptLanguageError
from docopt2._generate import _usage_pattern
from docopt2._parser import Argument, Command, Either, OneOrMore, Option, Optional, OptionsShortcut, Required

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


def _pick_branch(branches: list[Pattern], result: Arguments, provided: Collection[str]) -> Pattern | None:
    """The alternation branch the result took: its command is set and it covers the most provided leaves."""
    scored: list[tuple[int, int, Pattern]] = []
    for branch in branches:
        commands = branch.flat(Command)
        if commands and not any(_get(result, command.name) for command in commands):
            continue  # a command alternative was expected but none of this branch's commands is set
        overlap = len({leaf.name for leaf in branch.flat(Argument, Command, Option)} & set(provided))
        scored.append((len(commands), overlap, branch))
    scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return scored[0][2] if scored else None


def _emit(node: Pattern, result: Arguments, provided: Collection[str], tokens: list[str], done: set[str]) -> None:
    """Walk the pattern tree, appending the tokens the result supplied (each element at most once)."""
    if isinstance(node, Required):
        for child in node.children:
            _emit(child, result, provided, tokens, done)
    elif isinstance(node, Either):
        branch = _pick_branch(node.children, result, provided)
        if branch is not None:
            _emit(branch, result, provided, tokens, done)
    elif isinstance(node, OneOrMore):
        _emit(node.children[0], result, provided, tokens, done)  # list/count leaves expand themselves
    elif isinstance(node, (Optional, OptionsShortcut)):
        for child in node.children:
            if _leaves_provided(child, provided):
                _emit(child, result, provided, tokens, done)
    elif isinstance(node, Command):
        value = _get(result, node.name)
        if value and node.name is not None and node.name not in done:
            done.add(node.name)
            tokens.extend([node.name] * (_int_value(value) or 1))
    elif isinstance(node, Argument):
        if node.name is not None and node.name not in done:
            done.add(node.name)
            value = result.get(node.name)
            if isinstance(value, list):
                tokens.extend(str(item) for item in value)
            elif value is not None:
                tokens.append(str(value))
    elif isinstance(node, Option) and node.name is not None and node.name in provided and node.name not in done:
        done.add(node.name)  # stacked or duplicate leaves of one flag emit once, with the full count
        _emit_option(node, result, tokens)


def _usage_lines(top: Pattern) -> list[Pattern]:
    """The alternative usage lines: the children of the top ``Required(Either(...))``, else the pattern itself."""
    if isinstance(top, Required) and top.children and isinstance(top.children[0], Either):
        return top.children[0].children
    return [top]


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

    Each candidate usage line is generated and then re-parsed to verify it round-trips, so correctness is a
    guarantee rather than a heuristic. Raises :class:`ValueError` if no usage pattern reproduces ``result`` -
    which a genuine ``docopt`` result never triggers, only a hand-built or inconsistent mapping.
    """
    provided = result.provided
    candidates: list[list[str]] = []
    for line in _usage_lines(_usage_pattern(doc)):
        tokens: list[str] = []
        _emit(line, result, provided, tokens, set())
        candidates.append(tokens)
    for tokens in candidates:  # generate-and-verify: return the first line whose argv parses back to result
        if _round_trips(doc, tokens, result):
            return tokens
    raise ValueError("cannot format: the result matches no usage pattern in the doc")
