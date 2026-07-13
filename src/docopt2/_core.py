from __future__ import annotations

import enum
import itertools
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, TypeVar, cast, overload
from uuid import UUID

from docopt2._completion import reply_to_completion_request
from docopt2._diagnostics import Caret, Diagnostic, Snippet, use_color
from docopt2._errors import DocoptExit, DocoptLanguageError
from docopt2._help import render_help
from docopt2._parser import (
    MATCH_LIMIT,
    Argument,
    Command,
    Option,
    Pattern,
    Tokens,
    expand_options_shortcut,
    formal_tokens,
    formal_usage,
    nearest_usage_line,
    parse_argument_defaults,
    parse_argv,
    parse_defaults,
    parse_pattern,
    required_leaf_names,
    single_usage_section,
)
from docopt2._spellcheck import _closest, suggest_option
from docopt2._typed import _CoercionError, bind_schema

SchemaT = TypeVar("SchemaT")
CliT = TypeVar("CliT", bound="Cli")


class Source(enum.Enum):
    """Where a resolved value came from, in the precedence order docopt2 applies (highest first)."""

    CLI = "cli"
    ENV = "env"
    CONFIG = "config"
    DEFAULT = "default"


class Arguments(dict[str, Any]):
    """Mapping of parsed element names (``"--flag"``, ``"<arg>"``, ``"command"``) to their values
    (``str | bool | int | list[str] | None``); the back-compat return type, narrowed by the typed API.

    ``provided`` is the set of names actually supplied in ``argv`` (so a defaulted value is
    distinguishable from an explicit one); ``extra`` holds leftover tokens kept by ``allow_extra=True``.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.provided: frozenset[str] = frozenset()
        self.extra: list[str] = []
        self._sources: dict[str, Source] = {}

    def __repr__(self) -> str:
        body = ",\n ".join(f"{key!r}: {value!r}" for key, value in sorted(self.items()))
        return f"{{{body}}}"

    def was_given(self, name: str) -> bool:
        """Return whether ``name`` was supplied in ``argv`` (as opposed to left at its default)."""
        return name in self.provided

    def source(self, name: str) -> Source:
        """Where ``name``'s value was resolved from: the command line, ``[env:]``, ``[config:]``, or the default.

        Answers "why is this value what it is?" for layered configuration; a name never resolved from a
        fallback reports :attr:`Source.DEFAULT`.
        """
        return self._sources.get(name, Source.DEFAULT)


def _extras(default_help: bool, version: object, options: list[Pattern], doc: str, help_style: str) -> None:
    """Handle the built-in ``-h``/``--help`` and ``--version`` options by printing and exiting."""
    if default_help and any(option.name in ("-h", "--help") and option.value for option in options):
        if help_style == "rich":
            # scope the rendered help to the command path already typed (the positionals before --help)
            tokens = tuple(str(leaf.value) for leaf in options if type(leaf) is Argument and leaf.value is not None)
            print(render_help(doc, tokens, color=use_color(sys.stdout)))
        else:
            print(doc.strip("\n"))
        sys.exit()
    if version and any(option.name == "--version" and option.value for option in options):
        print(version)
        sys.exit()


def _argv_snippet(argv: list[str] | tuple[str, ...] | str, token: str, label: str) -> Snippet:
    """An 'in the arguments:' snippet with a caret under ``token`` (dropped if not a literal substring)."""
    argv_text = argv if isinstance(argv, str) else " ".join(str(item) for item in argv)
    at = argv_text.find(token)
    carets = [Caret(at, at + len(token), label)] if at != -1 else []
    return Snippet(argv_text, "in the arguments:", carets)


def _env_truthy(value: str) -> bool:
    """Interpret a fallback value for a boolean flag: set unless it reads as empty or false."""
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _span_of(leaves: Iterable[Pattern], name: str) -> tuple[int, int] | None:
    """The usage span of the leaf named ``name`` (the first that carries one), or None."""
    return next((leaf.span for leaf in leaves if leaf.name == name and leaf.span is not None), None)


def _coercion_diagnostic(doc: str, argv: list[str] | tuple[str, ...] | str, err: _CoercionError) -> Diagnostic:
    """Render a schema coercion failure with the same two-span caret used for match errors: the value
    in the argv, cross-referenced to the usage element that declared its type."""
    usage = single_usage_section(doc)
    snippets = []
    in_argv = _argv_snippet(argv, str(err.raw), f"expected {err.expected}")
    if in_argv.carets:  # only caret the argv when the value is literally there (a CLI value, not env/default)
        snippets.append(in_argv)
    # Build the pattern the same way docopt() does (formal_tokens), so the leaf spans align with `usage`;
    # parse_tree() uses formal_usage and would offset the caret.
    pattern = parse_pattern(formal_tokens(usage), parse_defaults(doc))
    where = _span_of(pattern.flat(), err.key)
    if where is not None:
        caret = Caret(*where, f"typed as {err.expected}")
        snippets.append(Snippet(usage, "in the usage:", [caret]))
    # "one of `a`, `b`" reads as "is not one of ..."; a plain type reads as "is not a valid int".
    hint = None
    if err.expected.startswith("one of "):
        reason = f"`{err.raw}` is not {err.expected}"
        choices = [match.group(1) for match in re.finditer(r"`([^`]+)`", err.expected)]
        suggestion = _closest(str(err.raw), choices)  # a mistyped choice gets a spell-checked "did you mean"
        if suggestion is not None:
            hint = f"did you mean `{suggestion}`?"
    else:
        reason = f"`{err.raw}` is not a valid {err.expected}"
    # Why it failed is context (a note); only the spell-checked suggestion proposes a fix (a help).
    return Diagnostic(summary=f"invalid value for `{err.key}`", snippets=snippets, note=reason, help=hint)


# What a `[config: key]` may hold. A config value is normalized with str(), so the type set is the one
# whose str() is a faithful, coercible-back rendering: everything `_coerce` accepts as a schema annotation
# (_typed.py), plus `time`, which a TOML loader yields and no annotation names. A whitelist, not a
# container blacklist: an opaque object is not a container either, and str(object()) is a memory address.
_CONFIG_VALUE = (str, bool, int, float, Decimal, Path, UUID, datetime, date, time)


class _ConfigShapeError(Exception):
    """A `[config: key]` annotation that lands on something that is not a value: raised in the fallback resolver."""

    def __init__(self, name: str, key: str, found: Any) -> None:
        super().__init__(key)
        self.name = name
        self.key = key
        self.found = found


def _config_shape_diagnostic(doc: str, err: _ConfigShapeError) -> Diagnostic:
    """Caret the option whose config key resolves to a table, a list or an opaque object, not to a value."""
    usage = single_usage_section(doc)
    snippets = []
    where = _span_of(parse_pattern(formal_tokens(usage), parse_defaults(doc)).flat(), err.name)
    if where is not None:
        snippets.append(Snippet(usage, "in the usage:", [Caret(*where, f"declared [config: {err.key}]")]))
    hint = None
    if isinstance(err.found, Mapping) and err.found:  # one level short of the value: name the keys under it
        leaves = ", ".join(f"`{err.key}.{child}`" for child in list(err.found)[:3])
        hint = f"point the annotation at a single value: {leaves}"
    return Diagnostic(
        summary=f"invalid config value for `{err.name}`",
        snippets=snippets,
        note=f"`{err.key}` has type `{type(err.found).__name__}` in the config, and an option takes one value",
        help=hint,
    )


def _config_lookup(config: Mapping[str, Any], key: str) -> Any:
    """Walk a dotted `[config: a.b.c]` key into the config mapping, or None if any level is absent."""
    node: Any = config
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _fallback_value(option: Option, config: Mapping[str, Any] | None) -> tuple[str, Source] | None:
    """The env-then-config fallback for an omitted option (env wins), with its source, or None to default.

    An empty or unset source is treated as absent - the shell ``${VAR:-default}`` convention - so a blank
    environment variable never silently overrides the config or default with an empty string.
    """
    if option.env is not None:
        env_value = os.environ.get(option.env)
        if env_value:  # non-empty; unset or "" falls through
            return env_value, Source.ENV
    if option.config_key is not None and config is not None:
        found = _config_lookup(config, option.config_key)
        if found is not None:
            # Anything outside the value set would reach the option as a repr - `{'c': 1}`, `[1, 2]`, or a
            # memory address - and the program would run on garbage. It fails here rather than at the
            # schema: without one, a config value is never coerced, and nothing downstream would notice.
            if not isinstance(found, _CONFIG_VALUE):
                raise _ConfigShapeError(cast("str", option.name), option.config_key, found)
            if str(found):  # non-empty; a null or blank config value falls through
                return str(found), Source.CONFIG  # a string, so the schema coerces it like a CLI value
    return None


def _apply_fallbacks(result: Arguments, options: list[Option], config: Mapping[str, Any] | None) -> None:
    """Fill options absent from argv from their declared sources: CLI (provided) > env > config > default.

    An option given on the command line (in ``result.provided``) is left untouched; otherwise an
    ``[env: VAR]`` (then a ``[config: key]`` against ``config``) supplies the value and records its
    :class:`Source`, which coerces through the schema like any other string. ``was_given`` still reports
    such an option as not given.
    """
    for option in options:
        name = option.name
        if name is None or name in result.provided or name not in result:
            continue
        resolved = _fallback_value(option, config)
        if resolved is not None:
            raw, source = resolved
            filled = raw if option.argcount else _env_truthy(raw)
            # a repeating option holds a list everywhere else; keep the key's type consistent
            result[name] = [filled] if isinstance(result[name], list) else filled
            result._sources[name] = source


@overload
def docopt(
    doc: str | None,
    argv: list[str] | tuple[str, ...] | str | None = ...,
    help: bool = ...,
    version: object = ...,
    options_first: bool = ...,
    *,
    default_help: bool | None = ...,
    suggest: bool = ...,
    negative_numbers: bool = ...,
    allow_abbrev: bool = ...,
    allow_extra: bool = ...,
    exit_code: int = ...,
    complete: bool = ...,
    schema: type[SchemaT],
    config: Mapping[str, Any] | None = ...,
    help_style: str = ...,
) -> SchemaT: ...
@overload
def docopt(
    doc: str | None,
    argv: list[str] | tuple[str, ...] | str | None = ...,
    help: bool = ...,
    version: object = ...,
    options_first: bool = ...,
    *,
    default_help: bool | None = ...,
    suggest: bool = ...,
    negative_numbers: bool = ...,
    allow_abbrev: bool = ...,
    allow_extra: bool = ...,
    exit_code: int = ...,
    complete: bool = ...,
    schema: None = ...,
    config: Mapping[str, Any] | None = ...,
    help_style: str = ...,
) -> Arguments: ...
def docopt(
    doc: str | None,
    argv: list[str] | tuple[str, ...] | str | None = None,
    help: bool = True,  # noqa: A002 - original docopt public parameter name; kept for drop-in compatibility
    version: object = None,
    options_first: bool = False,
    *,
    default_help: bool | None = None,
    suggest: bool = False,
    negative_numbers: bool = False,
    allow_abbrev: bool = True,
    allow_extra: bool = False,
    exit_code: int = 1,
    complete: bool = True,
    schema: type[SchemaT] | None = None,
    config: Mapping[str, Any] | None = None,
    help_style: str = "raw",
) -> Arguments | SchemaT:
    """Parse ``argv`` against the command-line interface described in ``doc``.

    Args:
        doc: Description of the command-line interface (the usage message).
        argv: Argument vector to parse. ``sys.argv[1:]`` is used if omitted; a string
            is split on whitespace.
        help: Set to False to disable automatic help on ``-h``/``--help``. This is the
            original docopt name, kept for drop-in compatibility.
        version: If truthy, printed when ``--version`` appears in ``argv``.
        options_first: Set to True to require options to precede positional arguments.
        default_help: Alias for ``help``. When not None it takes precedence.
        suggest: On a failed parse, if a mistyped long option resembles a known one,
            include a "did you mean ..." hint in the ``DocoptExit`` message.
        negative_numbers: Treat tokens like ``-3`` or ``-6.28`` as positional arguments
            instead of short-option clusters.
        allow_abbrev: When False, a long option in ``argv`` must be written in full; an
            unambiguous prefix like ``--ver`` no longer de-abbreviates to ``--version``.
        allow_extra: When True, leftover ``argv`` tokens that the usage cannot place no longer
            raise; the best partial match is returned and the surplus is exposed on the result's
            ``extra`` list (the ``parse_known_args`` idiom). Missing required elements still fail.
        exit_code: Process status carried by a ``DocoptExit`` from a failed parse. The default,
            1, keeps the usage message auto-printing on an uncaught error; any other value exits
            with that status (per ``SystemExit``, the message then travels on ``str(exc)``).
        complete: Answer shell completion requests (on by default). docopt inspects the environment
            for a request from a ``generate_completion`` script; when one is present it prints the
            candidates and exits, otherwise it parses normally. Set to False to opt out, so this
            call never responds to the completion protocol (the check is one environment lookup).
        schema: If given (a dataclass, TypedDict, or pydantic model), the parsed result
            is bound to it and returned as that type instead of an ``Arguments`` mapping.
        config: A mapping (from a config file you loaded) to resolve ``[config: key]`` fallbacks
            against. Precedence is command-line argument > ``[env: VAR]`` > ``[config: key]`` >
            ``[default: ...]``. Left as ``None``, any ``[config: ...]`` annotation is inert.
        help_style: ``"raw"`` (the default) prints the usage message verbatim on ``--help``, as docopt
            does. ``"rich"`` renders an aligned, colored help screen that documents each option's value
            source - its ``[env: ...]``/``[config: ...]``/``[default: ...]`` chain - and is scoped to the
            command path already typed (``prog sub --help`` shows only ``sub``).

    Returns:
        An ``Arguments`` mapping of element names to parsed values, or an instance of
        ``schema`` when one is supplied. On the mapping, ``provided`` is the set of names given
        in ``argv`` and ``extra`` holds surplus tokens kept by ``allow_extra``.

    Raises:
        DocoptLanguageError: The usage message is malformed, or the schema disagrees
            with it (see ``bind_schema``).
        DocoptExit: The user-supplied ``argv`` does not match, or a value cannot be
            coerced to a schema field's declared type.

    Example:
        ``docopt("Usage: prog <host> <port>", "127.0.0.1 8080")`` returns an ``Arguments``
        mapping ``{"<host>": "127.0.0.1", "<port>": "8080"}``. Passing ``schema=Args`` (a
        dataclass with ``host: str`` and ``port: int``) instead returns an ``Args`` whose
        ``port`` is an ``int``.
    """
    if doc is None:
        raise DocoptLanguageError(Diagnostic(summary="doc (the usage message) must not be None").render())
    if complete:
        # On by default (opt out with complete=False): answer a shell completion request from the
        # environment and exit; only a generate_completion script sets it, so a normal run gets None.
        completion_reply = reply_to_completion_request(doc)
        if completion_reply is not None:
            print(completion_reply)
            sys.exit()
    show_help = help if default_help is None else default_help
    if help_style not in ("raw", "rich"):
        raise ValueError(f"help_style must be 'raw' or 'rich', not {help_style!r}")
    argv = sys.argv[1:] if argv is None else argv

    usage = single_usage_section(doc)

    def _exit(diagnostic: Diagnostic, **fields: Any) -> DocoptExit:
        """A DocoptExit carrying this call's usage text and exit code (no shared class state)."""
        return DocoptExit(diagnostic=diagnostic, usage=usage, exit_code=exit_code, **fields)

    argument_defaults = parse_argument_defaults(doc)
    options = parse_defaults(doc)
    try:
        pattern = parse_pattern(formal_tokens(usage), options)
    except RecursionError:
        raise DocoptLanguageError(Diagnostic(summary="the usage pattern nests too deeply to parse").render()) from None
    argv_tokens = Tokens(argv, usage=usage, exit_code=exit_code)
    argv_patterns = parse_argv(argv_tokens, list(options), options_first, negative_numbers, allow_abbrev)
    expand_options_shortcut(pattern, options)
    # POSIX `--` ends option parsing; drop it unless the usage declares a `--`, so it is not a positional.
    if not any(leaf.name == "--" for leaf in pattern.flat(Command)):
        for index, leaf in enumerate(argv_patterns):
            if type(leaf) is Argument and leaf.value == "--":
                del argv_patterns[index]
                break
    _extras(show_help, version, argv_patterns, doc, help_style)
    # Greedy-first: the first outcome is the greedy result, so every argv vanilla accepts is unchanged;
    # if it leaves leaves over we keep looking (bounded) for a fully-consuming match.
    left: list[Pattern]
    collected: list[Pattern]
    complete_match: list[Pattern] | None
    try:
        fixed = pattern.fix()
        outcome_iter = fixed.matches(argv_patterns, [])
        greedy = next(outcome_iter, None)
        if greedy is None:
            # nothing matched at all; report the whole argv as left over
            left, collected, complete_match = argv_patterns, [], None
        else:
            left, collected = greedy
            bounded = itertools.islice(outcome_iter, MATCH_LIMIT)
            if left == []:
                complete_match = collected
            else:
                complete_match = next((accumulated for remaining, accumulated in bounded if remaining == []), None)
    except RecursionError:
        raise _exit(Diagnostic(summary="the arguments are too deeply nested to match")) from None
    extra_tokens: list[str] = []
    if complete_match is None and allow_extra and greedy is not None:
        # A prefix matched but not fully: keep it and return the surplus as `extra` instead of failing.
        # A missing required element leaves `greedy is None`, so it still fails - surplus tolerated, not gaps.
        complete_match = collected
        extra_tokens = [str(leaf.name) if isinstance(leaf, Option) else str(leaf.value) for leaf in left]
    if complete_match is not None:
        result = Arguments((cast("str", leaf.name), leaf.value) for leaf in [*fixed.flat(), *complete_match])
        result.provided = frozenset(cast("str", leaf.name) for leaf in complete_match)
        result.extra = extra_tokens
        try:
            _apply_fallbacks(result, options, config)
        except _ConfigShapeError as exc:
            raise _exit(_config_shape_diagnostic(doc, exc), collected=complete_match, left=left) from exc
        for name, default in argument_defaults.items():
            if name in result and result[name] is None:
                result[name] = default
        for name in result:
            # _apply_fallbacks already recorded ENV/CONFIG; here CLI wins for anything given on argv,
            # and everything else settles on its literal default.
            if name in result.provided:
                result._sources[name] = Source.CLI
            else:
                result._sources.setdefault(name, Source.DEFAULT)
        if schema is None:
            return result
        try:
            return bind_schema(result, schema)
        except _CoercionError as exc:
            raise _exit(_coercion_diagnostic(doc, argv, exc), collected=complete_match, left=left) from exc
    if suggest:
        raw_tokens = argv.split() if isinstance(argv, str) else argv
        hint = suggest_option(raw_tokens, options, allow_abbrev)
        if hint is not None:
            unknown, suggestion = hint
            snippets = [_argv_snippet(argv, unknown, "not a known option")]
            declared_at = _span_of(fixed.flat(Option), suggestion)
            if declared_at is not None:  # the suggested option is written in the usage: cross-reference it
                where = Snippet(usage, "in the usage:", [Caret(*declared_at, f"`{suggestion}` is defined here")])
                snippets.append(where)
            diagnostic = Diagnostic(
                summary=f"unknown option `{unknown}`", snippets=snippets, help=f"did you mean `{suggestion}`?"
            )
            raise _exit(diagnostic, collected=collected, left=left)
    if left and greedy is not None:
        # A prefix matched, so left[0] is the first token with no place in the usage. Caret it in the
        # argv; if it is an option the usage declares (mutual exclusion, or a non-repeatable option
        # given twice), add a second caret at that declaration - the argv-to-usage cross-reference.
        offending = left[0]
        shown = str(offending.name) if isinstance(offending, Option) else str(offending.value)
        snippets = [_argv_snippet(argv, shown, "not allowed here")]
        usage_span = _span_of(fixed.flat(Option), shown)
        advice: str | None
        if usage_span is not None:
            snippets.append(Snippet(usage, "in the usage:", [Caret(*usage_span, "declared here")]))
            advice = "give it at most once, not with a mutually exclusive option"
        else:
            advice = None
        summary = f"unexpected argument `{shown}`"
        raise _exit(Diagnostic(summary=summary, snippets=snippets, help=advice), collected=collected, left=left)
    # Score against a freshly-parsed (unfixed) pattern: fix() dedups identical leaves across lines onto
    # one shared span, which would caret the wrong line when a name repeats (e.g. `<y>` in several lines).
    near_miss = nearest_usage_line(parse_pattern(formal_tokens(usage), parse_defaults(doc)), argv_patterns)
    if near_miss is not None:
        # Caret the one element the closest line still needs. Ranking needs alternatives; the caret does not.
        name, span, total = near_miss
        snippet = Snippet(usage, "in the usage:", [Caret(*span, "required here")])
        diagnostic = Diagnostic(
            summary=f"missing required `{name}`",
            snippets=[snippet],
            note=f"of {total} usage patterns, your arguments came closest to this one" if total > 1 else None,
        )
        raise _exit(diagnostic, collected=collected, left=left)
    required = required_leaf_names(fixed)
    if required:
        missing = Diagnostic(
            summary="missing or mismatched arguments", note=f"the usage requires: {' '.join(required)}"
        )
        raise _exit(missing, collected=collected, left=left)
    raise _exit(Diagnostic(summary="the arguments do not match the usage"), collected=collected, left=left)


