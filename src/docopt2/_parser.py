# Parsing engine derived from the original docopt (MIT); see NOTICE.
from __future__ import annotations

import contextlib
import contextvars
import copy
import functools
import itertools
import re
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from docopt2._diagnostics import Caret, Diagnostic, Snippet
from docopt2._errors import DocoptExit, DocoptLanguageError

if TYPE_CHECKING:
    from collections.abc import Iterator

LeafValue: TypeAlias = str | int | bool | list[str] | None
Span: TypeAlias = tuple[int, int] | None
SingleMatch: TypeAlias = tuple[int, "Pattern"] | tuple[None, None]
MatchResult: TypeAlias = tuple[bool, list["Pattern"], list["Pattern"]]
MatchOutcome: TypeAlias = tuple[list["Pattern"], list["Pattern"]]
ErrorType: TypeAlias = type[DocoptExit] | type[DocoptLanguageError]

# A pattern with many optionals/alternatives has exponentially many match outcomes (`[<a>] [<b>]`
# x n -> 2**n). MATCH_LIMIT caps a single materialization - a lone Either's sort, the completion frontier
# walk, a bare matches() call - far above any real CLI. docopt()'s own match is bounded globally instead
# (the budget below), because this per-node cap alone still compounds to minutes on a malformed pattern.
MATCH_LIMIT = 200_000

# The global budget bounds docopt()'s whole match with one shared ceiling: an adversarial or malformed
# pattern, whose `_combine` DFS backtracks exponentially when no complete match exists, rejects in bounded
# time. It stays a small FIXED number because `Either.matches` yields lazily (greedy-first, materializing its
# sorted tail only if a caller backtracks past it): an honest match threads a single greedy path - a few
# hundred descents even for a long `<files>...` argv - so it never approaches the ceiling. Only a search with
# no complete match, forced to explore its full 2**n fan, reaches it. (An EAGER Either that materialized every
# outcome to sort them made an honest match's descents grow with argv and false-rejected a real 200-file CLI.)
_match_budget: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar("docopt2_match_budget", default=None)


class _MatchBudgetExceededError(Exception):
    """One match explored more outcomes than allowed - an adversarial argv or a malformed usage pattern."""


@contextlib.contextmanager
def match_budget(limit: int = MATCH_LIMIT) -> Iterator[None]:
    """Bound the total outcomes the enclosed match may materialize; past ``limit``, _MatchBudgetExceeded."""
    token = _match_budget.set([limit])
    try:
        yield
    finally:
        _match_budget.reset(token)


def _bounded(outcomes: Iterator[MatchOutcome]) -> Iterator[MatchOutcome]:
    """Bound a lone Either's materialization when no match budget is set - completion, a bare ``matches()``
    call, ``parse_tree`` - by falling back to the per-node MATCH_LIMIT. Under a budget, ``_combine``'s
    ``_spend_budget`` is the real bound (it charges the dead branches that yield nothing too), so this
    passes the outcomes straight through.
    """
    if _match_budget.get() is None:
        yield from itertools.islice(outcomes, MATCH_LIMIT)
    else:
        yield from outcomes


def _spend_budget() -> None:
    """Charge one step of match exploration against the shared budget; raise once it is spent.

    Charged per ``_combine`` descent - the exponential engine - so a DFS that dead-ends WITHOUT yielding
    (many optionals before an unmatchable required tail explores 2**n branches, none of them an outcome) is
    bounded too. A genuine match is cheap because ``Either`` yields greedy-first without materializing its
    fan (see :meth:`Either.matches`), so an honest match threads one greedy path - a few hundred descents even
    over a long ``<files>...`` glob - while an adversarial pattern's 2**n fan-out reaches the cap. A no-op when
    no budget is set.
    """
    budget = _match_budget.get()
    if budget is not None:
        budget[0] -= 1
        if budget[0] < 0:
            raise _MatchBudgetExceededError


# Extracts a `[default: value]` from an option or argument description; compiled once, not per line.
_DEFAULT_PATTERN = re.compile(r"\[default: (.*)]", flags=re.IGNORECASE)
# Extracts an `[env: VAR]` fallback source from an option description. Pure text only: os.environ is
# never read here (parsing stays side-effect-free, so completion and linting see the same tree).
_ENV_PATTERN = re.compile(r"\[env:\s*([^\]\s]+)\s*]", flags=re.IGNORECASE)
# Extracts a `[config: dotted.key]` fallback source; resolved against the mapping passed to docopt(config=).
_CONFIG_PATTERN = re.compile(r"\[config:\s*([^\]\s]+)\s*]", flags=re.IGNORECASE)


def _leaf_with_value(leaf: Pattern, value: LeafValue) -> Pattern:
    """Return a copy of ``leaf`` carrying ``value`` so matching accumulates immutably."""
    clone = copy.copy(leaf)
    clone.value = value
    return clone


