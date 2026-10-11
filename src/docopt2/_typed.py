from __future__ import annotations

import enum
import functools
import sys
import types
import typing
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Final,
    Literal,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from docopt2._errors import DocoptExit, DocoptLanguageError

if TYPE_CHECKING:
    import weakref
    from collections.abc import Callable, Mapping, Sequence

SchemaT = TypeVar("SchemaT")

_BUILTIN_SCALARS: Final = (int, float)
_SCALAR_HOMES: Final = frozenset({"pathlib", "decimal", "uuid", "datetime"})
# (home module, class, the classmethod that parses a string - or "" where calling the class does)
_HOMED_SCALARS: Final = (
    ("pathlib", "Path", ""),
    ("decimal", "Decimal", ""),
    ("uuid", "UUID", ""),
    ("datetime", "datetime", "fromisoformat"),
    ("datetime", "date", "fromisoformat"),
    ("datetime", "time", "fromisoformat"),
)


@functools.cache
def _homed_coercers(imported: frozenset[str]) -> dict[Any, Callable[[Any], Any]]:
    """The coercers of ``_HOMED_SCALARS`` whose home module is in ``imported``, in table order."""
    table: dict[Any, Callable[[Any], Any]] = {}
    for home, name, parser in _HOMED_SCALARS:
        if home in imported:
            scalar = getattr(sys.modules[home], name)
            table[scalar] = getattr(scalar, parser) if parser else scalar
    return table


def _scalar_coercers() -> dict[Any, Callable[[Any], Any]]:
    """The annotations whose coercion is nothing but "call this on the value", the whole CLOSED set.

    Data rather than an if-chain, so the documented table can be held against the real set: `_coerce`
    claims a CLOSED set, and a closed set that only the code knows drifts from the docs the moment a type
    is added. The forms with their own semantics (str, bool, Enum, list, Literal, `| None`) stay spelled
    out in `_coerce`.

    This imports all four home modules. `_coerce` asks `_coercers_in_reach` first and comes here only
    before it refuses an annotation, and so does the gate that holds the documented table against this one.
    """
    for home in _SCALAR_HOMES:
        __import__(home)
    return {scalar: scalar for scalar in _BUILTIN_SCALARS} | _homed_coercers(_SCALAR_HOMES)


def _coercers_in_reach() -> dict[Any, Callable[[Any], Any]]:
    """The part of the homed table an annotation is expected to name right now.

    A class is rarely an annotation before its module is imported, so the home modules are looked up and
    not imported: importing all four was 3.9 of the 9.0 ms a first call with a schema took. A name blocked
    with ``sys.modules[name] = None`` is not imported either. `_coerce` asks the whole table before it
    refuses, so an annotation this one misses is still recognized.
    """
    modules = sys.modules
    return _homed_coercers(frozenset(home for home in _SCALAR_HOMES if modules.get(home) is not None))


@functools.cache
def _markers(extensions_imported: bool) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """``Required`` and ``NotRequired`` as ``typing`` has them (neither below 3.11), then as
    ``typing_extensions`` does where it is imported."""
    modules = [typing, sys.modules["typing_extensions"]] if extensions_imported else [typing]
    required = tuple(marker for module in modules if (marker := getattr(module, "Required", None)) is not None)
    optional = tuple(marker for module in modules if (marker := getattr(module, "NotRequired", None)) is not None)
    return required, optional


def _optionality_markers() -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """The ``Required`` / ``NotRequired`` markers a TypedDict field can carry, from both sources.

    ``typing`` has them from 3.11; ``typing_extensions`` is the only source on the 3.10 floor, and a
    caller may use it on any version. It is looked up and never imported: a schema cannot carry a marker
    of a module nobody imported, and importing it was 4.4 of the 9.0 ms a first call with a schema took.
    """
    return _markers("typing_extensions" in sys.modules)


