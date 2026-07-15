from __future__ import annotations

import enum
import functools
import sys
import types
import weakref
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
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
    from collections.abc import Callable, Mapping, Sequence

SchemaT = TypeVar("SchemaT")


@functools.cache
def _scalar_coercers() -> dict[Any, Callable[[Any], Any]]:
    """The annotations whose coercion is nothing but "call this on the value".

    Data rather than an if-chain, so the documented table can be held against the real set: `_coerce`
    claims a CLOSED set, and a closed set that only the code knows drifts from the docs the moment a type
    is added. The forms with their own semantics (str, bool, Enum, list, Literal, `| None`) stay spelled
    out in `_coerce`.

    Built on first use, not at import: `datetime`, `decimal`, `pathlib` and `uuid` together are most of
    what importing docopt2 costs, and a docopt() call without a schema never coerces anything at all.
    """
    from datetime import date, datetime, time  # deferred: see the docstring
    from decimal import Decimal  # deferred: see the docstring
    from pathlib import Path  # deferred: see the docstring
    from uuid import UUID  # deferred: see the docstring

    return {
        int: int,
        float: float,
        Path: Path,
        Decimal: Decimal,
        UUID: UUID,
        datetime: datetime.fromisoformat,
        date: date.fromisoformat,
        time: time.fromisoformat,
    }


@functools.cache
def _optionality_markers() -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """The ``Required`` / ``NotRequired`` markers a TypedDict field can carry, from both sources.

    ``typing`` has them from 3.11; ``typing_extensions`` is the only source on the 3.10 floor, and a
    caller may use it on any version. It is looked up on first use, not at import: it sits in most
    environments as somebody else's dependency, it drags in `inspect`, and together they cost more than
    the rest of docopt2 put together - for a marker only a TypedDict schema can even carry.
    """
    required: tuple[Any, ...] = ()
    not_required: tuple[Any, ...] = ()
    if sys.version_info >= (3, 11):  # pragma: no branch - always taken on the interpreter the suite runs under
        from typing import NotRequired, Required  # deferred: see the docstring

        required, not_required = (Required,), (NotRequired,)
    try:
        from typing_extensions import NotRequired as TeNotRequired  # deferred: see the docstring
        from typing_extensions import Required as TeRequired  # deferred: see the docstring
    except ImportError:  # pragma: no cover - typing_extensions is optional
        return required, not_required
    return (*required, TeRequired), (*not_required, TeNotRequired)


# get_type_hints (compiling the forward refs from `from __future__ import annotations`) dominates
# binding cost, but annotations are static, so memoize per type; a WeakKeyDictionary keeps a
# dynamically built schema collectable rather than pinning it forever.
_HINTS_CACHE: weakref.WeakKeyDictionary[type[Any], dict[str, Any]] = weakref.WeakKeyDictionary()


def _resolved_hints(schema: type[Any]) -> dict[str, Any]:
    """Return ``get_type_hints(schema, include_extras=True)``, cached per schema type."""
    cached = _HINTS_CACHE.get(schema)
    if cached is None:
        cached = get_type_hints(schema, include_extras=True)
        _HINTS_CACHE[schema] = cached
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
        return select(value)
    for choice in choices:
        if _parsed_as(value, type(choice)) == choice:
            return select(choice)
    raise ValueError(message)


def _coerce(value: Any, annotation: Any) -> Any:
    """Coerce a docopt-native value to the field's declared type (closed set)."""
    if value is None:
        return None
    if hasattr(annotation, "__metadata__"):  # Annotated[T, ...] nested in a Union or list; unwrap to T
        return _coerce(value, get_args(annotation)[0])
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is types.UnionType or origin is Union:
        inner = next((arg for arg in args if arg is not type(None)), str)
        return _coerce(value, inner)
    if origin is Literal:
        return _coerce_choice(value, args, lambda literal: literal, f"{value!r} is not one of {args!r}")
    if origin is list or annotation is list:
        if not isinstance(value, list):
            raise DocoptLanguageError(
                f"the schema type {annotation!r} is a list, but this usage element is not repeated; "
                "mark it with `...` to repeat, or use a scalar type"
            )
        inner = args[0] if args else str
        return [_coerce(item, inner) for item in value]
    if isinstance(value, list):
        raise DocoptLanguageError(
            f"a repeated usage element yields a list, but the schema type {annotation!r} is not a list; use list[...]"
        )
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
    # Iterated, not looked up, so an unhashable annotation reaches the "unsupported" error below rather
    # than raising TypeError from the dict lookup itself.
    for supported, coercer in _scalar_coercers().items():
        if annotation is supported:
            return coercer(value)
    raise DocoptLanguageError(f"typed docopt cannot coerce to unsupported annotation {annotation!r}")


def _is_dataclass(schema: type[Any]) -> bool:
    """Whether ``schema`` is a dataclass - the dunder ``dataclasses.is_dataclass`` itself looks for.

    Asked directly so the module is not imported: `dataclasses` drags in `inspect`, and the pair is a
    quarter of what importing docopt2 costs, on every run of every CLI, schema or no schema.
    """
    return hasattr(schema, "__dataclass_fields__")


def _field_names(schema: type[Any], hints: dict[str, Any]) -> list[str]:
    """The names to bind on ``schema``, excluding ClassVars, dunders, and non-fields.

    A single leading underscore is kept: a positional ``<_x>`` maps to the field ``_x``, which a dataclass
    schema already binds, so a plain/``Cli`` schema must too. Only dunders (``__cli_doc__``) are dropped.
    """
    if _is_dataclass(schema):
        import dataclasses  # deferred; only a real dataclass schema pays for it

        return [field.name for field in dataclasses.fields(schema)]
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
            for field in dataclasses.fields(schema)
            if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING
        }
    if _is_typeddict(schema):
        return _typeddict_optional_keys(schema)
    # A plain (Cli-style) class carries defaults as class attributes.
    return {name for name in field_names if hasattr(schema, name)}


def _unwrap_annotation(annotation: Any) -> Any:
    # include_extras=True keeps Required/NotRequired and Annotated wrappers (get_type_hints does not
    # strip typing_extensions' markers on 3.10); coerce the underlying type.
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
    """

    def __init__(self, key: str, raw: Any, expected: str) -> None:
        self.key = key
        self.raw = raw
        self.expected = expected
        super().__init__(f"invalid value for {key}: {raw!r} (expected {expected})")


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
            an unsupported annotation).
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
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise _CoercionError(key, raw, _type_name(annotation)) from exc
    return schema(**values)