class Pattern:
    """Base class for every node in a usage-pattern tree."""

    _name: str | None
    # Source offsets of this node in the usage section, for caret diagnostics. Inert metadata: it is
    # excluded from repr/__eq__/__hash__/to_dict, so nodes equal on structure stay equal and matching
    # is unaffected. None when unknown (argv-parsed leaves, the formal-usage wrapper, parse_tree()).
    span: Span = None

    @property
    def value(self) -> LeafValue:
        raise NotImplementedError  # only leaf nodes carry a value; branches have none

    @value.setter
    def value(self, new_value: LeafValue) -> None:
        raise NotImplementedError

    @property
    def name(self) -> str | None:
        """Key under which this element appears in the parsed result."""
        return self._name

    def __eq__(self, other: object) -> bool:
        return repr(self) == repr(other)

    def __hash__(self) -> int:
        return hash(repr(self))

    def match(self, left: list[Pattern], collected: list[Pattern] | None = None) -> MatchResult:
        """Greedy single-result match: the first (greedy) outcome of :meth:`matches`."""
        collected = [] if collected is None else collected
        first = next(self.matches(left, collected), None)
        if first is None:
            return False, left, collected
        return True, first[0], first[1]

    def matches(self, left: list[Pattern], collected: list[Pattern]) -> Iterator[MatchOutcome]:
        """Yield every ``(remaining, collected)`` outcome of matching, greedy result first.

        Unlike ``match`` (a single greedy result), this explores alternatives so a caller can
        find a fully-consuming match even when the greedy one leaves leaves over.
        """
        raise NotImplementedError

    def flat(self, *types: type[Pattern]) -> list[Pattern]:
        """Return the tree tips (or the nodes whose exact type is in ``types``)."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable tree describing this pattern node."""
        raise NotImplementedError

    def fix(self) -> Pattern:
        """Resolve shared identities and mark repeating elements. Returns self."""
        self.fix_identities()
        self.fix_repeating_arguments()
        return self

    def fix_identities(self, uniq: dict[Pattern, Pattern] | None = None) -> None:
        """Make equal tree tips point to the same object, so counts accumulate."""
        if not isinstance(self, BranchPattern):
            return
        # Map each distinct leaf to one canonical instance; the dict lookup resolves n leaves in O(n).
        canonical = {leaf: leaf for leaf in self.flat()} if uniq is None else uniq
        for index, child in enumerate(self.children):
            if isinstance(child, BranchPattern):
                child.fix_identities(canonical)
            else:
                self.children[index] = canonical[child]

    def fix_repeating_arguments(self) -> Pattern:
        """Turn elements that may appear more than once into accumulators. Returns self."""
        repeating = {leaf for leaf, count in _max_occurrences(self).items() if count > 1}
        # Materialize the targets before mutating: leaves hash by value, so mutating one would
        # corrupt set membership for an equal sibling still to be visited.
        for element in [leaf for leaf in self.flat() if leaf in repeating]:
            if type(element) is Argument or (isinstance(element, Option) and element.argcount):
                if element.value is None:
                    element.value = []
                elif isinstance(element.value, str):
                    element.value = element.value.split()
            if type(element) is Command or (isinstance(element, Option) and element.argcount == 0):
                element.value = 0
        return self


def transform(pattern: Pattern) -> Either:
    """Expand a pattern into an (almost) equivalent one with a single top-level Either.

    Example: ``((-a | -b) (-c | -d))`` becomes ``(-a -c | -a -d | -b -c | -b -d)``.
    Quirks: ``[-a]`` becomes ``(-a)``; ``(-a...)`` becomes ``(-a -a)``.
    """
    result: list[list[Pattern]] = []
    groups: list[list[Pattern]] = [[pattern]]
    branch_types = (Required, Optional, OptionsShortcut, Either, OneOrMore)
    while groups:
        children = groups.pop(0)
        branches = [child for child in children if isinstance(child, branch_types)]
        if not branches:
            result.append(children)
            continue
        branch = branches[0]
        children.remove(branch)
        if isinstance(branch, Either):
            groups.extend([branch_child, *children] for branch_child in branch.children)
        elif isinstance(branch, OneOrMore):
            groups.append(branch.children * 2 + children)
        else:
            groups.append(branch.children + children)
    return Either(*[Required(*case) for case in result])


class LeafPattern(Pattern):
    """Leaf/terminal node of a pattern tree."""

    def __init__(self, name: str | None, value: LeafValue = None) -> None:
        self._name = name
        # __eq__/__hash__ compare via repr, called in tight fix() loops; cache the repr and drop it
        # on value mutation so each compare stays O(1).
        self._cached_repr: str | None = None
        self._value = value

    @property
    def value(self) -> LeafValue:
        return self._value

    @value.setter
    def value(self, new_value: LeafValue) -> None:
        self._value = new_value
        self._cached_repr = None

    def _render_repr(self) -> str:
        return f"{type(self).__name__}({self.name!r}, {self._value!r})"

    def __repr__(self) -> str:
        if self._cached_repr is None:
            self._cached_repr = self._render_repr()
        return self._cached_repr

    def to_dict(self) -> dict[str, Any]:
        return {"type": type(self).__name__, "name": self.name}

    def single_match(self, left: list[Pattern]) -> SingleMatch:
        """Find the first argument-vector leaf this pattern matches. Overridden per leaf."""
        raise NotImplementedError

    def flat(self, *types: type[Pattern]) -> list[Pattern]:
        if not types or type(self) in types:
            return [self]
        return []

    def matches(self, left: list[Pattern], collected: list[Pattern]) -> Iterator[MatchOutcome]:
        position, matched_leaf = self.single_match(left)
        if matched_leaf is None or position is None:
            return
        remaining = left[:position] + left[position + 1 :]
        # Only int-counted or list-valued leaves need the same-named prior match; the common
        # non-repeating case below does not, so skip scanning `collected` for it entirely.
        # `type(...) is int` deliberately excludes bool (a bool flag must not count).
        if type(self.value) is not int and type(self.value) is not list:
            yield remaining, [*collected, matched_leaf]
            return
        existing = next((item for item in collected if item.name == self.name), None)
        if type(self.value) is int:
            if existing is not None:
                incremented = cast("int", existing.value) + 1
                bumped = [_leaf_with_value(item, incremented) if item is existing else item for item in collected]
                yield remaining, bumped
            else:
                yield remaining, [*collected, _leaf_with_value(matched_leaf, 1)]
        else:  # type(self.value) is list
            addition = [matched_leaf.value] if isinstance(matched_leaf.value, str) else matched_leaf.value
            if existing is not None:
                combined = cast("list[str]", existing.value) + cast("list[str]", addition)
                merged = [_leaf_with_value(item, combined) if item is existing else item for item in collected]
                yield remaining, merged
            else:
                yield remaining, [*collected, _leaf_with_value(matched_leaf, addition)]