@functools.cache
def _hints_cache() -> weakref.WeakKeyDictionary[type[Any], dict[str, Any]]:
    """One memo of resolved hints per schema type. The keys are weak, so a dynamically built schema can be
    collected, unless its own hints refer back to it.

    Built on first use: `weakref` was 0.6 of the 11.3 ms `import docopt2` took, and only a schema asks.
    """
    import weakref  # deferred: see the docstring

    return weakref.WeakKeyDictionary()


def _resolved_hints(schema: type[Any]) -> dict[str, Any]:
    """Return ``get_type_hints(schema, include_extras=True)``, cached per schema type.

    get_type_hints (compiling the forward refs from `from __future__ import annotations`) dominates
    binding cost, and annotations are static.
    """
    cache = _hints_cache()
    cached = cache.get(schema)
    if cached is None:
        cached = get_type_hints(schema, include_extras=True)
        cache[schema] = cached
    return cached


def _key_to_field(key: str) -> str:
    """Map a docopt key ("--foo-bar", "<input file>", "NAME", "add") to a Python field."""
    core = key
    if core.startswith("--"):
        core = core[2:]
    elif core.startswith("-"):
        core = core[1:]
    if core.startswith("<") and core.endswith(">"):
        core = core[1:-1]
    return core.lower().replace("-", "_").replace(" ", "_")


_WORD_PUNCTUATION = "_./@%+,-"


def _closed_values(annotation: Any) -> list[Any]:
    """The values ``annotation`` takes where it is a closed set, a ``Literal`` or an ``Enum``, else none.

    Read the way ``_coerce`` reads it: through ``Annotated``, beside ``None``, and as the element of a list.
    """
    if hasattr(annotation, "__metadata__"):
        return _closed_values(get_args(annotation)[0])
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is types.UnionType or origin is Union:
        return _closed_values(next((arg for arg in args if arg is not type(None)), str))
    if origin is list:
        return _closed_values(args[0]) if args else []
    if origin is Literal:
        return list(args)
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return [member.value for member in annotation]
    return []


def _is_pydantic(schema: type[Any]) -> bool:
    return callable(getattr(schema, "model_validate", None))


def _declared(schemas: Sequence[type[Any]]) -> dict[str, list[Any]]:
    """The annotations each field name is declared with across ``schemas``, read as declaring nothing where they
    do not resolve.

    A pydantic model takes an argv text by rules of its own, a ``Literal[1]`` refuses the text ``1``. So only
    its closed sets of strings are read as closed, where its rules and this module's agree.
    """
    declared: dict[str, list[Any]] = {}
    for schema in schemas:
        try:
            hints = _resolved_hints(schema)
            fields = _field_names(schema, hints)
        except Exception:  # a Tab press must not raise into the shell, whatever the annotations do
            continue
        for name in fields:
            annotation = _unwrap_annotation(hints[name])
            if _is_pydantic(schema) and not all(isinstance(value, str) for value in _closed_values(annotation)):
                annotation = str
            declared.setdefault(name, []).append(annotation)
    return declared


def field_takes(schema: type[Any]) -> Callable[[str, object], bool]:
    """Whether a text is one the field of that name coerces, as binding ``schema`` would coerce it.

    A field the schema does not declare takes any text. So does every field of a pydantic model: the model
    binds itself, validators included, and what it refuses cannot be told from its annotations.
    """
    declared = {} if _is_pydantic(schema) else _declared([schema])
    return lambda name, text: all(_takes(text, annotation) for annotation in declared.get(name, ()))


def field_choices(schemas: Sequence[type[Any]]) -> dict[str, list[str]]:
    """For each field of ``schemas`` that takes a closed set of values, the argv texts it accepts.

    A text is kept only where it is one plain word and the coercion of the field takes it, in every schema
    that declares the field: whichever of them binds the result, it binds a value that was offered. A schema
    whose annotations do not resolve is read as declaring nothing.
    """
    found: dict[str, list[str]] = {}
    for name, declarations in _declared(schemas).items():
        closed = [str(value) for annotation in declarations for value in _closed_values(annotation)]
        texts = list(dict.fromkeys(closed))
        kept = [text for text in texts if all(_is_offerable(text, annotation) for annotation in declarations)]
        if kept:
            found[name] = kept
    return found


