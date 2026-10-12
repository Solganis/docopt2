from __future__ import annotations

import itertools
import os
import re
from typing import TYPE_CHECKING, cast

from docopt2._core import COMPLETION_REQUEST_ENV
from docopt2._errors import DocoptExit, DocoptLanguageError
from docopt2._parser import (
    MATCH_LIMIT,
    Argument,
    BranchPattern,
    Command,
    Either,
    LeafPattern,
    MatchBudget,
    OneOrMore,
    Option,
    Optional,
    OptionsShortcut,
    Pattern,
    Required,
    Tokens,
    _MatchBudgetExceededError,
    _option_chunks,
    _usage_lines,
    expand_options_shortcut,
    formal_usage,
    line_binders,
    most_specific,
    parse_argument_defaults,
    parse_argv,
    parse_defaults,
    parse_pattern,
    single_usage_section,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator, Sequence
    from typing import Any, TypeAlias

    from docopt2._parser import SingleMatch

    # the command path and the schema of each handler of a table, in the order they were registered
    Table: TypeAlias = Sequence[tuple[tuple[str, ...], type[Any] | None]]
    Takes: TypeAlias = Callable[[str, object], bool]  # whether the field of a usage element takes a text
    # by the key of a usage element: the values to offer for it, `Takes`, whether its field is typed as a `Path`
    Fields: TypeAlias = tuple[Callable[[str], list[str]], Takes | None, Callable[[str], bool]]

_A_VALUE = "\0"  # stands for a word not typed yet: the argument an option waits for, a positional further on
_PATHS_FINISHED = 128  # the paths with a positional next that one Tab press finishes: a usual line has a few
_THE_NEXT = "\1"  # stands for the word a Tab press asks for, in a line finished to see which element reads it

# Environment protocol shared with the generated shell scripts: when completion fires, the script
# sets these variables and re-invokes the program, whose docopt() call answers with the candidates.
_TRIGGER_ENV = COMPLETION_REQUEST_ENV
_WORDS_ENV = "_DOCOPT2_WORDS"


# --- the resolver: which tokens may legally come next -------------------------------------------


class _Steps:
    """How many more nodes a walk may visit.

    A cap on what a walk yields bounds no time where it yields little: before a word nothing takes, twenty
    flags that were typed are each taken or passed by, for 2.6 s with no budget and no path at the end.
    """

    def __init__(self, left: int | None = None, cut: list[bool] | None = None) -> None:
        self.left = MATCH_LIMIT if left is None else left
        self._cut = [False] if cut is None else cut  # one for a walk and every share of it

    @property
    def cut(self) -> bool:
        """Whether the walk, or a share of it, ran out: there may be paths it did not see."""
        return self._cut[0]

    def spend(self) -> bool:
        self.left -= 1
        if self.left < 0:
            self._cut[0] = True
        return self.left >= 0

    def share(self, among: int) -> _Steps:
        """A budget of its own for one of ``among`` alternatives still to walk: an equal part of what is left."""
        return _Steps(max(self.left, 0) // among, self._cut)


def _frontier(
    node: Pattern, left: list[Pattern], *, block: bool, steps: _Steps | None = None
) -> Iterator[tuple[list[Pattern], tuple[Pattern, ...], bool]]:
    """Yield ``(remaining, frontier, blocks)`` per partial-consumption path; a token sequence is a
    valid prefix iff some path leaves ``remaining == []``.

    ``frontier`` is the leaves the path left unfilled, in the order it meets them: each could match a later
    token, and its first command or positional is the one the path fills next. An option floats (offerable,
    and the path proceeds past it, non-blocking); an unfilled positional/command sets ``blocks`` to ``block``.
    So a walk that blocks stops each path at what comes next, and one that does not floats past it to every
    option the path can still take. A present positional that fails is dead.

    ``steps`` is the budget of the whole walk: a walk that has spent it ends, with the paths it found so far.
    """
    steps = steps or _Steps()
    if not steps.spend():
        return
    if isinstance(node, LeafPattern):
        position, matched = node.single_match(left)
        if matched is not None and position is not None:
            yield left[:position] + left[position + 1 :], (), False  # already typed; consume it
        elif isinstance(node, Option):
            yield left, (node,), False  # floats: offerable next, sequence proceeds (deferred)
        elif not any(type(leaf) is Argument for leaf in left):
            yield left, (node,), block  # unfilled positional/command (only options, if any, remain)
        return
    if isinstance(node, Either):
        # each alternative walks on a share: one that forks without end spent the whole budget, and no other was offered
        for position, child in enumerate(node.children):
            part = steps.share(len(node.children) - position)
            granted = part.left
            yield from _frontier(child, left, block=block, steps=part)
            steps.left -= granted - max(part.left, 0)
        return
    if isinstance(node, OneOrMore):
        idle: list[tuple[Pattern, ...]] = []  # what each round that took no word left unfilled
        for remaining, frontier, blocks in _frontier(node.children[0], left, block=block, steps=steps):
            yield remaining, frontier, blocks
            if len(remaining) == len(left):
                idle.append(frontier)
            elif not blocks:
                # a round that took a word may be followed by another: what it left unfilled does not stand in the way
                later = _frontier(node, remaining, block=block, steps=steps)
                for later_remaining, later_frontier, later_blocks in later:
                    yield later_remaining, frontier + later_frontier, later_blocks
        if not block:
            # a round with a positional of a schema is walked twice too: a value may show only on a line of two rounds
            twice = {_shape(first): first for first in idle if any(isinstance(leaf, _Typed) for leaf in first)}
            again = {_shape(second): second for second in idle if second} if twice else {}
            for first, second in itertools.product(twice.values(), again.values()):
                yield left, first + second, False
        return
    children = node.children if isinstance(node, (Optional, OptionsShortcut)) else cast("Required", node).children
    optional = isinstance(node, (Optional, OptionsShortcut))
    yield from _frontier_seq(children, left, optional=optional, block=block, steps=steps)


def _frontier_seq(
    children: list[Pattern], left: list[Pattern], *, optional: bool, block: bool, steps: _Steps
) -> Iterator[tuple[list[Pattern], tuple[Pattern, ...], bool]]:
    if not children:
        yield left, (), False
        return
    head, rest = children[0], children[1:]
    floated = False
    for remaining, frontier, blocks in _frontier(head, left, block=block, steps=steps):
        if blocks:  # an unfilled required positional; stop, do not advance past it
            yield remaining, frontier, True
            continue
        if len(remaining) == len(left) and all(isinstance(leaf, Option) for leaf in frontier):
            floated = True  # head took nothing and put only options ahead (an option alone always does)
        for tail_remaining, tail_frontier, tail_blocks in _frontier_seq(  # advance, carrying its frontier
            rest, remaining, optional=optional, block=block, steps=steps
        ):
            if not steps.spend():  # a path handed up costs a step at each level it passes: long paths are not free
                return
            yield tail_remaining, frontier + tail_frontier, tail_blocks
    # An optional child may be skipped. The skip is pruned where head floated: the take-branch holds the same
    # paths with head's options on top. `floated` leaves out a head that puts a command or a positional ahead
    # (`[go] <env>`). Unpruned, `[options]` over 25 flags forked into 2**25 paths and a Tab took over a second.
    if optional and not floated and steps.left >= 0:
        yield from _frontier_seq(rest, left, optional=optional, block=block, steps=steps)


class _Typed(Argument):
    """A positional read by its schema field. A token the field does not take is none it can be given, so a path
    that would hand it one is dead, as a path that hands a command another word is."""

    def __init__(self, name: str | None, takes: Takes) -> None:
        super().__init__(name)
        self._takes = takes

    def single_match(self, left: list[Pattern]) -> SingleMatch:
        found = super().single_match(left)
        given = found[1]
        return found if given is not None and self._takes(str(self.name), given.value) else (None, None)


def _typed(node: Pattern, takes: Takes) -> Pattern:
    """The tree with a ``_Typed`` in the place of every positional. Its other leaves are those of ``node``."""
    if type(node) is Argument:
        return _Typed(node.name, takes)
    if not isinstance(node, BranchPattern):
        return node
    return type(node)(*(_typed(child, takes) for child in node.children))


def _is_option(leaf: Pattern) -> bool:
    return isinstance(leaf, Option)


def _shape(unfilled: tuple[Pattern, ...]) -> tuple[str | None, ...]:
    """What a line holds for the leaves a path left unfilled: the name of an option or a command, and for a
    positional any word."""
    return tuple(leaf.name if isinstance(leaf, Option) or type(leaf) is Command else None for leaf in unfilled)


def _finished(typed: list[Pattern], unfilled: tuple[Pattern, ...]) -> list[Pattern]:
    """A whole line that a path of the walk takes: the leaves typed, then each that the path left unfilled.

    The first positional of those stands as `_THE_NEXT`, each later one and each option's argument as `_A_VALUE`.
    """
    line = [leaf for leaf in typed if not (type(leaf) is Argument and leaf.value == "--")]
    word = _THE_NEXT
    for leaf in unfilled:
        if isinstance(leaf, Option):
            line.append(Option(leaf.short, leaf.long, leaf.argcount, _A_VALUE if leaf.argcount else True))
        elif type(leaf) is Command:
            line.append(Argument(None, leaf.name))
        else:
            line.append(Argument(None, word))
            word = _A_VALUE
    return line


def _texts(leaf: Pattern) -> list[Any]:
    """What a leaf of a reading holds, one by one: the texts of a repeated element, or its one value."""
    return leaf.value if isinstance(leaf.value, list) else [leaf.value]


def _read_line(
    pattern: Pattern,
    line: list[Pattern],
    bound_by: Callable[[list[Pattern]], Fields | None],
    commands: Collection[str | None],
) -> tuple[list[Pattern], Fields] | None:
    """The leaves that ``docopt()`` takes ``line`` as, with the fields that bind them: its first match that
    leaves no leaf over, on the pattern as ``docopt()`` fixes it.

    None where there is no such match, where nothing binds it, or where a field refuses what the line gives it:
    a word, a flag, a count, the list of a repeated element. A list that holds a stand-in is asked about text
    by text. What the line leaves out, an element that is absent or a default, is not asked about.

    None too where a stand-in for a later word stands for an element whose every value is one of ``commands``:
    the stand-in is no command, and any word that element takes may be read as one.
    """
    try:
        outcomes = itertools.islice(pattern.matches(line, []), MATCH_LIMIT + 1)
        taken = next((leaves for left, leaves in outcomes if left == []), None)
    except _MatchBudgetExceededError:
        return None
    bound = None if taken is None else bound_by(taken)
    if taken is None or bound is None:
        return None
    values_for, takes, _is_path = bound
    for leaf in taken:
        name, texts = str(leaf.name), _texts(leaf)
        given = [text for text in texts if text not in (_A_VALUE, _THE_NEXT)]
        whole = [leaf.value] if len(given) == len(texts) else given
        if takes is not None and not all(takes(name, value) for value in whole):
            return None
        closed = values_for(name) if _A_VALUE in texts and not isinstance(leaf, Option) else []
        if closed and all(value in commands for value in closed):
            return None
    return taken, bound


def _next_word(
    pattern: Pattern,
    line: list[Pattern],
    bound_by: Callable[[list[Pattern]], Fields | None],
    commands: Collection[str | None],
) -> tuple[list[str], bool]:
    """The values that may stand as the `_THE_NEXT` of ``line``, and whether a file name may: those of the
    element that the reading of the line gives the word to. There are none where the line has no reading.

    A value that is also one of ``commands`` may be read as that command, and the words before it by another
    usage line. It is kept where the line still reads with the value itself in the place of the stand-in.
    """
    read = _read_line(pattern, line, bound_by, commands)
    if read is None:
        return [], False
    taken, (values_for, _takes, is_path) = read
    reader = next(str(leaf.name) for leaf in taken if _THE_NEXT in _texts(leaf))
    values = []
    for value in values_for(reader):
        with_it = [Argument(None, value) if leaf.value == _THE_NEXT else leaf for leaf in line]
        if value not in commands or _read_line(pattern, with_it, bound_by, commands) is not None:
            values.append(value)
    return values, is_path(reader)


def _next_values(
    pattern: Pattern,
    typed: list[Pattern],
    paths: list[tuple[Pattern, ...]],
    bound_by: Callable[[list[Pattern]], Fields | None],
) -> tuple[set[str], bool]:
    """The values that may follow ``typed`` as the next positional, and whether a file name may: what
    ``_next_word`` says of each line that the ``paths`` are finished into.

    A path is finished twice, with the options it left unfilled and without them. The walk does not tell an
    option that may be left out from one that may not, and a line that holds them all can be read by a usage
    line that requires one of them.
    """
    values: set[str] = set()
    free = False
    finished: set[tuple[str | None, ...]] = set()  # paths that differ in how they read the typed words end alike
    commands = {leaf.name for leaf in pattern.flat(Command)}
    if paths:
        pattern.fix()  # as docopt() does before it matches: a repeated element then holds its list, or its count
    with MatchBudget(MATCH_LIMIT):  # the lines share what one parse may cost
        for unfilled in paths:
            for kept in (unfilled, tuple(itertools.filterfalse(_is_option, unfilled))):
                shape = _shape(kept)
                if shape not in finished:
                    finished.add(shape)
                    offered, file = _next_word(pattern, _finished(typed, kept), bound_by, commands)
                    values.update(offered)
                    free = free or file
    return values, free


def _bindable(leaves: list[Pattern], takes: Takes) -> bool:
    """Whether every option of ``leaves`` that was given a value was given one its field takes."""
    given = [leaf for leaf in leaves if isinstance(leaf, Option) and isinstance(leaf.value, str)]
    return all(takes(str(leaf.name), leaf.value) for leaf in given)


def _taking_all(pattern: Pattern, leaves: list[Pattern], steps: _Steps | None = None) -> Iterator[tuple[Pattern, ...]]:
    """The frontier of each path on which the usage takes all of ``leaves`` as a prefix, positionals not blocking.

    The `--` separator is left out: read as a positional nothing matches, it would kill every path.
    """
    typed = [leaf for leaf in leaves if not (type(leaf) is Argument and leaf.value == "--")]
    paths = _frontier(pattern, typed, block=False, steps=steps)
    return (frontier for remaining, frontier, _blocks in paths if remaining == [])


def _commands_in_order(pattern: Pattern, leaves: list[Pattern]) -> set[str]:
    """The commands that the typed positionals of ``leaves`` have next, by a walk that stops each path at the
    command or positional it meets unfilled.

    The options are left out, since one typed may belong behind the leaf that a path stops at. So a command
    here is one that some line has next, whatever options that line holds.
    """
    positionals: list[Pattern] = [leaf for leaf in leaves if type(leaf) is Argument and leaf.value != "--"]
    paths = _frontier(pattern, positionals, block=True)
    ahead = [frontier for remaining, frontier, _blocks in paths if remaining == []]
    return {str(leaf.name) for frontier in ahead for leaf in frontier if type(leaf) is Command}


def _read(doc: str) -> tuple[list[Option], Pattern]:
    """The options of ``doc`` and its usage pattern, with every ``[options]`` filled in."""
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_usage(single_usage_section(doc)), options)
    expand_options_shortcut(pattern, options)
    return options, pattern


def _resolve(
    options: list[Option],
    pattern: Pattern,
    typed: list[str],
    values_for: Callable[[str], list[str]],
    takes: Takes | None,
    is_path: Callable[[str], bool],
    bound_by: Callable[[list[Pattern]], Fields | None] | None = None,
) -> tuple[list[str], bool]:
    """What may legally follow the already-typed ``typed`` tokens: commands, options, and the values of an element.

    With ``takes``, the fields of a schema read the tokens too: a prefix that holds a value its field does not
    take has nothing to follow it, since no argv that starts that way can be bound.

    A value follows as the next positional only where ``docopt()`` itself reads it so. A path of the walk says
    no more than that some reading gives the next word to an element, and the parser takes the first reading
    that fits. So each path is finished into a whole line, and the values are those of the element that the
    parser gives the next word of that line to. ``bound_by`` gives the fields that bind the leaves of such a
    reading: the three given here where it is left out, and None where nothing binds them.

    The second item says whether a file name may come next: the argument of an option that waits for one, or
    the next positional, where its field is typed as a ``Path``.
    """
    walked = pattern if takes is None else _typed(pattern, takes)
    try:
        base = parse_argv(Tokens(list(typed)), list(options))
    except DocoptExit:
        # refused as it stands: one more token makes it read only where the last option waited for its argument
        given = parse_argv(Tokens([*typed, _A_VALUE]), list(options))
        fits = any(True for _frontier_of_a_path in _taking_all(walked, given))  # the usage takes it there too
        fits = fits and (takes is None or _bindable(given[:-1], takes))
        return (sorted(values_for(str(given[-1].name))) if fits else []), fits and is_path(str(given[-1].name))
    if takes is not None and not _bindable(base, takes):
        return [], False
    after_separator = "--" in typed and not any(leaf.name == "--" for leaf in pattern.flat(Command))
    # the frontier of a path holds every option it can still take, and its first command or positional comes next
    steps = _Steps()
    reachable: set[Pattern] = set()
    names: set[str] = set()
    ahead: list[tuple[Pattern, ...]] = []  # what each path with a positional of the schema next left unfilled
    for frontier in _taking_all(walked, base, steps):
        reachable.update(frontier)
        first = next(itertools.filterfalse(_is_option, frontier), None)
        if type(first) is Command:
            names.add(str(first.name))
        elif isinstance(first, _Typed) and len(ahead) < _PATHS_FINISHED:
            ahead.append(frontier)
    if steps.cut:
        # paths went unseen: the commands are those of the walk that stops at them, where a path seen holds the name
        names = _commands_in_order(walked, base) & {str(leaf.name) for leaf in reachable if type(leaf) is Command}
    fields: Fields = (values_for, takes, is_path)
    values, free = _next_values(pattern, base, ahead, bound_by or (lambda _taken: fields))
    names |= values
    if after_separator:
        return sorted(names), free  # options are not parsed after a POSIX `--` separator
    for leaf in reachable:
        if isinstance(leaf, Option):
            names.add(str(leaf.long or leaf.short))
            if leaf.long is not None and leaf.argcount:
                names.update(f"{leaf.long}={value}" for value in values_for(leaf.long))
    return sorted(names), free


def complete(doc: str, words: Sequence[str], schema: type[Any] | None = None) -> list[str]:
    """Return the completion candidates for the last (cursor) word of ``words``.

    Earlier tokens are consumed against the usage pattern. The command literals and option names
    that could legally come next are returned, filtered to the partial word. A malformed doc yields
    no candidates, never raises.

    A value is a candidate only with ``schema``, and only for a field that takes a closed set, a
    ``Literal`` or an ``Enum``. Such a field completes as the next positional, as the argument the
    last option is waiting for, and as ``--option=value`` beside the option's own name. Without it,
    a prefix that ends on an option waiting for its argument yields no candidates.

    The next positional is the one [`docopt`][docopt2.docopt] would give the next word to: with
    ``[<name>] [<mode>]`` a word typed first is a ``<name>``, so no ``<mode>`` is offered before it.

    A schema other than a pydantic model reads the typed words too: after a value that its field does
    not take there are no candidates, since no argv that starts that way can be bound.
    """
    return _complete(doc, words, [] if schema is None else [schema])[0]


def _complete(
    doc: str, words: Sequence[str], schemas: Sequence[type[Any]], table: Table | None = None
) -> tuple[list[str], bool]:
    tokens = list(words)
    incomplete = tokens[-1] if tokens else ""
    typed = tokens[:-1]
    try:
        if table is None:
            options, pattern = _read(doc)
            candidates, free = _resolve(options, pattern, typed, *_fields(schemas, alone=True))
        else:
            candidates, free = _resolve_table(doc, typed, table)
    except (DocoptLanguageError, DocoptExit, RecursionError):
        # a malformed doc, a prefix ending mid-option-argument, or a pathologically deep pattern:
        # complete nothing rather than raising into the shell
        return [], False
    return [name for name in candidates if name.startswith(incomplete)], free


def _behind(node: Pattern, words: Sequence[str], counts: set[int]) -> set[int]:
    """How many of ``words``, the positionals typed so far, can be behind once ``node`` is, where any of ``counts``
    of them were behind before it.

    An option is passed by, since it is read wherever it stands, and so is the `--` that the words leave out.
    Once every word is behind, the count stays: what is typed is a beginning, and the rest is free to follow.
    """
    if not isinstance(node, BranchPattern):
        if isinstance(node, Option) or (type(node) is Command and node.name == "--"):
            return counts
        taken = {count + 1 for count in counts if count < len(words)}
        if type(node) is Command:
            taken = {count for count in taken if words[count - 1] == node.name}
        return taken | (counts & {len(words)})
    if isinstance(node, Either):
        return {count for child in node.children for count in _behind(child, words, counts)}
    for child in node.children:
        past = _behind(child, words, counts)
        counts = counts | past if isinstance(node, Optional) else past
    while isinstance(node, OneOrMore) and not (again := _behind(node.children[0], words, counts)) <= counts:
        counts = counts | again
    return counts


def _in_reach(options: list[Option], pattern: Pattern, typed: list[str], table: Table) -> set[int | None]:
    """The handlers of ``table`` that may be the one run once the line is whole: those that can be run for a
    usage line that may take the typed words. None among them stands for an argv that no handler takes.

    A line may take them where it holds every option typed and some way through it has the typed positionals
    in their order. That is asked of the pattern, and not of the walk that completes: a line too many is a
    handler too many in reach, and a line too few would let one schema judge what another handler is run for.
    Each line is asked alone, so a word that two lines read in two ways leaves the handlers of both.
    """
    try:
        leaves = parse_argv(Tokens(list(typed)), list(options))
    except DocoptExit:
        leaves = parse_argv(Tokens([*typed, _A_VALUE]), list(options))  # the last option waits for its argument
    words = [str(leaf.value) for leaf in leaves if type(leaf) is Argument and leaf.value != "--"]
    given = {leaf.name for leaf in leaves if isinstance(leaf, Option)}
    binders = line_binders(pattern, [command_path for command_path, _schema in table])
    reach: set[int | None] = set()
    for line, able in zip(_usage_lines(pattern), binders, strict=True):
        if given <= {leaf.name for leaf in line.flat(Option)} and len(words) in _behind(line, words, {0}):
            reach |= able
    return reach


def _resolve_table(doc: str, typed: list[str], table: Table) -> tuple[list[str], bool]:
    """As ``_resolve``, for a handler table: the usage is read with the schemas of the handlers that the typed
    words leave in reach.

    Where that is one handler, with a schema, its schema reads the typed words as well. Where it is several,
    the value of an option follows only where each schema that declares its field takes it, and the walk judges
    no typed word: which of them is run is not known before the line is whole. A line finished to see what
    reads the next word is whole, so its positional is offered the values of the handler run for that line.
    """
    options, pattern = _read(doc)  # the options filled in: a path may name one that only `[options]` holds
    reach = _in_reach(options, pattern, typed, table)
    bound = [table[at][1] for at in sorted(at for at in reach if at is not None)]
    # told apart by `is`: a class need not hash
    schemas = [one for at, one in enumerate(bound) if one is not None and not any(one is seen for seen in bound[:at])]
    alone = len(reach) == 1 and len(schemas) == 1
    return _resolve(options, pattern, typed, *_fields(schemas, alone=alone), _run_for(doc, pattern, table))


def _run_for(doc: str, pattern: Pattern, table: Table) -> Callable[[list[Pattern]], Fields | None]:
    """For the leaves a whole line is read as: the fields of the handler run for them, None where none is.

    The handler is the one ``Dispatch.run`` resolves, from what the line gives and the defaults the usage
    states: a Tab press reads no ``[env:]`` variable and no config.
    """
    paths = [command_path for command_path, _schema in table]
    unset: dict[str | None, object] = {}
    fields: dict[int, Fields] = {}

    def bound_by(taken: list[Pattern]) -> Fields | None:
        if not unset:
            unset.update((leaf.name, leaf.value) for leaf in pattern.flat())
            stated = parse_argument_defaults(doc).items()
            unset.update((name, default) for name, default in stated if unset.get(name, default) is None)
        read = {**unset, **{leaf.name: leaf.value for leaf in taken}}
        run = most_specific(paths, [name for path in paths for name in path if read.get(name)])
        if run is not None and run not in fields:
            schema = table[run][1]
            fields[run] = _fields([] if schema is None else [schema], alone=True)
        return None if run is None else fields[run]

    return bound_by


def _describe(doc: str) -> dict[str, str]:
    """Map each option name (long and short) to its help text from the ``Options:`` block(s).

    This is the same right-hand column ``Option.parse`` reads for ``[default: ...]``, kept here for
    completion tooltips instead of discarded. Options with no description, and commands (which have no
    description column), simply get no entry, so their completion candidate shows without a tooltip.
    """
    descriptions: dict[str, str] = {}
    for chunk in _option_chunks(doc):
        option = Option.parse(chunk)
        _, _, text = chunk.strip().partition("  ")
        # Collapse wrapped continuation lines and stray tabs to single spaces: a newline or tab in
        # the text would split the `name\tdescription` reply line the shells rely on, injecting a
        # bogus candidate. join(split()) also trims the ends before the trailing period is dropped.
        text = " ".join(text.split()).rstrip(".").strip()
        for name in (option.long, option.short):
            if name is not None:
                descriptions[name] = text
    return descriptions


def _fields(schemas: Sequence[type[Any]], *, alone: bool) -> Fields:
    """By the key of a usage element: the values to offer for it, whether a text is one its field takes, and
    whether its field is typed as a ``Path``.

    With no schema there is nothing to offer and nothing to ask, so the second is None. Where the first schema
    is not ``alone`` in binding the lines, any text is taken: which handler binds a line is not known before
    the line is whole.
    """
    if not schemas:
        return (lambda _key: []), None, (lambda _key: False)
    from docopt2._typed import _key_to_field, field_choices, field_paths, field_takes  # deferred: a schema's alone

    choices, paths = field_choices(schemas), field_paths(schemas)
    takes = field_takes(schemas[0]) if alone else (lambda _field, _text: True)
    return (
        (lambda key: choices.get(_key_to_field(key), [])),
        (lambda key, text: takes(_key_to_field(key), text)),
        (lambda key: _key_to_field(key) in paths),
    )


_MARKED_REQUEST = "2"  # what a script sets the trigger to when it reads the mark below; an older one sets "1"
_FILES_MARK = "\tfiles"  # the first line of a reply where a file name may come next: no name opens with a tab


def reply_to_completion_request(
    doc: str, schemas: Sequence[type[Any]] = (), *, table: Table | None = None
) -> str | None:
    """If a completion request is in the environment, return its reply, else None.

    ``table`` is given in place of ``schemas`` by a handler table: the command path and the schema of each of
    its handlers. Each usage line is then completed by the schemas of the handlers that can be run for it.

    A request that names a shell, ``_DOCOPT2_COMPLETE=bash``, asks for the completion script of that shell,
    written for the program the usage names, by the base name of its first word. Where that is no plain
    command name, ``generate_completion`` refuses it.

    Any other value asks for the candidates after the completed tokens that the second variable holds. Each
    reply line is ``name\tdescription`` (the description may be empty). To the value ``2`` the reply opens
    with one more line, a tab and ``files``, where a file name may come next: the value of a field that a
    schema types as a ``Path``. A script from before that mark asks with ``1`` and never gets it.

    Only a [`generate_completion`][docopt2.generate_completion] script, or a user who asks for one, sets the
    variable, so a normal run returns None.

    Shells that show descriptions (zsh, fish, PowerShell, nushell) render the second
    column, while bash keeps the name only.
    """
    asked = os.environ.get(_TRIGGER_ENV)
    if asked is None:
        return None
    if asked in _RENDERERS:
        named = single_usage_section(doc).partition(":")[2].split()[:1]  # empty where the usage names no program
        return generate_completion(doc, os.path.basename("".join(named)), asked)
    raw = os.environ.get(_WORDS_ENV, "")
    words = raw.split("\n") if raw else []
    try:
        descriptions = _describe(doc)
    except DocoptLanguageError:
        descriptions = {}  # a malformed Options section must not raise into the shell on Tab
    candidates, free = _complete(doc, [*words, ""], schemas, table)
    # `--option=value` is described as its option is, and a value alone has no description
    lines = [f"{name}\t{descriptions.get(name.partition('=')[0], '')}" for name in candidates]
    return "\n".join([_FILES_MARK, *lines] if free and asked == _MARKED_REQUEST else lines)


# --- shell scripts: thin callbacks that ask the program at completion time ----------------------


def _function_name(prog: str) -> str:
    """A shell-function-safe identifier derived from the program name."""
    return "_" + re.sub(r"\W", "_", prog) + "_completion"


def _render_bash(prog: str, function: str) -> str:
    # COMP_WORDBREAKS holds `=` and `:`, so bash splits `--opt=value` into three COMP_WORDS. Forwarding the
    # shards destroys the parse context and kills every later completion; bash emits the separator as its
    # own word, so the loop glues them back.
    template = (
        "__FUNC__() {\n"
        "    local -a typed=()\n"
        "    local index part\n"
        "    for (( index = 1; index < COMP_CWORD; index++ )); do\n"
        "        part=${COMP_WORDS[index]}\n"
        "        if [[ ${#typed[@]} -gt 0 && ( $part == [:=] || ${COMP_WORDS[index-1]} == [:=] ) ]]; then\n"
        "            typed[$(( ${#typed[@]} - 1 ))]+=$part\n"
        "        else\n"
        '            typed+=("$part")\n'
        "        fi\n"
        "    done\n"
        # the cursor in the value of `--opt=`: bash completes behind the `=` itself, so ask as for `--opt` waiting
        "    local current=${COMP_WORDS[COMP_CWORD]}\n"
        "    local last=$(( ${#typed[@]} - 1 ))\n"
        "    if [[ $current == = ]]; then\n"
        "        current=\n"
        "    elif [[ $last -ge 0 && ${COMP_WORDS[COMP_CWORD-1]} == = ]]; then\n"
        "        typed[$last]=${typed[$last]%=}\n"
        "    fi\n"
        "    local IFS=$'\\n'\n"
        '    local words="${typed[*]}"\n'  # completed tokens, glued back, without the program name
        '    local reply; reply="$(__TRIGGER__=__ASK__ __WORDS__="$words" "${COMP_WORDS[0]}" 2>/dev/null)"\n'
        '    COMPREPLY=( $(compgen -W "$(cut -f1 <<< "$reply")" -- "$current") )\n'
        # a reply that opens with a tab asks for file names. By line: unquoted, $(compgen -f) globs `[x].txt` away
        "    if [[ $reply == $'\\t'* ]]; then\n"
        "        local -a files=()\n"
        "        local file\n"
        # a line that is no file is a piece of a name that holds a newline: compgen prints one name to a line
        "        while IFS= read -r file; do\n"
        '            [[ -e ${file/#\\~\\//$HOME/} || -L $file ]] && files+=("$file")\n'
        '        done <<< "$(compgen -f -- "$current")"\n'
        # `-o filenames` would slash a command named as a directory: beside names each file is quoted and slashed here
        "        if [[ ${#COMPREPLY[@]} -eq 0 ]]; then\n"
        "            type compopt &>/dev/null && compopt -o filenames\n"
        '            COMPREPLY=( "${files[@]}" )\n'
        "        else\n"
        '            for file in "${files[@]}"; do\n'
        "                [[ -d $file ]] && file+=/\n"
        '                COMPREPLY+=( "$(printf \'%q\' "$file")" )\n'
        "            done\n"
        "        fi\n"
        "    fi\n"
        "}\n"
        "complete -F __FUNC__ __PROG__\n"
    )
    return (
        template.replace("__PROG__", prog)
        .replace("__FUNC__", function)
        .replace("__TRIGGER__", _TRIGGER_ENV)
        .replace("__WORDS__", _WORDS_ENV)
        .replace("__ASK__", _MARKED_REQUEST)
    )


def _render_zsh(prog: str, function: str) -> str:
    # Commands reply with an empty description, and `_describe` renders one as a dangling `--`, so bare
    # names go to `compadd` instead. The two groups are added under `if`, not `&&`: an empty group would
    # otherwise leave a non-zero status and zsh would read that as "nothing matched".
    template = (
        "#compdef __PROG__\n"
        "__FUNC__() {\n"
        '    local joined="${(pj:\\n:)words[2,CURRENT-1]}"\n'  # completed tokens, not the current word
        "    local -a lines described bare\n"
        '    lines=("${(@f)$(__TRIGGER__=__ASK__ __WORDS__=$joined ${words[1]})}")\n'
        "    local line desc files=0\n"
        "    for line in $lines; do\n"
        "        if [[ $line == $'\\t'* ]]; then\n"  # the mark: file names may come next
        "            files=1\n"
        "            continue\n"
        "        fi\n"
        "        desc=\"${line#*$'\\t'}\"\n"
        "        if [[ -n $desc ]]; then\n"
        "            described+=(\"${line%%$'\\t'*}:$desc\")\n"
        "        else\n"
        "            bare+=(\"${line%%$'\\t'*}\")\n"
        "        fi\n"
        "    done\n"
        "    if (( $#described )); then\n"
        "        _describe -t candidates candidate described\n"
        "    fi\n"
        "    if (( $#bare )); then\n"
        "        compadd -a bare\n"
        "    fi\n"
        "    if (( files )); then\n"
        "        _files\n"
        "    fi\n"
        "}\n"
        # Autoloaded from `$fpath`, zsh runs this file's body AS the completion function, so a body that
        # only defines and registers offers nothing on the first Tab. `CURRENT` exists only while the
        # completion system runs, which tells that install apart from a plain `source`.
        "if (( ${+CURRENT} )); then\n"
        '    __FUNC__ "$@"\n'
        "else\n"
        "    compdef __FUNC__ __PROG__\n"
        "fi\n"
    )
    return (
        template.replace("__PROG__", prog)
        .replace("__FUNC__", function)
        .replace("__TRIGGER__", _TRIGGER_ENV)
        .replace("__WORDS__", _WORDS_ENV)
        .replace("__ASK__", _MARKED_REQUEST)
    )


def _render_fish(prog: str, function: str) -> str:
    return (
        f"function {function}\n"
        # `commandline -opc` is the completed tokens before the cursor (the partial word is excluded);
        # fish filters the returned candidates by that partial word itself.
        f"    set -l tokens (commandline -opc)\n"
        # fish documents that a command substitution splits its output on newlines. A completion function
        # happens not to re-split today, but that is undocumented; `string collect` states the intent rather
        # than depending on the accident.
        f"    set -l reply (env {_TRIGGER_ENV}={_MARKED_REQUEST} "
        f"{_WORDS_ENV}=(string join \\n -- $tokens[2..-1] | string collect) $tokens[1])\n"
        # a line that opens with a tab is the mark: `-f` below keeps fish's own file names out, so they are added here
        f"    string match -v -- \\t'*' $reply\n"
        f"    if string match -q -- \\t'*' $reply\n"
        f"        for file in (__fish_complete_path (commandline -ct))\n"
        f"            set -l name (string split -m1 \\t -- $file)[1]\n"
        # a line that is no file is a piece of a name that holds a newline: fish prints one name to a line
        f"            if string match -q -- '~*' $name; or test -e $name; or test -L $name\n"
        f"                echo $file\n"
        f"            end\n"
        f"        end\n"
        f"    end\n"
        f"end\n"
        f"complete -c {prog} -f -a '({function})'\n"
    )


def _render_powershell(prog: str, _function: str) -> str:
    # PowerShell script blocks are brace-heavy, so build from a template with plain placeholders
    # rather than an f-string that would need every `{`/`}` doubled.
    template = (
        "Register-ArgumentCompleter -Native -CommandName __PROG__ -ScriptBlock {\n"
        "    param($wordToComplete, $commandAst, $cursorPosition)\n"
        # PowerShell hands over the whole line, so a mid-line Tab would read the tokens right of the cursor.
        "    $typed = @($commandAst.CommandElements | Where-Object { $_.Extent.EndOffset -le $cursorPosition })\n"
        # A quoted token arrives with its quotes attached; the program must get the value, not the quoting.
        "    $words = @($typed | Select-Object -Skip 1 | ForEach-Object {\n"
        "        if ($_ -is [System.Management.Automation.Language.StringConstantExpressionAst])"
        " { $_.Value } else { $_.ToString() }\n"
        "    })\n"
        "    if ($wordToComplete -ne '' -and $words.Count -gt 0) { $words = @($words | Select-Object -SkipLast 1) }\n"
        "    $env:__TRIGGER__ = '__ASK__'\n"
        '    $env:__WORDS__ = ($words -join "`n")\n'
        "    $files = $false\n"
        "    try {\n"
        "        & $commandAst.CommandElements[0].ToString() 2>$null | ForEach-Object {\n"
        '            $parts = $_ -split "`t", 2\n'  # reply line is name`tdescription
        "            $name = $parts[0]\n"
        # StartsWith, not -like: a `*` or `[` in the partial word is a literal prefix, not a wildcard.
        '            if ($_.StartsWith("`t")) {\n'  # the mark: file names may come next
        "                $files = $true\n"
        "            } elseif ($name.StartsWith($wordToComplete, [System.StringComparison]::Ordinal)) {\n"
        "                $tip = if ($parts.Count -ge 2 -and $parts[1]) { $parts[1] } else { $name }\n"
        "                [System.Management.Automation.CompletionResult]::new($name, $name, 'ParameterValue', $tip)\n"
        "            }\n"
        "        }\n"
        # names and file names together: left to itself PowerShell offers files only where nothing was returned
        "        if ($files) {\n"
        "            [System.Management.Automation.CompletionCompleters]::CompleteFilename($wordToComplete) |\n"
        "                ForEach-Object {\n"
        # a native program is handed the text as it stands: the escapes PowerShell adds for its own providers go
        "                    $text = $_.CompletionText -replace '`([`\\[\\]])', '$1'\n"
        "                    [System.Management.Automation.CompletionResult]::new("
        "$text, $_.ListItemText, $_.ResultType, $_.ToolTip)\n"
        "                }\n"
        "        }\n"
        "    } finally {\n"
        "        Remove-Item Env:__TRIGGER__ -ErrorAction SilentlyContinue\n"
        "        Remove-Item Env:__WORDS__ -ErrorAction SilentlyContinue\n"
        "    }\n"
        "}\n"
    )
    return (
        template.replace("__PROG__", prog)
        .replace("__TRIGGER__", _TRIGGER_ENV)
        .replace("__WORDS__", _WORDS_ENV)
        .replace("__ASK__", _MARKED_REQUEST)
    )


def _render_nushell(prog: str, function: str) -> str:
    # nushell's `@complete` (0.108+) attaches a whole-command completer that fires for commands AND flags and
    # does NOT filter, so the completer filters by the partial itself. `spans` is `[prog, ...typed, partial]`,
    # so it drops the program name, answers the typed tokens over the shared env protocol, and keeps the
    # reply candidates starting with the partial. `export extern` declares only `...rest` (no typed flags) so
    # the program still RUNS with any flag - a typed flag would reject a valid invocation. The module file
    # must NOT be named `<prog>.nu` (a module cannot export an extern of its own name).
    template = (
        'def "__FUNC__" [spans: list<string>] {\n'
        "    let words = ($spans | skip 1)\n"
        "    let typed = ($words | drop 1)\n"
        "    let partial = ($words | last)\n"
        '    let reply = (with-env {__TRIGGER__: "__ASK__", __WORDS__: ($typed | str join (char newline))} '
        "{ ^__PROG__ | complete | get stdout } | lines)\n"
        "    let marks = ($reply | where {|line| $line | str starts-with (char tab)})\n"  # file names may come next
        "    let names = ($reply | where {|line| ($line | str length) > 0 and $line not-in $marks} | each {|line|\n"
        "        let parts = ($line | split row (char tab))\n"  # reply line is name<TAB>description
        '        {value: ($parts | get 0), description: ($parts | get 1? | default "")}\n'
        "    } | where {|candidate| $candidate.value | str starts-with $partial})\n"
        "    if ($marks | is-empty) { return $names }\n"
        # null hands the word to nushell's own file completion; beside names it gives none, so they are listed here
        "    if ($names | is-empty) { return null }\n"
        '    $names | append (try { ls ($partial + "*" | into glob) | each {|file|\n'
        '        let name = (if $file.type == dir { $file.name + "/" } else { $file.name })\n'
        '        {value: ($name | to nuon), description: ""}\n'  # quoted as nushell itself writes a string
        "    } } catch { [] })\n"
        "}\n"
        '@complete "__FUNC__"\n'
        'export extern "__PROG__" [ ...rest: string ]\n'
    )
    return (
        template.replace("__PROG__", prog)
        .replace("__FUNC__", function)
        .replace("__TRIGGER__", _TRIGGER_ENV)
        .replace("__WORDS__", _WORDS_ENV)
        .replace("__ASK__", _MARKED_REQUEST)
    )


_RENDERERS: dict[str, Callable[[str, str], str]] = {
    "bash": _render_bash,
    "zsh": _render_zsh,
    "fish": _render_fish,
    "powershell": _render_powershell,
    "nushell": _render_nushell,
}


def generate_completion(doc: str, prog: str, shell: str = "bash") -> str:
    """Return a context-aware shell completion script for the CLI described by ``doc``.

    The script is a thin callback carrying no grammar of its own. At each Tab it re-invokes the program with
    a completion request in the environment, and that program's [`docopt`][docopt2.docopt] call resolves the
    tokens legal at the cursor from the usage grammar. Suggestions therefore narrow to the matched subcommand's options
    and arguments, rather than a flat global list.

    A docopt program answers those requests by default. A program that does not want this passes
    ``docopt(..., complete=False)`` to opt out.

    Args:
        doc: The usage message (the same string given to [`docopt`][docopt2.docopt]).
        prog: The command name the script completes for. Must be a plain command name
            (letters, digits, ``.``, ``_``, ``-``), and must be on ``PATH`` under that name.
        shell: One of ``"bash"``, ``"zsh"``, ``"fish"``, ``"powershell"`` or ``"nushell"``.

    Returns:
        The completion script as text. It depends only on ``prog`` and ``shell``, never on the usage,
        since the grammar stays in the program.

    Raises:
        ValueError: ``shell`` is not supported, or ``prog`` is not a plain command name.
        DocoptLanguageError: The usage message is malformed. It fails here rather than at Tab time.
    """
    if shell not in _RENDERERS:
        supported = ", ".join(sorted(_RENDERERS))
        raise ValueError(f"unsupported shell: {shell!r}; expected one of {supported}")
    # The script interpolates `prog` into shell/PowerShell source that is sourced or eval'd, so a
    # name with metacharacters (`;`, `$()`, spaces, quotes) would inject or corrupt it. Require a
    # plain command name.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", prog):
        raise ValueError(f"prog {prog!r} must be a plain command name (letters, digits, . _ -)")
    # Validate the docstring up front so a malformed usage fails loudly here, not silently at Tab.
    parse_pattern(formal_usage(single_usage_section(doc)), parse_defaults(doc))  # as a Tab press reads it
    return _RENDERERS[shell](prog, _function_name(prog))