class BranchPattern(Pattern):
    """Branch/inner node of a pattern tree."""

    def __init__(self, *children: Pattern) -> None:
        self.children = list(children)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({', '.join(repr(child) for child in self.children)})"

    def flat(self, *types: type[Pattern]) -> list[Pattern]:
        if type(self) in types:
            return [self]
        return list(itertools.chain.from_iterable(child.flat(*types) for child in self.children))

    def to_dict(self) -> dict[str, Any]:
        return {"type": type(self).__name__, "children": [child.to_dict() for child in self.children]}


class Argument(LeafPattern):
    """A positional argument, written ``<name>`` or ``NAME`` in the usage pattern."""

    def single_match(self, left: list[Pattern]) -> SingleMatch:
        for index, pattern in enumerate(left):
            if type(pattern) is Argument:
                return index, Argument(self.name, pattern.value)
        return None, None


class Command(Argument):
    """A (sub)command literal, written as a bare word in the usage pattern."""

    def __init__(self, name: str | None, value: bool = False) -> None:
        self._name = name
        self.value = value

    def single_match(self, left: list[Pattern]) -> SingleMatch:
        for index, pattern in enumerate(left):
            if type(pattern) is Argument:
                if pattern.value == self.name:
                    return index, Command(self.name, value=True)
                break
        return None, None


class Option(LeafPattern):
    """A short and/or long option, optionally taking a single argument."""

    def __init__(
        self,
        short: str | None = None,
        long: str | None = None,
        argcount: int = 0,
        value: LeafValue = False,
        env: str | None = None,
        config_key: str | None = None,
    ) -> None:
        self.short = short
        self.long = long
        self.argcount = argcount
        self.value = None if value is False and argcount else value
        self.env = env  # `[env: VAR]` fallback source, resolved at parse time in docopt(), not here
        self.config_key = config_key  # `[config: dotted.key]` fallback, resolved against docopt(config=)

    @classmethod
    def parse(cls, option_description: str, source: str = "") -> Option:
        """Build an Option from a single option-description line.

        ``source`` is the full docstring; when given, a malformed line's error carries a caret
        pointing at the offending word within its reproduced source line.
        """
        short: str | None = None
        long: str | None = None
        argcount = 0
        value: LeafValue = False
        stripped = option_description.strip()
        options, _, description = stripped.partition("  ")
        options = options.replace(",", " ").replace("=", " ")
        flag_tokens = 0
        argument_tokens = 0
        for token in options.split():
            if token.startswith("--"):
                long = token
                flag_tokens += 1
            elif token.startswith("-"):
                short = token
                flag_tokens += 1
            else:
                argcount = 1
                argument_tokens += 1
        if argument_tokens > flag_tokens:
            # Each flag takes at most one arg name, so more argument words than flags almost always
            # means the option and its description were run together with a single space; name the
            # real cause (caret under the first stray word) instead of a cryptic later "unmatched".
            offending = next(match for match in re.finditer(r"\S+", options) if not match.group().startswith("-"))
            base = source.find(stripped)
            carets = [Caret(base + offending.start(), base + offending.end(), "read as an argument name")]
            snippets = [Snippet(source, "in the options:", carets)] if base != -1 else []
            diagnostic = Diagnostic(
                summary=f"option `{stripped}` has more argument words than flags",
                snippets=snippets,
                help="separate the option from its description with at least two spaces",
            )
            raise DocoptLanguageError(diagnostic.render())
        env_match = _ENV_PATTERN.search(description)
        env = env_match.group(1) if env_match else None
        config_match = _CONFIG_PATTERN.search(description)
        config_key = config_match.group(1) if config_match else None
        if argcount:
            # Strip `[env:]`/`[config:]` first so the greedy `[default: (.*)]` cannot swallow them.
            without_sources = _CONFIG_PATTERN.sub("", _ENV_PATTERN.sub("", description))
            matched = _DEFAULT_PATTERN.findall(without_sources)
            value = matched[0] if matched else None
        return cls(short, long, argcount, value, env, config_key)

    def single_match(self, left: list[Pattern]) -> SingleMatch:
        for index, pattern in enumerate(left):
            if self.name == pattern.name:
                token = cast("Option", pattern)
                # Fresh copy: a failed usage branch must not leak accumulated values into the shared argv token.
                value = token.value.copy() if isinstance(token.value, list) else token.value
                return index, Option(token.short, token.long, token.argcount, value)
        return None, None

    @property
    def name(self) -> str | None:
        return self.long or self.short

    def _render_repr(self) -> str:
        return f"Option({self.short!r}, {self.long!r}, {self.argcount!r}, {self._value!r})"

    def to_dict(self) -> dict[str, Any]:
        node: dict[str, Any] = {
            "type": type(self).__name__,
            "short": self.short,
            "long": self.long,
            "argcount": self.argcount,
        }
        if self.argcount:
            node["default"] = self._value
        return node


def _sequence_matches(
    children: list[Pattern], left: list[Pattern], collected: list[Pattern], *, optional: bool
) -> Iterator[MatchOutcome]:
    """Match ``children`` in order, threading the accumulator; with ``optional`` each may be skipped."""

    def _combine(index: int, cur_left: list[Pattern], cur_collected: list[Pattern]) -> Iterator[MatchOutcome]:
        _spend_budget()
        if index == len(children):
            yield cur_left, cur_collected
            return
        for next_left, next_collected in children[index].matches(cur_left, cur_collected):
            yield from _combine(index + 1, next_left, next_collected)
        if optional:  # a child of an Optional may also be skipped entirely
            yield from _combine(index + 1, cur_left, cur_collected)

    yield from _combine(0, left, collected)