def _is_offerable(text: str, annotation: Any) -> bool:
    """Whether ``text`` is one plain word that the coercion of ``annotation`` takes, alone or as a list's element.

    A plain word is letters, digits and ``_ . / @ % + , -``, not led by a dash: nothing a shell expands,
    splits or breaks a word at, and nothing an argv reads as an option.
    """
    plain = all(character.isalnum() or character in _WORD_PUNCTUATION for character in text)
    if not text or text.startswith("-") or not plain:
        return False
    return _takes(text, annotation)


def _takes(text: object, annotation: Any) -> bool:
    """Whether the coercion of ``annotation`` takes ``text``, alone or as the element of a list."""
    return _coerces(text, annotation) or _coerces([text], annotation)


# what a coercer raises for a value it refuses. AttributeError is `UUID(True)`, a flag handed to a type of texts
_REFUSALS: Final = (ValueError, TypeError, ArithmeticError, AttributeError)


def _attempt(value: Any, annotation: Any) -> tuple[Any, Exception | None]:
    """``value`` coerced to ``annotation``, or why it was not."""
    try:
        return _coerce(value, annotation), None
    except (*_REFUSALS, DocoptLanguageError) as refused:
        return None, refused


def _coerce_each(values: list[Any], inner: Any) -> list[Any]:
    """Each of ``values`` coerced to ``inner``. A refusal carries the value that was refused, its place among
    them and the type that refused it, so that nothing is coerced again to find them."""
    coerced: list[Any] = []
    try:
        coerced.extend(_coerce(item, inner) for item in values)
    except _REFUSALS as refused:
        at = len(coerced)  # extend() keeps what it took before the value that was refused
        setattr(refused, "_refused_item", (at, values[at], inner))  # noqa: B010 - an attribute no exception declares
        raise
    return coerced


def _coerce_union(value: Any, members: list[Any]) -> Any:
    """``value`` bound by a union of several types: left to right, by the first member that takes it.

    Each member is asked once. Where none takes the value, the first that refused the value and not its shape
    is the one heard, so that a text of the user's is reported as theirs.
    """
    refusals = []
    for member in members:
        bound, refused = _attempt(value, member)
        if refused is None:
            return bound
        refusals.append(refused)
    raise next((refused for refused in refusals if not isinstance(refused, DocoptLanguageError)), refusals[-1])


def _coerces(value: Any, annotation: Any) -> bool:
    return _attempt(value, annotation)[1] is None


_UNPARSEABLE = object()  # a sentinel distinct from every real choice, so a failed parse never matches


def _parsed_as(value: Any, target: type) -> Any:
    """``value`` parsed to ``target``, or the ``_UNPARSEABLE`` sentinel when it cannot be."""
    try:
        return target(value)
    except (ValueError, TypeError):
        return _UNPARSEABLE


def _coerce_choice(value: Any, choices: Sequence[Any], select: Callable[[Any], Any], message: str) -> Any:
    """Match ``value`` (an argv string) against a closed set of ``choices``, then return ``select(choice)``.

    argv gives a string, but the choices may be numbers (``Literal[80, 443]``, an ``IntEnum``). A direct
    membership test misses those, so the string is also parsed to each choice's own type and compared -
    ``"80"`` matches the literal ``80``. ``select`` maps the matched choice to what the caller wants back
    (the literal itself, or an enum member). Raises ``ValueError(message)`` when nothing matches.
    """
    if value in choices:
        return select(choices[choices.index(value)])  # the choice, not what equals it: a flag's `True` is no `1`
    for choice in choices:
        if _parsed_as(value, type(choice)) == choice:
            return select(choice)
    raise ValueError(message)