def parse_tree(doc: str) -> Pattern:
    """Build the usage-pattern :class:`Pattern` tree for ``doc`` without matching argv - ``repr()`` it,
    walk it, or serialize with :meth:`Pattern.to_dict` to diff how a change affects parsing. The
    ``[options]`` shortcut stays an :class:`OptionsShortcut` node rather than expanded."""
    options = parse_defaults(doc)
    return parse_pattern(formal_usage(single_usage_section(doc)), options)


class Cli:
    """Optional typed base class for a class-first API.

    Subclass it, set ``__cli_doc__`` to the usage message, and declare fields as
    annotations; ``YourClass.parse(argv)`` returns an instance typed as the subclass. This is
    the only decorator-shaped sugar that keeps real static types under mypy, pyright and
    ty (a method-injecting decorator degrades the result to ``Any``).
    """

    __cli_doc__: ClassVar[str | None] = None

    def __init__(self, **fields: Any) -> None:
        # Generic value-object init so a plain (non-dataclass) subclass constructs from
        # the bound fields; a @dataclass subclass overrides this with its generated init.
        for name, value in fields.items():
            setattr(self, name, value)

    @classmethod
    def parse(
        cls: type[CliT],
        argv: list[str] | tuple[str, ...] | str | None = None,
        *,
        help: bool = True,  # noqa: A002 - mirrors docopt()'s public parameter name
        version: object = None,
        options_first: bool = False,
        suggest: bool = False,
        negative_numbers: bool = False,
        allow_abbrev: bool = True,
        allow_extra: bool = False,
        exit_code: int = 1,
        complete: bool = True,
        config: Mapping[str, Any] | None = None,
        help_style: str = "raw",
    ) -> CliT:
        """Parse ``argv`` against ``__cli_doc__`` and return a typed instance of the subclass."""
        return docopt(
            cls.__cli_doc__,
            argv,
            help,
            version,
            options_first,
            suggest=suggest,
            negative_numbers=negative_numbers,
            allow_abbrev=allow_abbrev,
            allow_extra=allow_extra,
            exit_code=exit_code,
            complete=complete,
            schema=cls,
            config=config,
            help_style=help_style,
        )