class Required(BranchPattern):
    """All children must match, in order."""

    def matches(self, left: list[Pattern], collected: list[Pattern]) -> Iterator[MatchOutcome]:
        yield from _sequence_matches(self.children, left, collected, optional=False)


class Optional(BranchPattern):
    """Children may match; a non-match is not a failure."""

    def matches(self, left: list[Pattern], collected: list[Pattern]) -> Iterator[MatchOutcome]:
        yield from _sequence_matches(self.children, left, collected, optional=True)


class OptionsShortcut(Optional):
    """Marker/placeholder for the ``[options]`` shortcut."""


class OneOrMore(BranchPattern):
    """The single child must match one or more times."""

    def matches(self, left: list[Pattern], collected: list[Pattern]) -> Iterator[MatchOutcome]:
        """Greedy-first: the longest run of the child comes out first, then progressively shorter ones.

        Iterative, on an explicit stack. A repetition consumes one token per round, so a recursive walk
        would nest once per argv token - and `prog <files>...` over a shell glob of a few thousand files
        is ordinary use, which the original parses (its ``OneOrMore`` is a ``while`` loop) and a recursive
        one cannot. Each frame holds the outcome that opened it and yields it once its own run is spent,
        which is what puts the deepest (greediest) run first.
        """
        child = self.children[0]
        stack: list[tuple[Iterator[MatchOutcome], int, MatchOutcome | None]] = [
            (child.matches(left, collected), len(left), None)
        ]
        while stack:
            outcomes, remaining_count, opener = stack[-1]
            outcome = next(outcomes, None)
            if outcome is None:  # this run is spent; the outcome that opened it comes after everything it led to
                stack.pop()
                if opener is not None:
                    yield opener
            elif len(outcome[0]) < remaining_count:  # progress: try to repeat before settling for this run
                stack.append((child.matches(*outcome), len(outcome[0]), outcome))
            else:  # matched without consuming (`[NAME]...` with nothing left): repeating would not terminate
                yield outcome


class Either(BranchPattern):
    """Exactly one branch must match; the one leaving the fewest leaves wins."""

    def matches(self, left: list[Pattern], collected: list[Pattern]) -> Iterator[MatchOutcome]:
        # Greedy-first, lazily. Each branch yields its own fewest-left outcome first, so the global
        # fewest-left - the greedy result the matcher wants - is the min over the branches' first outcomes.
        # Yield it WITHOUT materializing the rest: a caller that takes only the greedy outcome (the common
        # case, and every complete match) stops here, so an honest match never builds the whole fan. The
        # eager `sorted(list(all))` this replaces made that fan grow with argv and false-rejected long CLIs.
        streams = [child.matches(left, collected) for child in self.children]
        firsts = [next(stream, None) for stream in streams]
        live = [index for index, outcome in enumerate(firsts) if outcome is not None]
        if not live:
            return
        best_index = min(live, key=lambda index: len(cast("MatchOutcome", firsts[index])[0]))
        yield cast("MatchOutcome", firsts[best_index])

        def _rest() -> Iterator[MatchOutcome]:
            # Every outcome except the one already yielded, in the branch order the eager version listed
            # them, so `[best] + sorted(_rest())` reproduces `sorted(all)` exactly - tie order included.
            for index, (first, stream) in enumerate(zip(firsts, streams, strict=True)):
                if first is not None and index != best_index:
                    yield first
                yield from stream

        yield from sorted(_bounded(_rest()), key=lambda outcome: len(outcome[0]))


def _accumulate_occurrences(node: Pattern, counts: dict[Pattern, int], multiplier: int) -> None:
    """Add each leaf's occurrence count under ``node`` (scaled by ``multiplier``) into ``counts``.

    A sequence accumulates its children in place; only an Either forks into per-branch subtotals to
    take their maximum, so a long flat option list stays a single pass rather than a dict merge.
    """
    if not isinstance(node, BranchPattern):
        counts[node] = counts.get(node, 0) + multiplier
        return
    if isinstance(node, Either):  # a branch is chosen: add the per-leaf maximum across branches
        branch_max: dict[Pattern, int] = {}
        for child in node.children:
            child_counts: dict[Pattern, int] = {}
            _accumulate_occurrences(child, child_counts, 1)
            for leaf, count in child_counts.items():
                branch_max[leaf] = max(branch_max.get(leaf, 0), count)
        for leaf, count in branch_max.items():
            counts[leaf] = counts.get(leaf, 0) + count * multiplier
        return
    inner = multiplier * 2 if isinstance(node, OneOrMore) else multiplier  # a repetition counts twice
    for child in node.children:
        _accumulate_occurrences(child, counts, inner)


def _max_occurrences(node: Pattern) -> dict[Pattern, int]:
    """Most times each distinct leaf can occur in a single expansion of ``node``.

    A leaf whose maximum reaches two may repeat, so it becomes an accumulator. Computed by a
    bottom-up walk instead of expanding the pattern into disjunctive normal form, which was
    exponential in the number of alternations.
    """
    counts: dict[Pattern, int] = {}
    _accumulate_occurrences(node, counts, 1)
    return counts


# Position-aware tokenizer for usage patterns: each token carries its source offset for caret
# diagnostics. Matches an <angle> argument, an ellipsis, a bracket/pipe, or a word stopping before `...`.
_PATTERN_TOKEN = re.compile(r"(?:(?!\.\.\.)[^\s\[\]()|])*<[^>]*>|\.\.\.|[\[\]()|]|(?:(?!\.\.\.)[^\s\[\]()|])+")


