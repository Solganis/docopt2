from __future__ import annotations

import dataclasses
import enum
import sys
import types
import weakref
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
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
from uuid import UUID

from docopt2._errors import DocoptExit, DocoptLanguageError

if TYPE_CHECKING:
    from collections.abc import Mapping

SchemaT = TypeVar("SchemaT")

# Required/NotRequired markers for TypedDict optionality, gathered from typing (3.11+) and
# typing_extensions (present iff the caller uses it, e.g. for NotRequired on Python 3.10).
_REQUIRED_MARKERS: tuple[Any, ...] = ()
_NOTREQUIRED_MARKERS: tuple[Any, ...] = ()
if sys.version_info >= (3, 11):  # pragma: no branch - always taken on the 3.11+ interpreter the suite runs under
    from typing import NotRequired, Required

    _REQUIRED_MARKERS = (Required,)
    _NOTREQUIRED_MARKERS = (NotRequired,)
try:
    from typing_extensions import NotRequired as _TeNotRequired
    from typing_extensions import Required as _TeRequired

    _REQUIRED_MARKERS += (_TeRequired,)
    _NOTREQUIRED_MARKERS += (_TeNotRequired,)
except ImportError:  # pragma: no cover - typing_extensions is optional
    pass


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


def _coerce(value: Any, annotation: Any) -> Any:
    """Coerce a docopt-native value to the field's declared type (closed set)."""
    if value is None:
        return None
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is types.UnionType or origin is Union:
        inner = next((arg for arg in args if arg is not type(None)), str)
        return _coerce(value, inner)
    if origin is Literal:
        if value in args:
            return value
        raise ValueError(f"{value!r} is not one of {args!r}")
    if origin is list or annotation is list:
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
    if annotation is int:
        return int(value)
    if annotation is float:
        return float(value)
    if annotation is str:
        return value
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return annotation(value)
    if annotation is Path:
        return Path(value)
    if annotation is Decimal:
        return Decimal(value)
    if annotation is UUID:
        return UUID(value)
    if annotation is datetime:
        return datetime.fromisoformat(value)
    if annotation is date:
        return date.fromisoformat(value)
    raise DocoptLanguageError(f"typed docopt cannot coerce to unsupported annotation {annotation!r}")


def _field_names(schema: type[Any], hints: dict[str, Any]) -> list[str]:
    """The names to bind on ``schema``, excluding ClassVars, dunders, and non-fields."""
    if dataclasses.is_dataclass(schema):
        return [field.name for field in dataclasses.fields(schema)]
    if _is_typeddict(schema):
        return list(hints)
    return [
        name
        for name, annotation in hints.items()
        if not name.startswith("_") and get_origin(annotation) is not ClassVar
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
    total = getattr(schema, "__total__", True)
    optional: set[str] = set()
    for name, annotation in _resolved_hints(schema).items():
        origin = get_origin(annotation)
        if origin in _REQUIRED_MARKERS:
            continue
        if origin in _NOTREQUIRED_MARKERS or not total:
            optional.add(name)
    return optional


def _omittable_fields(schema: type[Any], field_names: list[str]) -> set[str]:
    """Fields that may be left out when their value is None (default, or NotRequired)."""
    if dataclasses.is_dataclass(schema):
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
    origin = get_origin(annotation)
    if origin in _REQUIRED_MARKERS or origin in _NOTREQUIRED_MARKERS:
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
    # Reflective pydantic detection: we never import pydantic, so it stays optional.
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