def _spelled(annotation: Any) -> str:
    """An annotation as its author wrote it: a class by its name, anything else by its repr."""
    return annotation.__name__ if get_origin(annotation) is None and isinstance(annotation, type) else repr(annotation)


def _coerce(value: Any, annotation: Any) -> Any:
    """Coerce a docopt-native value to the field's declared type (closed set)."""
    if value is None:
        return None
    if hasattr(annotation, "__metadata__"):  # Annotated[T, ...] nested in a Union or list; unwrap to T
        return _coerce(value, get_args(annotation)[0])
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is types.UnionType or origin is Union:
        members = [arg for arg in args if arg is not type(None)] or [str]
        return _coerce(value, members[0]) if len(members) == 1 else _coerce_union(value, members)
    if origin is list or annotation is list:
        if not isinstance(value, list):
            raise DocoptLanguageError(
                f"the schema type {_spelled(annotation)} is a list, but this usage element is not repeated; "
                "mark it with `...` to repeat, or use a scalar type"
            )
        inner = args[0] if args else str
        return _coerce_each(value, inner)
    if isinstance(value, list):
        raise DocoptLanguageError(
            f"a repeated usage element yields a list, but the schema type {_spelled(annotation)} is not a list; "
            "use list[...]"
        )
    if origin is Literal:
        return _coerce_choice(value, args, lambda literal: literal, f"{value!r} is not one of {args!r}")
    if annotation is bool:
        if isinstance(value, str):
            raise DocoptLanguageError(
                f"a bool field maps to a flag, but the usage element yields the string {value!r}; use a flag or str"
            )
        return bool(value)
    if annotation is str:
        return value
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        try:
            return annotation(value)  # a str-valued member matches the argv string directly
        except ValueError:
            # An int/float-valued enum (e.g. IntEnum) is keyed by a number, but argv is a string. Try the
            # string parsed to each member value's type, then map the matched value back to its member.
            member_values = [member.value for member in annotation]
            message = f"{value!r} is not a valid {annotation.__name__}"
            return annotation(_coerce_choice(value, member_values, lambda matched: matched, message))
    for builtin in _BUILTIN_SCALARS:
        if annotation is builtin:
            return builtin(value)
    # Iterated, not looked up, so an unhashable annotation reaches the "unsupported" error below rather
    # than raising TypeError from the dict lookup itself.
    for supported, coercer in _coercers_in_reach().items():
        if annotation is supported:
            return coercer(value)
    # the whole table before refusing: a class can outlive its home in sys.modules, or come from `_datetime`
    for supported, coercer in _scalar_coercers().items():
        if annotation is supported:
            return coercer(value)
    raise DocoptLanguageError(f"typed docopt cannot coerce to unsupported annotation {_spelled(annotation)}")


def _is_dataclass(schema: type[Any]) -> bool:
    """Whether ``schema`` is a dataclass - the dunder ``dataclasses.is_dataclass`` itself looks for.

    Asked directly so the module is not imported: `dataclasses` drags in `inspect`, and the pair is a
    quarter of what importing docopt2 costs, on every run of every CLI, schema or no schema.
    """
    return hasattr(schema, "__dataclass_fields__")


def _is_bound(hint: Any) -> bool:
    """Whether a dataclass annotation names a value its ``__init__`` takes: a field or an InitVar, not a ClassVar."""
    return get_origin(hint) is not ClassVar and hint is not ClassVar


def _field_names(schema: type[Any], hints: dict[str, Any]) -> list[str]:
    """The names to bind on ``schema``, excluding ClassVars, dunders, and non-fields.

    A single leading underscore is kept: a positional ``<_x>`` maps to the field ``_x``, which a dataclass
    schema already binds, so a plain/``Cli`` schema must too. Only dunders (``__cli_doc__``) are dropped.
    """
    if _is_dataclass(schema):
        declared = schema.__dataclass_fields__  # dataclasses.fields() leaves the init-only ones out
        return [name for name in hints if name in declared and declared[name].init and _is_bound(hints[name])]
    if _is_typeddict(schema):
        return list(hints)
    return [
        name
        for name, annotation in hints.items()
        if not name.startswith("__") and get_origin(annotation) is not ClassVar
    ]