def _check_brackets(source: str, spanned: list[tuple[str, int, int]]) -> None:
    """Raise a diagnostic pointing at the first unbalanced bracket, if any."""
    openers = {")": "(", "]": "["}
    closers = {"(": ")", "[": "]"}
    stack: list[tuple[str, int, int]] = []
    for text, start, end in spanned:
        if text in "([":
            stack.append((text, start, end))
        elif text in ")]":
            if not stack:  # a closer with nothing open: one caret, on the stray bracket
                stray = Snippet(source, "in the usage:", [Caret(start, end, "no group is open to close")])
                diagnostic = Diagnostic(
                    summary=f"unexpected closing `{text}`",
                    snippets=[stray],
                    help="remove it, or open a group before it",
                )
                raise DocoptLanguageError(diagnostic.render())
            open_text, open_start, open_end = stack.pop()
            if open_text != openers[text]:  # wrong kind of closer: two carets, opener and closer
                mismatch = Snippet(
                    source,
                    "in the usage:",
                    [
                        Caret(open_start, open_end, f"`{open_text}` opens the group here"),
                        Caret(start, end, f"`{text}` cannot close it"),
                    ],
                )
                diagnostic = Diagnostic(
                    summary=f"mismatched delimiters: `{open_text}` is closed by `{text}`",
                    snippets=[mismatch],
                    help=f"close it with `{closers[open_text]}`, or open with `{openers[text]}`",
                )
                raise DocoptLanguageError(diagnostic.render())
    if stack:  # an opener that was never closed: one caret, on the opener
        open_text, open_start, open_end = stack[-1]
        unclosed = Snippet(source, "in the usage:", [Caret(open_start, open_end, "opened here, but never closed")])
        diagnostic = Diagnostic(
            summary=f"unclosed `{open_text}`",
            snippets=[unclosed],
            help=f"add `{closers[open_text]}` to close the group",
        )
        raise DocoptLanguageError(diagnostic.render())


class Tokens(list[str]):
    """A mutable token stream that remembers which error class to raise and each token's span."""

    def __init__(
        self,
        source: list[str] | tuple[str, ...] | str,
        error: ErrorType = DocoptExit,
        *,
        spans: list[Span] | None = None,
        text: str = "",
        usage: str = "",
        exit_code: int = 1,
    ) -> None:
        super().__init__(source.split() if isinstance(source, str) else source)
        self.error = error
        self.text = text  # the full source string, for caret rendering
        self.spans: list[Span] = spans if spans is not None else [None] * len(self)
        self._last_span: Span = None
        self.usage = usage  # threaded onto a DocoptExit so argv errors carry usage/exit_code too
        self.exit_code = exit_code

    @property
    def parsing_argv(self) -> bool:
        """Whether this stream is argv (a user error, ``DocoptExit``) rather than the docstring."""
        return self.error is DocoptExit

    @staticmethod
    def from_pattern(source: str) -> Tokens:
        """Tokenize a usage-pattern string (errors become DocoptLanguageError)."""
        spanned = [(match.group(), match.start(), match.end()) for match in _PATTERN_TOKEN.finditer(source)]
        _check_brackets(source, spanned)
        texts = [text for text, _, _ in spanned]
        spans: list[Span] = [(start, end) for _, start, end in spanned]
        return Tokens(texts, error=DocoptLanguageError, spans=spans, text=source)

    def move(self) -> str | None:
        """Pop and return the next token, or None if the stream is empty."""
        if not len(self):
            return None
        self._last_span = self.spans.pop(0)
        return self.pop(0)

    def current(self) -> str | None:
        """Return the next token without consuming it, or None if empty."""
        return self[0] if len(self) else None

    def current_span(self) -> Span:
        """The source span of the next token, if any."""
        return self.spans[0] if self.spans else None

    def fail(self, message: str) -> DocoptExit | DocoptLanguageError:
        """Build the error as a diagnostic, with a caret at the current (or last consumed) token."""
        span = self.current_span() or self._last_span
        intro = "in the arguments:" if self.parsing_argv else "in the usage:"
        carets = [Caret(span[0], span[1], "here")] if span is not None else []
        snippets = [Snippet(self.text, intro, carets)] if self.text else []
        diagnostic = Diagnostic(summary=message, snippets=snippets)
        if self.parsing_argv:
            return DocoptExit(diagnostic=diagnostic, usage=self.usage, exit_code=self.exit_code)
        return self.error(diagnostic.render())


def parse_long(tokens: Tokens, options: list[Option], allow_abbrev: bool = True) -> list[Pattern]:
    """Parse a long option: ``long ::= '--' chars [ ( ' ' | '=' ) chars ] ;``"""
    span = tokens.current_span()
    long, eq, raw_value = cast("str", tokens.move()).partition("=")
    value: str | None = None if eq == "" and raw_value == "" else raw_value
    similar = [option for option in options if option.long == long]
    # An unambiguous prefix de-abbreviates in argv (`--ver` -> `--version`) unless disabled.
    if allow_abbrev and tokens.parsing_argv and not similar:
        similar = [option for option in options if option.long and option.long.startswith(long)]
    if len(similar) > 1:
        names = ", ".join(str(option.long) for option in similar)
        raise tokens.fail(f"`{long}` is not a unique prefix of: {names}")
    if len(similar) < 1:
        argcount = 1 if eq == "=" else 0
        option = Option(None, long, argcount)
        options.append(option)
        if tokens.parsing_argv:
            option = Option(None, long, argcount, value if argcount else True)
        option.span = span
        return [option]
    matched = similar[0]
    option = Option(matched.short, matched.long, matched.argcount, matched.value)
    if option.argcount == 0:
        if value is not None:
            raise tokens.fail(f"`{option.long}` takes no argument")
    elif value is None:
        # `)`/`]` close a group only in the usage pattern; in argv they are ordinary values.
        closers = (None, "--", ")", "]") if not tokens.parsing_argv else (None, "--")
        if tokens.current() in closers:
            raise tokens.fail(f"`{option.long}` requires an argument")
        value = tokens.move()
    if tokens.parsing_argv:
        option.value = value if value is not None else True
    option.span = span
    return [option]