_DispatchHandler = Callable[[Any], Any]


class Dispatch:
    """Route a parsed command to a handler - the subcommand dispatch docopt itself omits.

    Register one handler per command path with :meth:`on`, then :meth:`run` parses ``argv`` and
    calls the handler for the most specific command path that matched, passing it the parsed
    ``Arguments`` (or, when the registration supplies ``schema=``, an instance of that schema bound
    from the result, so each subcommand gets its own typed view). An ``on()`` with no command path
    registers a fallback, used when no more specific path matches.

    Example:
        ``app = Dispatch(doc); @app.on("user", "create") def create(args): ...; app.run()``.
    """

    def __init__(self, doc: str) -> None:
        self.doc = doc
        self._handlers: list[tuple[tuple[str, ...], _DispatchHandler, type[Any] | None]] = []

    def on(self, *command_path: str, schema: type[Any] | None = None) -> Callable[[_DispatchHandler], _DispatchHandler]:
        """Register the decorated handler for ``command_path`` (empty path = fallback handler)."""

        def register(handler: _DispatchHandler) -> _DispatchHandler:
            self._handlers.append((command_path, handler, schema))
            return handler

        return register

    def run(self, argv: list[str] | tuple[str, ...] | str | None = None, **options: Any) -> Any:
        """Parse ``argv`` against the doc and invoke the handler for the matched command path.

        Extra keyword arguments are forwarded to :func:`docopt` (``suggest``, ``exit_code``, ...);
        ``schema`` is not among them, since dispatch matches on the mapping and binds per handler.
        """
        arguments = cast("Arguments", docopt(self.doc, argv, **options))
        resolved = self._resolve(arguments)
        if resolved is None:
            raise DocoptExit(diagnostic=Diagnostic(summary="no handler is registered for the given command"))
        handler, schema = resolved
        if schema is None:
            return handler(arguments)
        try:
            bound = bind_schema(arguments, schema)
        except _CoercionError as exc:
            resolved_argv = sys.argv[1:] if argv is None else argv
            raise DocoptExit(diagnostic=_coercion_diagnostic(self.doc, resolved_argv, exc)) from exc
        return handler(bound)

    def _resolve(self, arguments: Arguments) -> tuple[_DispatchHandler, type[Any] | None] | None:
        best_length = -1
        best: tuple[_DispatchHandler, type[Any] | None] | None = None
        for command_path, handler, schema in self._handlers:
            if len(command_path) > best_length and all(arguments.get(name) for name in command_path):
                best_length = len(command_path)
                best = (handler, schema)
        return best