def _bind_pydantic(parsed: Mapping[str, Any], schema: type[SchemaT], validator: Any) -> SchemaT:
    """Delegate to pydantic's ``model_validate`` (it coerces itself); keys are filtered to the model's
    field names and aliases (pydantic validates by alias), dropping elements the model does not declare."""
    accepted: set[str] = set()
    for name, field_info in getattr(schema, "model_fields", {}).items():
        accepted.add(name)
        alias = getattr(field_info, "alias", None)
        if alias is not None:
            accepted.add(alias)
    remapped = {
        field: value
        for field, value in ((_key_to_field(key), value) for key, value in parsed.items())
        if field in accepted
    }
    return cast("SchemaT", validator(remapped))


def _has_no_constructor(schema: type[SchemaT]) -> bool:
    """Whether ``schema`` is a class that defines no construction of its own, and so takes no fields."""
    inherited = (schema.__init__ is object.__init__, schema.__new__ is object.__new__)
    return all(inherited) and type(schema).__call__ is type.__call__


def _is_optional(annotation: Any) -> bool:
    if get_origin(annotation) in (types.UnionType, Union):
        return type(None) in get_args(annotation)
    return False


def _is_typeddict(schema: type[Any]) -> bool:
    # typing.is_typeddict misses a typing_extensions.TypedDict on 3.10; the dunder is on every TypedDict.
    return hasattr(schema, "__required_keys__")


def _typeddict_optional_keys(schema: type[Any]) -> set[str]:
    # From __total__ + per-field Required/NotRequired, not __optional_keys__ (misses stringized wrappers).
    required_markers, not_required_markers = _optionality_markers()
    total = getattr(schema, "__total__", True)
    optional: set[str] = set()
    for name, annotation in _resolved_hints(schema).items():
        origin = get_origin(annotation)
        if origin in required_markers:
            continue
        if origin in not_required_markers or not total:
            optional.add(name)
    return optional


def _omittable_fields(schema: type[Any], field_names: list[str]) -> set[str]:
    """Fields that may be left out when their value is None (default, or NotRequired)."""
    if _is_dataclass(schema):
        import dataclasses  # deferred; only a real dataclass schema pays for it

        return {
            field.name
            for field in schema.__dataclass_fields__.values()  # dataclasses.fields() leaves the init-only ones out
            if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING
        }
    if _is_typeddict(schema):
        return _typeddict_optional_keys(schema)
    # A plain (Cli-style) class carries defaults as class attributes.
    return {name for name in field_names if hasattr(schema, name)}


def _unwrap_annotation(annotation: Any) -> Any:
    # include_extras=True keeps Required/NotRequired and Annotated wrappers (get_type_hints does not
    # strip typing_extensions' markers on 3.10); coerce the underlying type.
    dataclasses = sys.modules.get("dataclasses")  # an InitVar cannot be an annotation before its module is imported
    if dataclasses is not None and isinstance(annotation, dataclasses.InitVar):
        annotation = annotation.type
    required_markers, not_required_markers = _optionality_markers()
    origin = get_origin(annotation)
    if origin in required_markers or origin in not_required_markers:
        annotation = get_args(annotation)[0]
    if hasattr(annotation, "__metadata__"):
        annotation = get_args(annotation)[0]
    return annotation


