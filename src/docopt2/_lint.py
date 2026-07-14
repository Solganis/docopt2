from __future__ import annotations

import re
from typing import TYPE_CHECKING

from docopt2._diagnostics import Caret, Diagnostic, Snippet
from docopt2._errors import DocoptLanguageError
from docopt2._parser import (
    Argument,
    BranchPattern,
    Either,
    OneOrMore,
    Option,
    OptionsShortcut,
    always_required_names,
    formal_tokens,
    parse_pattern,
    single_usage_section,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from docopt2._parser import Pattern, Span


def _variadic_units(node: Pattern) -> int:
    """Count variadic-positional groups (a ``...`` over a positional) co-occurring in one path.

    A sequence sums along its children, an Either takes the maximum across branches; each ``...``
    that wraps a positional counts as ONE unit and is not looked inside. So two SEPARATE repeats
    (``<a>... <b>...``) reach two - their token boundary is free, hence ambiguous - while a single
    ``(<a> <b>)...`` is one unit (its interleaving is fixed) and two in separate alternatives do not.
    """
    if isinstance(node, OneOrMore):
        return 1 if node.flat(Argument) else 0
    if not isinstance(node, BranchPattern):
        return 0
    if isinstance(node, Either):
        return max((_variadic_units(child) for child in node.children), default=0)
    return sum(_variadic_units(child) for child in node.children)


_DEFAULT = re.compile(r"\[default:.*?]", re.IGNORECASE)
_OPTION_LINE = re.compile(r"-\S")  # what the parser reads as an option: a dash and a NON-space


def _branch_key(branch: Pattern, usage: str) -> str:
    """What makes two alternatives the same: the source they were written from, not the node they parsed to.

    `-h | --help` is one option under its two spellings - docopt's own idiom, and the canonical naval-fate
    example - which parses to two identical leaves. `(add | add)` is the copy-paste slip, and its branches
    share their source text as well. A branch with no span (a whole usage line) falls back to its shape.
    """
    span = branch.span
    return usage[span[0] : span[1]].strip() if span is not None else repr(branch)


def _nested_eithers(node: Pattern) -> Iterator[Either]:
    """Every ``Either`` in the tree, including one nested inside another."""
    if isinstance(node, Either):
        yield node
    if isinstance(node, BranchPattern):
        for child in node.children:
            yield from _nested_eithers(child)


def _section_lines(doc: str, header: str) -> Iterator[tuple[str, int]]:
    """Yield ``(line, offset)`` for each indented body line of every ``header`` section of ``doc``."""
    pattern = re.compile(r"^[^\n]*" + header + r"[^\n]*\n((?:[ \t].*(?:\n|$))*)", re.IGNORECASE | re.MULTILINE)
    for section in pattern.finditer(doc):
        base = section.start(1)
        for line in re.finditer(r"[ \t]+\S[^\n]*", section.group(1)):
            yield line.group(), base + line.start()


def _token_span(line: str, offset: int) -> Span:
    """Span of the first token on ``line`` (a flag or an argument name), stopping before ``=``/``,``."""
    start = len(line) - len(line.lstrip())
    end = start
    while end < len(line) and not line[end].isspace() and line[end] not in ",=":
        end += 1
    return (offset + start, offset + end)


def _default_span(line: str, offset: int) -> Span:
    hit = _DEFAULT.search(line)
    return (offset + hit.start(), offset + hit.end()) if hit else None


def _warn(summary: str, doc: str, span: Span, intro: str, label: str, hint: str) -> Diagnostic:
    snippets = [Snippet(doc, intro, [Caret(span[0], span[1], label)])] if span is not None else []
    return Diagnostic(summary=summary, snippets=snippets, help=hint, level="warning")


def check(doc: str) -> list[Diagnostic]:
    """Statically lint the usage grammar itself, before any argv is parsed.

    Returns a list of ``"warning"``-level :class:`~docopt2._diagnostics.Diagnostic` for defects the
    usage message contains that :func:`~docopt2.docopt` would otherwise accept silently - an option
    declared but never usable, a ``[default: ...]`` on an always-required element, an empty
    ``[options]`` shortcut. The check is read-only: it does not affect parsing or matching. A usage
    message too malformed to parse returns no warnings (that error surfaces at parse time instead).
    """
    warnings: list[Diagnostic] = []
    declared: list[tuple[Option, Span, Span]] = []
    for line, offset in _section_lines(doc, "options:"):
        if not _OPTION_LINE.match(line.lstrip()):
            continue  # a wrapped description, or a prose bullet: `- fast, quick` is not an option
        try:
            option = Option.parse(line)
        except DocoptLanguageError:
            return []  # docopt rejects the whole message; that error is the one worth reading, not a lint
        declared.append((option, _token_span(line, offset), _default_span(line, offset)))
    options = [option for option, _name, _default in declared]
    try:
        # formal_tokens, not formal_usage: the latter builds the same tree but offsets every leaf span, and
        # the redundant-alternative rule reads the source a branch was written from.
        usage = single_usage_section(doc)
        pattern = parse_pattern(formal_tokens(usage), list(options))
    except (DocoptLanguageError, RecursionError):
        return warnings
    in_usage = {leaf.name for leaf in pattern.flat(Option)}
    required = set(always_required_names(pattern))
    has_shortcut = bool(pattern.flat(OptionsShortcut))

    for option, name_span, default_span in declared:
        if option.name not in in_usage and not has_shortcut:
            warnings.append(
                _warn(
                    f"option `{option.name}` is declared but never used",
                    doc,
                    name_span,
                    "in the options:",
                    "declared here",
                    f"add `{option.name}` to a usage line, or add `[options]` to accept it",
                )
            )
        if option.argcount and option.value is not None and option.name in required:
            warnings.append(
                _warn(
                    f"dead default on `{option.name}`, which the usage always requires",
                    doc,
                    default_span,
                    "in the options:",
                    "never applies",
                    f"make `{option.name}` optional with `[ ... ]`, or drop the default",
                )
            )
    for line, offset in _section_lines(doc, "arguments:"):
        name = line.split()[0]
        if _DEFAULT.search(line) and name in required:
            warnings.append(
                _warn(
                    f"dead default on `{name}`, which the usage always requires",
                    doc,
                    _default_span(line, offset),
                    "in the arguments:",
                    "never applies",
                    f"make `{name}` optional with `[{name}]`, or drop the default",
                )
            )
    if _variadic_units(pattern) >= 2:
        warnings.append(
            Diagnostic(
                summary="ambiguous grammar: two variadic positionals share one sequence",
                help="the token split between them is undefined; make one non-variadic, or split into branches",
                level="warning",
            )
        )
    # Not `flat(Either)`: it returns a matching node without descending into it, and a multi-line usage is
    # the outermost Either - so an `(a | a)` written inside a usage line would go unseen.
    for either in _nested_eithers(pattern):
        seen: set[str] = set()
        for branch in either.children:
            if _branch_key(branch, usage) in seen:
                warnings.append(
                    Diagnostic(
                        summary="redundant alternative: this branch repeats an earlier one",
                        help="one of the identical `|` alternatives can never be reached; remove it or fix the typo",
                        level="warning",
                    )
                )
            seen.add(_branch_key(branch, usage))
    if has_shortcut and not options:
        at = doc.lower().find("[options]")
        span = (at, at + len("[options]")) if at != -1 else None
        warnings.append(
            _warn(
                "`[options]` accepts nothing - no options are described",
                doc,
                span,
                "in the usage:",
                "expands to nothing",
                "describe options in an `Options:` section, or remove `[options]`",
            )
        )
    return warnings