def parse_shorts(tokens: Tokens, options: list[Option]) -> list[Pattern]:
    """Parse a short-option cluster: ``shorts ::= '-' ( chars )* [ [ ' ' ] chars ] ;``"""
    span = tokens.current_span()
    token = cast("str", tokens.move())
    left = token.lstrip("-")
    parsed: list[Pattern] = []
    while left != "":
        short, left = "-" + left[0], left[1:]
        similar = [option for option in options if option.short == short]
        if len(similar) > 1:
            raise tokens.fail(f"`{short}` is specified {len(similar)} times")
        if len(similar) < 1:
            option = Option(short, None, 0)
            options.append(option)
            if tokens.parsing_argv:
                option = Option(short, None, 0, True)
            option.span = span
            parsed.append(option)
            continue
        matched = similar[0]
        option = Option(short, matched.long, matched.argcount, matched.value)
        value: str | None = None
        if option.argcount != 0:
            if left == "":
                closers = (None, "--", ")", "]") if not tokens.parsing_argv else (None, "--")
                if tokens.current() in closers:
                    raise tokens.fail(f"`{short}` requires an argument")
                value = tokens.move()
            else:
                # Accept the `-s=value` form; a leading `=` is the separator, not part of the value.
                value = left[1:] if left.startswith("=") else left
                left = ""
        if tokens.parsing_argv:
            option.value = value if value is not None else True
        option.span = span
        parsed.append(option)
    return parsed


def parse_pattern(source: str | Tokens, options: list[Option]) -> Required:
    """Parse a formal usage string (or pre-spanned ``Tokens``) into a Required pattern tree."""
    tokens = source if isinstance(source, Tokens) else Tokens.from_pattern(source)
    result = parse_expr(tokens, options)
    return Required(*result)


def required_leaf_names(pattern: Pattern) -> list[str]:
    """Names of the leaves the usage always requires (outside any Optional or Either branch)."""
    names: list[str] = []

    def walk(node: Pattern, required: bool) -> None:
        if isinstance(node, BranchPattern):
            still_required = required and type(node) in (Required, OneOrMore)
            for child in node.children:
                walk(child, still_required)
        elif required and node.name is not None and node.name not in names:
            names.append(node.name)

    walk(pattern, required=True)
    return names


def _usage_lines(pattern: Pattern) -> list[Pattern]:
    """The alternative usage lines, each shaped like a branch of the top-level ``Either``.

    A lone usage line sits one ``Required`` deeper than a branch of an ``Either``, so it is unwrapped to the
    same shape: otherwise its elements are a level below where a caller looks for them, and a scan for leaves
    finds a branch instead.
    """
    if isinstance(pattern, Required) and pattern.children:
        first = pattern.children[0]
        if isinstance(first, Either):
            return first.children
        if len(pattern.children) == 1 and isinstance(first, Required):
            return [first]
    return [pattern]


def always_required_names(pattern: Pattern) -> list[str]:
    """Names EVERY usage line requires: the required leaves intersected over the alternatives.

    :func:`required_leaf_names` stops at an ``Either``, and a multi-line usage *is* one, so it answers
    "nothing" for the very case this question is asked about.
    """
    lines = _usage_lines(pattern)
    per_line = [set(required_leaf_names(line)) for line in lines]
    common = set.intersection(*per_line)
    return [name for name in required_leaf_names(lines[0]) if name in common]


def _unmet_target(node: Pattern) -> tuple[str, Span] | None:
    """The (name, span) a near-miss caret points at, seeing through groups.

    A required choice reports as ``(a|b)`` and carets the whole group: that is what the argv failed to
    supply, and blaming the leaf after it would be advice that still fails.
    """
    if isinstance(node, LeafPattern):
        return (node.name, node.span) if node.name is not None and node.span is not None else None
    if not isinstance(node, BranchPattern) or not node.children:  # pragma: no cover - no such pattern parses
        return None
    targets: list[tuple[str, Span]] = []
    for child in node.children:
        target = _unmet_target(child)
        if target is None:  # pragma: no cover - every parsed leaf carries a name and a span; a fail-safe
            return None
        targets.append(target)
    if len(targets) == 1:  # a bare repetition has no span of its own, so it borrows its child's
        name, span = targets[0]
        return name, node.span if node.span is not None else span
    joiner = "|" if isinstance(node, Either) else " "
    return "(" + joiner.join(name for name, _ in targets) + ")", node.span


def _line_partial_score(line: Pattern, argv_leaves: list[Pattern]) -> tuple[int, int, tuple[str, Span] | None]:
    """Greedily match a usage line's top-level elements against argv: (score, evidence, first unmet target).

    ``score`` ranks the lines against each other. ``evidence`` counts only matched LITERALS: a positional
    matches any token, so it says nothing about which line the user meant, and the caller needs a signal
    the missing-command penalty cannot cancel out. A group can be the unmet target just as a leaf can.
    """
    left = list(argv_leaves)
    score = 0
    evidence = 0
    unmet: tuple[str, Span] | None = None
    found_unmet = False
    for element in line.children if isinstance(line, Required) else [line]:
        if isinstance(element, LeafPattern):
            position, _node = element.single_match(left)
            if position is not None:
                score += 2 if isinstance(element, Command) else 1
                if isinstance(element, Command | Option):
                    evidence += 1
                left = left[:position] + left[position + 1 :]
            else:
                score -= 2 if isinstance(element, Command) else 0
                if not found_unmet:
                    found_unmet, unmet = True, _unmet_target(element)
        else:
            matched, reduced, _ = element.match(left, [])
            if matched:  # an Optional never fails, so this is the usual path for `[ ... ]`
                score += len(left) - len(reduced)
                left = reduced
            elif not found_unmet:  # a required group the argv cannot satisfy is itself the unmet element
                found_unmet, unmet = True, _unmet_target(element)
    return score, evidence, unmet


