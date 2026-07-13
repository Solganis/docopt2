from __future__ import annotations

import keyword
from typing import TYPE_CHECKING, Literal

from docopt2._parser import (
    always_required_names,
    expand_options_shortcut,
    formal_tokens,
    parse_argument_defaults,
    parse_defaults,
    parse_pattern,
    single_usage_section,
)
from docopt2._typed import _key_to_field

if TYPE_CHECKING:
    from docopt2._parser import LeafValue

StubStyle = Literal["dataclass", "typeddict", "cli"]


def _annotation(value: LeafValue, *, required: bool, defaulted: bool) -> str:
    """The Python type a schema field needs, read from the fixed leaf value the matcher uses.

    ``fix_repeating_arguments`` has already stamped the multiplicity into the value: ``False`` is a
    non-repeating flag/command, ``0`` a repeating one (a count), ``[]`` a repeating value element, a
    string a value with a ``[default: ...]``. ``None`` is a non-repeating value element with no
    default, optional unless the usage always requires it (or a positional default fills it in).
    """
    if value is None:
        return "str" if required or defaulted else "str | None"
    if type(value) is bool:  # before int: a bool IS an int, and a flag is not a count
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is list:
        return "list[str]"
    return "str"


def _key_annotations(doc: str) -> dict[str, str]:
    """Map every result key ``docopt()`` would return to its inferred annotation, in usage order."""
    usage = single_usage_section(doc)
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_tokens(usage), options)
    expand_options_shortcut(pattern, options)  # so keys reachable only via `[options]` are included
    fixed = pattern.fix()
    required = set(always_required_names(fixed))
    defaults = parse_argument_defaults(doc)
    key_types: dict[str, str] = {}
    for leaf in fixed.flat():
        key = leaf.name
        if key is None or key in key_types:  # a leaf on several usage lines is one result key
            continue
        key_types[key] = _annotation(leaf.value, required=key in required, defaulted=key in defaults)
    return key_types


def _doc_literal(doc: str) -> str:
    """A Python string literal for ``doc``: a readable triple-quoted block when safe, else ``repr``."""
    if '"""' not in doc and "\\" not in doc and not doc.endswith('"'):
        return f'"""{doc}"""'
    return repr(doc)


def _render(name: str, style: StubStyle, doc: str, fields: list[tuple[str, str]], notes: list[str]) -> str:
    lines = [*notes, ""] if notes else []
    body = [f"    {field}: {annotation}" for field, annotation in fields]
    if style == "cli":
        lines += ["from docopt2 import Cli", "", "", f"class {name}(Cli):", f"    __cli_doc__ = {_doc_literal(doc)}"]
        lines += body  # the class body is never empty (it always carries __cli_doc__)
    elif style == "typeddict":
        lines += ["from typing import TypedDict", "", "", f"class {name}(TypedDict):"]
        lines += body or ["    pass"]
    else:
        lines += ["import dataclasses", "", "", "@dataclasses.dataclass", f"class {name}:"]
        lines += body or ["    pass"]
    return "\n".join(lines) + "\n"


def generate_stub(doc: str, *, name: str = "Args", style: StubStyle = "dataclass") -> str:
    """Generate a typed schema class from a usage message, ready to pass as ``docopt(doc, schema=...)``.

    Args:
        doc: The usage message (the same string given to :func:`~docopt2.docopt`).
        name: Class name for the generated schema.
        style: ``"dataclass"`` (default), ``"typeddict"``, or ``"cli"`` (a :class:`~docopt2.Cli`
            subclass with the usage embedded, so ``Name.parse()`` works standalone).

    Returns:
        Python source for the schema class. Every field is typed from the grammar (``str``,
        ``str | None``, ``int``, ``bool``, ``list[str]``); widen a field by hand (``port: int``) to
        get coercion for free. A key the typed API cannot represent (two usage names collapsing to
        one field, or a name that is not a valid identifier) becomes a leading ``# note`` instead of
        a field, so the output is always valid Python.

    Raises:
        DocoptLanguageError: The usage message is malformed (the same error :func:`docopt` raises).
        ValueError: ``name`` is not a valid Python identifier.
    """
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(f"class name {name!r} is not a valid Python identifier")
    key_types = _key_annotations(doc)
    keys_by_field: dict[str, list[str]] = {}
    for key in key_types:
        keys_by_field.setdefault(_key_to_field(key), []).append(key)

    notes: list[str] = []
    fields: list[tuple[str, str]] = []
    handled: set[str] = set()
    for key, annotation in key_types.items():
        field = _key_to_field(key)
        if field in handled:
            continue
        handled.add(field)
        colliding = keys_by_field[field]
        if len(colliding) > 1:
            joined = ", ".join(f"`{usage_key}`" for usage_key in colliding)
            notes.append(f"# note: usage keys {joined} all map to `{field}`; give them distinct names to type them")
        elif not field.isidentifier() or keyword.iskeyword(field):
            notes.append(f"# note: usage key `{key}` is not a valid field name; rename it in the usage to type it")
        else:
            fields.append((field, annotation))
    return _render(name, style, doc, fields, notes)
