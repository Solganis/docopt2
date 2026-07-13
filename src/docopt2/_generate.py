from __future__ import annotations

import contextlib
import io
import itertools
import random
import re
from typing import TYPE_CHECKING

from docopt2._core import docopt
from docopt2._diagnostics import Diagnostic
from docopt2._errors import DocoptExit, DocoptLanguageError
from docopt2._parser import (
    Argument,
    Command,
    Either,
    OneOrMore,
    Option,
    Optional,
    OptionsShortcut,
    Pattern,
    Required,
    expand_options_shortcut,
    formal_usage,
    parse_defaults,
    parse_pattern,
    single_usage_section,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Protocol

    class _Chooser(Protocol):
        """The random decisions the pattern walk makes: pick a branch, a repeat count, a coin flip.

        Typing-only. Abstracting the choices lets the same walk run off a seeded ``random.Random``
        (:class:`_RandomChooser`) or off a Hypothesis draw (in :mod:`docopt2.hypothesis`), with no
        second copy of the tree walk.
        """

        def choice(self, options: list[Pattern]) -> Pattern: ...
        def integer(self, low: int, high: int) -> int: ...
        def boolean(self) -> bool: ...


class _RandomChooser:
    """Drives the walk from a seeded ``random.Random``; used by :func:`generate_examples`."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def choice(self, options: list[Pattern]) -> Pattern:
        return self._rng.choice(options)

    def integer(self, low: int, high: int) -> int:
        return self._rng.randint(low, high)

    def boolean(self) -> bool:
        return self._rng.random() < 0.5


def _usage_pattern(doc: str) -> Pattern:
    """Build the usage-pattern tree, the same one :func:`docopt` matches against."""
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_usage(single_usage_section(doc)), options)
    expand_options_shortcut(pattern, options)
    return pattern


def _sample(node: Pattern, chooser: _Chooser, counter: Iterator[int]) -> list[str]:
    """Walk the pattern into one argv the usage accepts.

    Every choice comes from ``chooser``, so the same walk serves both the seeded generator and the
    Hypothesis strategy.
    """
    if isinstance(node, Required):
        return [token for child in node.children for token in _sample(child, chooser, counter)]
    if isinstance(node, Either):
        return _sample(chooser.choice(node.children), chooser, counter)
    if isinstance(node, OneOrMore):
        return [token for _ in range(chooser.integer(1, 2)) for token in _sample(node.children[0], chooser, counter)]
    if isinstance(node, (Optional, OptionsShortcut)):
        if chooser.boolean():
            return [token for child in node.children for token in _sample(child, chooser, counter)]
        return []
    if isinstance(node, Command):
        return [str(node.name)]
    if isinstance(node, Argument):
        return [f"v{next(counter)}"]
    if isinstance(node, Option):
        name = str(node.long or node.short)
        if node.argcount:
            return [f"{name}=v{next(counter)}"] if name.startswith("--") else [name, f"v{next(counter)}"]
        return [name]
    raise TypeError(f"unexpected pattern node {type(node).__name__}")  # pragma: no cover - closed node hierarchy


def _unknown_option(doc: str) -> str:
    """A long option the doc does not define, so appending it turns an accepted argv into a rejected one."""
    defined = {option.long for option in parse_defaults(doc) if option.long is not None}
    name = "--unknown"
    while name in defined:
        name += "-x"
    return name


def _is_rejected(doc: str, argv: list[str]) -> bool:
    """Does docopt really refuse this argv, called the way a program calls it?

    An appended unknown option is a guess, not a proof: an argv carrying ``--help`` prints the help and
    exits 0 first, and a usage with ``[--]`` takes the unknown token as a positional and accepts it.
    """
    with contextlib.redirect_stdout(io.StringIO()):  # the help path would print the doc
        try:
            docopt(doc, argv, complete=False)
        except DocoptExit:
            return True
        except SystemExit:  # `--help` exits 0: not a refusal
            return False
    return False


def generate_examples(doc: str, *, count: int = 10, valid: bool = True, seed: int | None = None) -> list[list[str]]:
    """Generate example argument vectors derived from the usage message.

    Each returned item is an argv token list (no program name). A ``valid`` example is one ``docopt``
    accepts; an invalid one (``valid=False``) is one ``docopt`` rejects, and every invalid example is
    verified against the parser before it is returned - never merely assumed to be rejected. Duplicates are
    dropped, so a small grammar (or one where few argvs can be made invalid) may yield fewer than ``count``.
    ``seed`` makes the output reproducible. Everything is derived from the ``Usage:`` and ``Options:``
    blocks, so the examples cannot drift from what :func:`docopt` parses.
    """
    single_usage_section(doc)  # fail loudly here on a malformed usage, not mid-walk
    pattern = _usage_pattern(doc)
    chooser = _RandomChooser(random.Random(seed))
    counter = itertools.count(1)
    unknown = _unknown_option(doc) if not valid else ""
    seen: set[tuple[str, ...]] = set()
    examples: list[list[str]] = []
    for _ in range(max(count, 0) * 20):
        if len(examples) >= count:
            break
        argv = _sample(pattern, chooser, counter)
        if not valid:
            argv.append(unknown)
        key = tuple(argv)
        if key in seen:
            continue
        seen.add(key)
        if not valid and not _is_rejected(doc, argv):
            continue  # the appended option did not make it invalid; this argv is not an example of a refusal
        examples.append(argv)
    return examples


def _toml_quote(text: str) -> str:
    """Quote a string as TOML, doubling backslashes before escaping quotes (order matters)."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_value(value: object) -> str:
    """Render an option's default as a TOML scalar: bare int/float/bool, quoted string, ``""`` if none."""
    if value is None:
        return '""'
    if value is True:
        return "true"
    if value is False:
        return "false"
    text = str(value)
    if re.fullmatch(r"-?(0|[1-9]\d*)(\.\d+)?", text):  # a bare TOML int/float; leading zeros (e.g. "007") stay strings
        return text
    if text.lower() in ("true", "false"):
        return text.lower()
    return _toml_quote(text)


def _toml_key(segment: str) -> str:
    """Render one dotted-key segment as a TOML key: bare when bare-key-safe, else a quoted key.

    A config annotation may name anything (``[config: a"b]``); an unquoted ``a"b = ...`` would be
    invalid TOML, so a segment outside ``[A-Za-z0-9_-]`` (or empty) is emitted as a quoted key instead.
    """
    if re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        return segment
    return _toml_quote(segment)


def _config_comment(option: Option) -> str:
    """A trailing comment tying a config entry back to its CLI flag and any ``[env: VAR]`` it also reads."""
    refs = [str(option.name), *([f"env {option.env}"] if option.env is not None else [])]
    return "  # " + ", ".join(refs)


def _reject_colliding_config_keys(keys: list[str]) -> None:
    """Fail loudly on config keys that cannot share one TOML document, instead of emitting a broken file.

    A repeated key, or a dotted path that is a prefix of another (the same name used as both a value and
    a ``[table]``, like ``srv`` beside ``srv.port``), is a contradiction TOML cannot express - so it is a
    usage error, reported like a malformed usage rather than written out as invalid TOML.
    """
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            raise DocoptLanguageError(Diagnostic(summary=f"duplicate config key `{key}`").render())
        seen.add(key)
    paths = sorted({tuple(key.split(".")) for key in keys}, key=len)
    for index, prefix in enumerate(paths):
        collides = next((path for path in paths[index + 1 :] if path[: len(prefix)] == prefix), None)
        if collides is not None:
            raise DocoptLanguageError(
                Diagnostic(
                    summary=f"config key `{'.'.join(prefix)}` collides with `{'.'.join(collides)}`",
                    note="one is used as a value and the other as a table; they cannot share a TOML file",
                ).render()
            )


def generate_config_template(doc: str) -> str:
    """Generate a TOML config-file skeleton from the ``[config: key]`` annotations in ``doc``.

    Every option declaring a ``[config: dotted.key]`` becomes an entry under its table, seeded with the
    option's ``[default: ...]`` (or an empty placeholder), and commented with the CLI flag and any
    ``[env: VAR]`` it also reads. Options without a ``[config:]`` key are not part of the file. Returns
    an empty string when the usage declares no config keys. Config keys that cannot coexist in one TOML
    document (a duplicate, or a path that is a prefix of another) raise :class:`DocoptLanguageError`.
    """
    single_usage_section(doc)  # fail loudly on a malformed usage, like the other generators
    config_options = [option for option in parse_defaults(doc) if option.config_key is not None]
    _reject_colliding_config_keys([str(option.config_key) for option in config_options])
    tables: dict[str, list[tuple[str, Option]]] = {}
    order: list[str] = []
    for option in config_options:
        *prefix, leaf = str(option.config_key).split(".")
        table = ".".join(prefix)
        if table not in tables:
            tables[table] = []
            order.append(table)
        tables[table].append((leaf, option))
    # TOML requires root keys before any [table] header, so emit the unnamed table first.
    order = ([""] if "" in tables else []) + [table for table in order if table]
    blocks: list[str] = []
    for table in order:
        header = ["[" + ".".join(_toml_key(segment) for segment in table.split(".")) + "]"] if table else []
        rows = [(f"{_toml_key(leaf)} = {_toml_value(opt.value)}", _config_comment(opt)) for leaf, opt in tables[table]]
        width = max(len(entry) for entry, _ in rows)
        blocks.append("\n".join([*header, *(f"{entry.ljust(width)}{comment}" for entry, comment in rows)]))
    return "\n\n".join(blocks) + "\n" if blocks else ""