def nearest_usage_line(pattern: Pattern, argv_leaves: list[Pattern]) -> tuple[str, tuple[int, int], int] | None:
    """The unmet required element of the usage line the argv came closest to, with the line count.

    Every line is scored by how much of it the argv supplied, and the best one's first unmet element comes
    back as ``(name, span, line_count)`` for a caret. Fires only on a matched literal: a positional matches
    any token, so a garbage argv would otherwise resemble every line. The score cannot gate it, because a
    matched command (+2) is cancelled by the next missing one (-2) - the partial-subcommand case
    (`git remote`) the diagnostic exists for.

    A single-line usage has nothing to rank, but it still has an unmet element, so it is carets too - the
    ranking is what needs alternatives, not the caret.
    """
    lines = _usage_lines(pattern)
    ranked: list[tuple[int, int, int, tuple[str, Span] | None]] = []
    for index, line in enumerate(lines):
        score, evidence, unmet = _line_partial_score(line, argv_leaves)
        ranked.append((evidence, score, -index, unmet))  # ties break to the earliest line
    ranked.sort(key=lambda entry: (entry[0], entry[1], entry[2]), reverse=True)
    best_evidence, _score, _index, unmet = ranked[0]
    if best_evidence == 0 or unmet is None:
        return None
    name, span = unmet
    if span is None:  # pragma: no cover - only a bare Either could carry none, and `(...)` always wraps it
        return None
    return name, span, len(lines)


def parse_expr(tokens: Tokens, options: list[Option]) -> list[Pattern]:
    """expr ::= seq ( '|' seq )* ;"""
    seq = parse_seq(tokens, options)
    if tokens.current() != "|":
        return seq
    result: list[Pattern] = [Required(*seq)] if len(seq) > 1 else list(seq)
    while tokens.current() == "|":
        tokens.move()
        seq = parse_seq(tokens, options)
        result += [Required(*seq)] if len(seq) > 1 else seq
    return [Either(*result)] if len(result) > 1 else result


def parse_seq(tokens: Tokens, options: list[Option]) -> list[Pattern]:
    """seq ::= ( atom [ '...' ] )* ;"""
    result: list[Pattern] = []
    while tokens.current() not in (None, "]", ")", "|"):
        atom = parse_atom(tokens, options)
        if tokens.current() == "...":
            atom = [OneOrMore(*atom)]
            tokens.move()
        result += atom
    return result


def _span_between(opener: Span, closer: Span) -> Span:
    """Span covering an opening bracket through its closer, or None if either offset is unknown."""
    if opener is None or closer is None:
        return None
    return (opener[0], closer[1])


def parse_atom(tokens: Tokens, options: list[Option]) -> list[Pattern]:
    """atom ::= '(' expr ')' | '[' expr ']' | 'options' | long | shorts | argument | command ;"""
    token = cast("str", tokens.current())
    if token in "([":
        opener = tokens.current_span()
        tokens.move()
        pattern_type = {"(": Required, "[": Optional}[token]
        result = pattern_type(*parse_expr(tokens, options))
        result.span = _span_between(opener, tokens.current_span())
        tokens.move()  # consume the matching closer (bracket balance is checked up front)
        return [result]
    if token == "options":
        shortcut = OptionsShortcut()
        shortcut.span = tokens.current_span()
        tokens.move()
        return [shortcut]
    if token.startswith("--") and token != "--":
        return parse_long(tokens, options)
    if token.startswith("-") and token not in ("-", "--"):
        return parse_shorts(tokens, options)
    span = tokens.current_span()
    if (token.startswith("<") and token.endswith(">")) or token.isupper():
        argument = Argument(tokens.move())
        argument.span = span
        return [argument]
    command = Command(tokens.move())
    command.span = span
    return [command]


def _is_number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def parse_argv(
    tokens: Tokens,
    options: list[Option],
    options_first: bool = False,
    negative_numbers: bool = False,
    allow_abbrev: bool = True,
) -> list[Pattern]:
    """Parse the command-line argument vector.

    With ``options_first`` the grammar is
    ``argv ::= [ long | shorts ]* [ argument ]* [ '--' [ argument ]* ] ;`` and options
    must precede positionals; otherwise options and positionals may intermix. With
    ``negative_numbers`` a token like ``-3`` or ``-6.28`` is treated as a positional
    argument rather than a cluster of short options. With ``allow_abbrev`` disabled a long
    option must be written in full (no ``--ver`` -> ``--version`` de-abbreviation).
    """
    parsed: list[Pattern] = []
    current = tokens.current()
    while current is not None:
        if current == "--":
            return parsed + [Argument(None, value) for value in tokens]
        if current.startswith("--"):
            parsed += parse_long(tokens, options, allow_abbrev)
        elif current.startswith("-") and current != "-" and not (negative_numbers and _is_number(current)):
            parsed += parse_shorts(tokens, options)
        elif options_first:
            return parsed + [Argument(None, value) for value in tokens]
        else:
            parsed.append(Argument(None, tokens.move()))
        current = tokens.current()
    return parsed