def _type_name(annotation: Any) -> str:
    """A short, readable name for the target type in a coercion-failure message ('int', 'list[int]').

    A closed set of choices (a ``Literal`` or an ``Enum``) is rendered as ``one of `a`, `b`, `c```, so the
    diagnostic lists the valid values instead of a bare type name.
    """
    if get_origin(annotation) is Literal:
        return "one of " + ", ".join(f"`{arg}`" for arg in get_args(annotation))
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return "one of " + ", ".join(f"`{member.value}`" for member in annotation)
    if get_origin(annotation) is not None:  # a parameterized generic: keep its argument (list[int], not list)
        return str(annotation)
    return getattr(annotation, "__name__", str(annotation))


class _CoercionError(DocoptExit):
    """A user value that cannot be coerced to its declared field type.

    Carries the pieces docopt()/Dispatch need to render a two-span diagnostic (the usage element, the
    raw value, the expected type); ``str()`` is a usable message on its own for a direct bind call.

    Of a repeated element ``raw`` is the one value refused, ``index`` its place among the values, ``expected``
    the type of one value and ``declared`` the type of the field.
    """

    def __init__(
        self, key: str, raw: Any, expected: str, index: int | None = None, declared: str | None = None
    ) -> None:
        self.key = key
        self.raw = raw
        self.expected = expected
        self.index = index
        self.declared = declared or expected
        super().__init__(f"invalid value for {key}: {raw!r} (expected {expected})")


def _refusal(key: str, raw: Any, annotation: Any, refused: BaseException) -> _CoercionError:
    """The refusal of ``raw`` by ``annotation``: of a list, of the one value that ``_coerce_each`` named."""
    declared = _type_name(annotation)
    named = getattr(refused, "_refused_item", None)
    if named is None:
        return _CoercionError(key, raw, declared)
    at, item, element = named
    return _CoercionError(key, item, _type_name(element), at, declared)


def bind_schema(parsed: Mapping[str, Any], schema: type[SchemaT]) -> SchemaT:
    """Bind a parsed docopt result onto ``schema``.

    Args:
        parsed: The docopt result mapping (keys like "--flag", "<arg>", "command").
        schema: A dataclass, a TypedDict, or a pydantic model.

    Returns:
        An instance of ``schema`` with values coerced to the declared field types.

    Raises:
        DocoptLanguageError: The schema and usage message disagree (a field has no
            matching usage element, two elements collide on one field, or a field uses
            an unsupported annotation), or the schema is a plain class with no
            constructor to take its fields.
        DocoptExit: A user-supplied value cannot be coerced to the declared type.
    """
    # Reflective pydantic detection: pydantic is never imported, so it stays optional.
    validator = getattr(schema, "model_validate", None)
    if callable(validator):
        return _bind_pydantic(parsed, schema, validator)

    by_field: dict[str, tuple[str, Any]] = {}
    for key, value in parsed.items():
        field = _key_to_field(key)
        if field in by_field:
            existing = by_field[field][0]
            raise DocoptLanguageError(f"usage elements {existing!r} and {key!r} both map to field {field!r}")
        by_field[field] = (key, value)

    hints = _resolved_hints(schema)
    field_names = _field_names(schema, hints)
    omittable = _omittable_fields(schema, field_names)
    values: dict[str, Any] = {}
    for name in field_names:
        if name not in by_field:
            raise DocoptLanguageError(f"schema field {name!r} has no matching usage element")
        key, raw = by_field[name]
        annotation = _unwrap_annotation(hints[name])
        if raw is None and not _is_optional(annotation):
            if name in omittable:
                continue
            raise DocoptLanguageError(
                f"usage element {key!r} may be absent but field {name!r} is not optional; "
                f"annotate it as `{name}: ... | None` or give it a default"
            )
        try:
            values[name] = _coerce(raw, annotation)
        except _REFUSALS as exc:
            raise _refusal(key, raw, annotation, exc) from exc
    try:
        return schema(**values)
    except TypeError as exc:
        if _has_no_constructor(schema):  # a TypeError out of the user's own construction is theirs
            raise DocoptLanguageError(
                f"schema `{schema.__name__}` is a plain class with no constructor to take its fields; "
                "make it a dataclass or subclass `Cli`"
            ) from exc
        raise
