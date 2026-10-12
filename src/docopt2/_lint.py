from __future__ import annotations

import enum
import re
import types
from typing import TYPE_CHECKING, Any, Literal, Union, get_args, get_origin

from docopt2._diagnostics import Caret, Diagnostic, Snippet
from docopt2._errors import DocoptLanguageError
from docopt2._parser import (
    _CONFIG_PATTERN,
    _ENV_PATTERN,
    Argument,
    BranchPattern,
    Either,
    OneOrMore,
    Option,
    OptionsShortcut,
    always_required_names,
    formal_tokens,
    parse_defaults,
    parse_pattern,
    single_usage_section,
)
from docopt2._stub import _key_shapes
from docopt2._typed import (
    _asked,
    _field_names,
    _has_no_constructor,
    _is_optional,
    _is_pydantic,
    _key_to_field,
    _omittable_fields,
    _resolved_hints,
    _type_name,
    _unwrap_annotation,
    unbindable,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from docopt2._parser import LeafValue, Pattern, Span


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
_ANNOTATIONS = {"default": _DEFAULT, "env": _ENV_PATTERN, "config": _CONFIG_PATTERN}
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


def _sections(doc: str, header: str) -> Iterator[list[tuple[str, int]]]:
    """Yield, for every ``header`` section of ``doc``, the ``(line, offset)`` of each of its indented body lines."""
    pattern = re.compile(r"^[^\n]*" + header + r"[^\n]*\n((?:[ \t].*(?:\n|$))*)", re.IGNORECASE | re.MULTILINE)
    for section in pattern.finditer(doc):
        base = section.start(1)
        yield [(line.group(), base + line.start()) for line in re.finditer(r"[ \t]+\S[^\n]*", section.group(1))]


def _section_lines(doc: str, header: str) -> Iterator[tuple[str, int]]:
    """Yield ``(line, offset)`` for each indented body line of every ``header`` section of ``doc``."""
    for lines in _sections(doc, header):
        yield from lines


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


def _is_closed(annotation: Any) -> bool:
    """Whether ``annotation`` holds a closed set, a ``Literal`` or an ``Enum``, through ``Annotated`` and in any
    member of a union."""
    if hasattr(annotation, "__metadata__"):
        return _is_closed(get_args(annotation)[0])
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is types.UnionType or origin is Union:
        return any(_is_closed(member) for member in args)
    return origin is Literal or (origin is None and isinstance(annotation, type) and issubclass(annotation, enum.Enum))


def _yields(yielded: LeafValue, given: bool, annotation: Any) -> list[Any]:
    """Every kind of value an element of this fixed value can hand the binder that is no text of the user's.

    A flag hands it ``True``, and ``False`` unless the usage always requires the flag. A counted flag hands it
    a count, and one and two stand for every count, beside nought unless the usage always requires it. That
    holds for every type but a closed set, the one way a type tells counts apart. Which counts a usage can
    reach is not worked out, so a counted flag typed with a closed set is not asked at all.
    """
    if type(yielded) is bool:
        return [True] if given else [False, True]
    if type(yielded) is int and not _is_closed(annotation):
        return [1, 2] if given else [0, 1, 2]
    return []


def _turned_away(raw: object, annotation: Any) -> str | None:
    """Why the binder turns ``raw`` away from a field of ``annotation``, or None where it takes it."""
    refused = _asked(raw, annotation)[1]
    if isinstance(refused, DocoptLanguageError):
        raise refused
    return None if refused is None else f"the element yields `{raw!r}`, which {_type_name(annotation)} does not take"


def _misfit(yielded: LeafValue, given: bool, annotation: Any) -> str | None:
    """Why a field of ``annotation`` cannot hold what an element of this fixed value yields, or None.

    The binder's own coercion is asked, so an ``Enum`` of the schema is called with the values tried. A shape
    it refuses, a list for an element that is not repeated or a flag for a field of text, is a misfit
    whatever the value. A value it refuses is a misfit only where it refuses every value the element can
    yield: a text is the user's to correct. A counted flag typed with a closed set is judged by its shape
    alone: the set is a limit the author put on the count.
    """
    probes = _yields(yielded, given, annotation)
    if not probes:
        shape = _asked(["x"] if type(yielded) is list else "x", annotation)[1]
        return str(shape) if isinstance(shape, DocoptLanguageError) else None
    try:
        refusals = [_turned_away(raw, annotation) for raw in probes]
    except DocoptLanguageError as shape:
        return str(shape)
    return refusals[0] if all(refusals) else None


def _unfit(summary: str, usage: str = "", at: Span = None, label: str = "", **lines: str) -> Diagnostic:
    snippets = [Snippet(usage, "in the usage:", [Caret(at[0], at[1], label)])] if at is not None else []
    return Diagnostic(summary=summary, snippets=snippets, level="error", **lines)


def _schema_findings(doc: str, schema: type[Any]) -> list[Diagnostic]:
    """Where ``schema`` disagrees with the usage, each a case in which binding some argv the usage accepts would
    raise or hand a field a value of another type, whatever the user typed."""
    refused = unbindable(schema)
    if refused is not None:
        return [_unfit(refused)]
    name = schema.__name__
    if _is_pydantic(schema):
        unchecked = f"schema `{name}` is a pydantic model, which binds by rules of its own: it was not checked"
        return [Diagnostic(summary=unchecked, level="warning")]
    try:
        shapes = _key_shapes(doc)
    except (DocoptLanguageError, RecursionError):
        unread = f"the usage message does not parse: schema `{name}` was not checked"
        return [Diagnostic(summary=unread, level="warning")]
    try:
        hints = _resolved_hints(schema)
        fields = _field_names(schema, hints)
    except Exception as unresolved:  # whatever evaluating the annotations of a user's class raises
        return [_unfit(f"the annotations of schema `{name}` do not resolve", note=f"{unresolved}")]
    usage = single_usage_section(doc)
    found: list[Diagnostic] = []
    keys: dict[str, str] = {}
    for key, (_yielded, _given, written) in shapes.items():
        field = _key_to_field(key)
        if field in keys:
            both = f"usage elements `{keys[field]}` and `{key}` both map to field `{field}`"
            found.append(_unfit(both, usage, written, "the second of them", help="rename one of the two elements"))
        keys.setdefault(field, key)
    if fields and _has_no_constructor(schema):
        plain = f"schema `{name}` is a plain class with no constructor to take its fields"
        found.append(_unfit(plain, help="make it a dataclass or subclass `Cli`"))
    omittable = _omittable_fields(schema, fields)
    for field in fields:
        if field not in keys:
            found.append(_unfit(f"schema field `{field}` has no matching usage element"))
            continue
        key, annotation = keys[field], _unwrap_annotation(hints[field])
        yielded, given, written = shapes[key]
        if yielded is None and not given and not _is_optional(annotation) and field not in omittable:
            absent = f"usage element `{key}` may be absent, but field `{field}` is not optional"
            advice = f"annotate it as `{field}: ... | None` or give it a default"
            found.append(_unfit(absent, usage, written, "may be absent", help=advice))
        misfit = _misfit(yielded, given, annotation)
        if misfit is not None:
            summary, label = f"field `{field}` does not fit usage element `{key}`", f"typed as {_type_name(annotation)}"
            found.append(_unfit(summary, usage, written, label, note=misfit))
    return found


def check(doc: str, schema: type[Any] | None = None) -> list[Diagnostic]:
    """Statically lint the usage grammar itself, before any argv is parsed.

    Returns a list of ``"warning"``-level diagnostics for defects the usage message contains that
    [`docopt`][docopt2.docopt] would otherwise accept silently: an option declared but never usable, a
    ``[default: ...]`` on an always-required element, an empty ``[options]`` shortcut.

    The check is read-only and does not affect parsing or matching. A usage message that does not parse is
    reported as a single ``"error"``, the one [`docopt`][docopt2.docopt] raises for it at every run, and
    nothing else in it is looked at.

    With ``schema``, a dataclass, a ``TypedDict`` or a ``Cli`` subclass, the list also holds an ``"error"`` for
    every way the schema disagrees with the usage: a field with no element, two elements for one field, an
    element that may be absent for a field that is not optional, a type that cannot hold what the element
    yields. Binding raises the last two only on the argv that reaches them. A pydantic model, and a schema
    whose usage message does not parse, get one ``"warning"`` that says they were not checked.

    To judge a type the check calls the coercion that binding uses, so an ``Enum`` of the schema is called with
    the values tried, and whatever its ``_missing_`` does is done. A counted flag typed with a closed set,
    ``Literal[0, 1, 2]`` on ``[-v]...``, is judged by its shape alone: the set is the author's limit on the count.

    Fields are held against elements, and no more than that: a default is not held against its own annotation,
    and the schema is not constructed, so what its own ``__init__`` takes or refuses is not looked at. The
    schema is held against the whole usage. A handler of a ``Dispatch`` table binds its schema only on the
    lines of its command, so an element those lines always give can be reported as one that may be absent.
    """
    found = _usage_findings(doc)
    return found if schema is None else [*found, *_schema_findings(doc, schema)]


def _usage_findings(doc: str) -> list[Diagnostic]:
    try:
        # As docopt() reads the doc before any argv, so what is raised here is raised at every run. formal_tokens,
        # not formal_usage: the latter offsets every leaf span, and a rule below reads the source of a branch.
        usage = single_usage_section(doc)
        read = parse_defaults(doc)
        describes_options = bool(read)  # asked now: the read below adds the options that only the usage names
        pattern = parse_pattern(formal_tokens(usage), read)
    except DocoptLanguageError as refused:
        return [refused.diagnostic or Diagnostic(summary=str(refused))]
    warnings: list[Diagnostic] = []
    declared: list[tuple[Option, Span, Span]] = []
    described: list[tuple[Option, list[tuple[str, int]]]] = []
    for section in _sections(doc, "options:"):
        description: list[tuple[str, int]] | None = None  # of the option above, in this section
        for line, offset in section:
            if not _OPTION_LINE.match(line.lstrip()):
                if description is not None:
                    description.append((line, offset))
                continue  # a wrapped description, or a prose bullet: `- fast, quick` is not an option
            try:
                option = Option.parse(line)
            except DocoptLanguageError:
                description = None  # the parser took this option with the lines under it: it has no line of its own
                continue
            declared.append((option, _token_span(line, offset), _default_span(line, offset)))
            description = [(line, offset)]
            described.append((option, description))
    for option, lines in described:
        for kind, annotation in _ANNOTATIONS.items():
            written = [(at + hit.start(), at + hit.end()) for line, at in lines for hit in annotation.finditer(line)]
            if len(written) > 1:
                warnings.append(
                    _warn(
                        f"option `{option.name}` has more than one `[{kind}: ...]`",
                        doc,
                        written[1],
                        "in the options:",
                        "one too many",
                        f"keep a single `[{kind}: ...]` on `{option.name}`",
                    )
                )
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
    if has_shortcut and not describes_options:
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