def _option_chunks(doc: str) -> Iterator[str]:
    """Each ``-``-led option block from every ``options:`` section, split on its leading flag token."""
    for section in parse_section("options:", doc):
        _, _, body = section.partition(":")
        split = re.split(r"\n[ \t]*(-\S+?)", "\n" + body)[1:]
        yield from ("".join(pair) for pair in zip(split[::2], split[1::2], strict=False))


def parse_defaults(doc: str) -> list[Option]:
    """Collect option defaults from every ``options:`` section of the docstring."""
    return [Option.parse(text, doc) for text in _option_chunks(doc) if text.startswith("-")]


def parse_argument_defaults(doc: str) -> dict[str, str]:
    """Collect positional-argument defaults from every ``arguments:`` section (``<name> ... [default: v]``),
    mirroring the ``options:`` convention so an unmatched positional falls back to the value, not ``None``."""
    defaults: dict[str, str] = {}
    for section in parse_section("arguments:", doc):
        _, _, body = section.partition(":")
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            name = stripped.split(maxsplit=1)[0]
            if not ((name.startswith("<") and name.endswith(">")) or name.isupper()):
                continue
            matched = _DEFAULT_PATTERN.findall(stripped)
            if matched:
                defaults[name] = matched[0]
    return defaults


@functools.cache
def _section_pattern(name: str) -> re.Pattern[str]:
    """Compile (once per section name) the regex that captures a whole ``name`` section.

    A section's body is the indented lines under its header. But when the header keyword stands ALONE on
    its line (``usage:`` with nothing after the colon), the patterns are on the following lines - and
    Python 3.13 strips a docstring's common leading indent (gh-81283), so an inline ``\"\"\"Usage:``
    docstring arrives with those lines flush-left, the whole block dedented at once. So a bare header may
    take a flush-left body too, stopping at a blank line or another section header; ``docopt(__doc__)``
    then keeps working across 3.10-3.15. A header with its pattern text INLINE (``usage: prog ...``) keeps
    the old rule exactly - only indented continuation lines - so a flush-left line after it (prose, or a
    second section) is never swallowed.
    """
    indented = r"(?:[ \t].*(?:\n|$))*"  # zero or more indented continuation lines
    not_a_header = r"(?!(?:usage|options|arguments)\s*:)"
    flush = r"(?:(?:[ \t].*(?:\n|$))+|(?:" + not_a_header + r"\S.*(?:\n|$))+)?"
    inline = r"[^\n]*" + name + r"[ \t]*\S[^\n]*\n?" + indented  # keyword then pattern text on one line
    bare = r"[^\n]*" + name + r"[ \t]*\n?" + flush  # keyword alone on its line; body follows, any indent
    return re.compile(r"^(" + inline + r"|" + bare + r")", re.IGNORECASE | re.MULTILINE)


def parse_section(name: str, source: str) -> list[str]:
    """Return the stripped text of every section whose header contains ``name``."""
    return [section.strip() for section in _section_pattern(name).findall(source)]


def section_line_numbers(name: str, source: str) -> set[int]:
    """The 0-based line indices every ``name`` section covers - the same span :func:`parse_section` reads.

    So a caller that must agree with the parser on which lines are options (``format_usage``) asks it.
    """
    covered: set[int] = set()
    for match in _section_pattern(name).finditer(source):
        first = source.count("\n", 0, match.start())
        last = source.count("\n", 0, match.end() - 1)
        covered.update(range(first, last + 1))
    return covered


def expand_options_shortcut(pattern: Pattern, options: list[Option]) -> None:
    """Fill every ``[options]`` shortcut in ``pattern`` with the doc options it does not already name."""
    shortcuts = pattern.flat(OptionsShortcut)
    if not shortcuts:  # common case: no `[options]` shortcut, so skip the option-set walk entirely
        return
    pattern_options = set(pattern.flat(Option))
    for shortcut in shortcuts:
        fill: list[Pattern] = [option for option in options if option not in pattern_options]
        cast("OptionsShortcut", shortcut).children = fill


def single_usage_section(doc: str) -> str:
    """Return the one ``usage:`` section, raising if the doc has none or more than one."""
    sections = parse_section("usage:", doc)
    if len(sections) == 0:
        raise DocoptLanguageError(Diagnostic(summary='"usage:" (case-insensitive) not found').render())
    if len(sections) > 1:
        raise DocoptLanguageError(Diagnostic(summary='more than one "usage:" section (case-insensitive)').render())
    return sections[0]


def formal_usage(section: str) -> str:
    """Rewrite a usage section into a formal pattern with the program name as separator."""
    _, _, body = section.partition(":")
    words = body.split()
    if not words:
        raise DocoptLanguageError(Diagnostic(summary="the usage section names no program").render())
    program = words[0]
    return "( " + " ".join(") | (" if word == program else word for word in words[1:]) + " )"


def formal_tokens(section: str) -> Tokens:
    """Like ``formal_usage`` but returns spanned ``Tokens`` (each token keeps its offset in
    ``section``) so parse errors can point a caret at the offending source."""
    body_start = section.index(":") + 1
    spanned = [
        (match.group(), match.start() + body_start, match.end() + body_start)
        for match in _PATTERN_TOKEN.finditer(section[body_start:])
    ]
    if not spanned:
        raise DocoptLanguageError(Diagnostic(summary="the usage section names no program").render())
    _check_brackets(section, spanned)
    program = spanned[0][0]
    texts: list[str] = ["("]
    spans: list[Span] = [None]
    for text, start, end in spanned[1:]:
        if text == program:
            texts += [")", "|", "("]
            spans += [None, None, None]
        else:
            texts.append(text)
            spans.append((start, end))
    texts.append(")")
    spans.append(None)
    return Tokens(texts, error=DocoptLanguageError, spans=spans, text=section)
