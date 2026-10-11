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
    OneOrMore,
    Option,
    Optional,
    OptionsShortcut,
    Pattern,
    Required,
    Tokens,
    _option_chunks,
    expand_options_shortcut,
    formal_usage,
    parse_argv,
    parse_defaults,
    parse_pattern,
    single_usage_section,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from typing import Any

    from docopt2._parser import SingleMatch

_A_VALUE = "\0"  # stands for the next word where a prefix is probed for an option waiting for its argument

# Environment protocol shared with the generated shell scripts: when completion fires, the script
# sets these variables and re-invokes the program, whose docopt() call answers with the candidates.
_TRIGGER_ENV = COMPLETION_REQUEST_ENV
_WORDS_ENV = "_DOCOPT2_WORDS"


# --- the resolver: which tokens may legally come next -------------------------------------------


def _frontier(
    node: Pattern, left: list[Pattern], *, block: bool, in_repetition: bool = False
) -> Iterator[tuple[list[Pattern], tuple[Pattern, ...], bool]]:
    """Yield ``(remaining, frontier, blocks)`` per partial-consumption path; a token sequence is a
    valid prefix iff some path leaves ``remaining == []``.

    ``frontier`` is the leaves that could match the NEXT token, in the order the path meets them, so its first
    positional is the one the path fills next. An option floats (offerable, and the
    path proceeds past it, non-blocking); an unfilled positional/command sets ``blocks`` to ``block``,
    so the command pass (``block=True``) stops at the next positional while the option pass
    (``block=False``) floats past it to reach later options. A present positional that fails is dead.

    ``in_repetition`` marks that this node is being expanded as a ``OneOrMore`` child, which gates the
    skip-branch prune in ``_frontier_seq`` - see there.
    """
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
        for child in node.children:
            yield from _frontier(child, left, block=block, in_repetition=in_repetition)
        return
    if isinstance(node, OneOrMore):
        for remaining, frontier, blocks in _frontier(node.children[0], left, block=block, in_repetition=True):
            yield remaining, frontier, blocks
            if not frontier and len(remaining) < len(left):  # consumed one and progressed: may repeat
                yield from _frontier(node, remaining, block=block, in_repetition=in_repetition)
        return
    if isinstance(node, (Optional, OptionsShortcut)):
        yield from _frontier_seq(node.children, left, optional=True, block=block, in_repetition=in_repetition)
        return
    children = cast("Required", node).children
    yield from _frontier_seq(children, left, optional=False, block=block, in_repetition=in_repetition)


def _frontier_seq(
    children: list[Pattern], left: list[Pattern], *, optional: bool, block: bool, in_repetition: bool
) -> Iterator[tuple[list[Pattern], tuple[Pattern, ...], bool]]:
    if not children:
        yield left, (), False
        return
    head, rest = children[0], children[1:]
    floated = False
    for remaining, frontier, blocks in _frontier(head, left, block=block, in_repetition=in_repetition):
        if blocks:  # an unfilled required positional; stop, do not advance past it
            yield remaining, frontier, True
            continue
        if len(remaining) == len(left) and all(isinstance(leaf, Option) for leaf in frontier):
            floated = True  # head took nothing and put only options ahead (an option alone always does)
        for tail_remaining, tail_frontier, tail_blocks in _frontier_seq(  # advance, carrying its frontier
            rest, remaining, optional=optional, block=block, in_repetition=in_repetition
        ):
            yield tail_remaining, frontier + tail_frontier, tail_blocks
    # An optional child may be skipped. The skip is pruned where head floated: the take-branch holds the same
    # paths with head's options on top. Not inside a OneOrMore, whose re-entry needs the skip's empty frontier
    # (`[-a <name>]...`), and `floated` leaves out a head that puts a command or a positional ahead
    # (`[go] <env>`). Unpruned, `[options]` over 25 flags forked into 2**25 paths and a Tab took over a second.
    if optional and not (floated and not in_repetition):
        yield from _frontier_seq(rest, left, optional=optional, block=block, in_repetition=in_repetition)


class _Typed(Argument):
    """A positional read by its schema field. A token the field does not take is none it can be given, so a path
    that would hand it one is dead, as a path that hands a command another word is."""

    def __init__(self, name: str | None, offered: list[str], takes: Callable[[str, object], bool]) -> None:
        super().__init__(name)
        self.offered = offered
        self._takes = takes

    def single_match(self, left: list[Pattern]) -> SingleMatch:
        found = super().single_match(left)
        given = found[1]
        return found if given is not None and self._takes(str(self.name), given.value) else (None, None)


def _type(node: Pattern, values_for: Callable[[str], list[str]], takes: Callable[[str, object], bool]) -> None:
    """Put a ``_Typed`` in the place of every positional of the tree."""
    if not isinstance(node, BranchPattern):
        return
    for index, child in enumerate(node.children):
        if type(child) is Argument:
            node.children[index] = _Typed(child.name, values_for(str(child.name)), takes)
        _type(child, values_for, takes)


def _bindable(leaves: list[Pattern], takes: Callable[[str, object], bool]) -> bool:
    """Whether every option of ``leaves`` that was given a value was given one its field takes."""
    given = [leaf for leaf in leaves if isinstance(leaf, Option) and isinstance(leaf.value, str)]
    return all(takes(str(leaf.name), leaf.value) for leaf in given)


def _taking_all(pattern: Pattern, leaves: list[Pattern]) -> Iterator[tuple[Pattern, ...]]:
    """The frontier of each path on which the usage takes all of ``leaves`` as a prefix, positionals not blocking.

    The `--` separator is left out: read as a positional nothing matches, it would kill every path.
    """
    typed = [leaf for leaf in leaves if not (type(leaf) is Argument and leaf.value == "--")]
    paths = itertools.islice(_frontier(pattern, typed, block=False), MATCH_LIMIT)
    return (frontier for remaining, frontier, _blocks in paths if remaining == [])


def _resolve(
    doc: str, typed: list[str], values_for: Callable[[str], list[str]], takes: Callable[[str, object], bool] | None
) -> list[str]:
    """What may legally follow the already-typed ``typed`` tokens: commands, options, and the values of an element.

    With ``takes``, the fields of a schema read the tokens too: a prefix that holds a value its field does not
    take has nothing to follow it, since no argv that starts that way can be bound.
    """
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_usage(single_usage_section(doc)), options)
    expand_options_shortcut(pattern, options)
    if takes is not None:
        _type(pattern, values_for, takes)
    try:
        base = parse_argv(Tokens(list(typed)), list(options))
    except DocoptExit:
        # refused as it stands: one more token makes it read only where the last option waited for its argument
        given = parse_argv(Tokens([*typed, _A_VALUE]), list(options))
        fits = any(True for _frontier_of_a_path in _taking_all(pattern, given))  # the usage takes it there too
        fits = fits and (takes is None or _bindable(given[:-1], takes))
        return sorted(values_for(str(given[-1].name))) if fits else []
    if takes is not None and not _bindable(base, takes):
        return []
    after_separator = "--" in typed and not any(leaf.name == "--" for leaf in pattern.flat(Command))
    # Command pass: the typed positionals only (options and `--` stripped), positionals blocking so
    # only the next command in order is offered. Bounded, so an exponential-skip pattern cannot hang.
    positionals: list[Pattern] = [leaf for leaf in base if type(leaf) is Argument and leaf.value != "--"]
    command_paths = itertools.islice(_frontier(pattern, positionals, block=True), MATCH_LIMIT)
    command_frontiers = [frontier for remaining, frontier, _b in command_paths if remaining == []]
    if not command_frontiers:
        return []  # the typed positionals cannot be consumed - not a valid prefix, nothing to complete
    # Option pass: over the full prefix, positionals do NOT block, so the walk floats past unfilled
    # positionals to every reachable unconsumed option (repeats return via `...`); dead branches prune. Its
    # remaining==[] frontiers also decide command viability: a command whose line cannot consume a typed
    # option is a dead end docopt() would reject, so after `--reload` (only on the serve line) `db` is out.
    reachable: set[Pattern] = set()
    filled_next: set[Pattern] = set()  # the positional each path fills next: the first one of its frontier
    for frontier in _taking_all(pattern, base):
        reachable.update(frontier)
        filled_next.update(itertools.islice((leaf for leaf in frontier if not isinstance(leaf, Option)), 1))
    viable_commands = {leaf.name for leaf in reachable if type(leaf) is Command}
    names: set[str] = {
        cast("str", leaf.name)
        for frontier in command_frontiers
        for leaf in frontier
        if type(leaf) is Command and leaf.name in viable_commands
    }
    for leaf in filled_next:
        if isinstance(leaf, _Typed):
            names.update(leaf.offered)
    if after_separator:
        return sorted(names)  # options are not parsed after a POSIX `--` separator
    for leaf in reachable:
        if isinstance(leaf, Option):
            names.add(str(leaf.long or leaf.short))
            if leaf.long is not None and leaf.argcount:
                names.update(f"{leaf.long}={value}" for value in values_for(leaf.long))
    return sorted(names)


def complete(doc: str, words: Sequence[str], schema: type[Any] | None = None) -> list[str]:
    """Return the completion candidates for the last (cursor) word of ``words``.

    Earlier tokens are consumed against the usage pattern. The command literals and option names
    that could legally come next are returned, filtered to the partial word. A malformed doc yields
    no candidates, never raises.

    A value is a candidate only with ``schema``, and only for a field that takes a closed set, a
    ``Literal`` or an ``Enum``. Such a field completes as the next positional, as the argument the
    last option is waiting for, and as ``--option=value`` beside the option's own name. Without it,
    a prefix that ends on an option waiting for its argument yields no candidates.

    A schema other than a pydantic model reads the typed words too: after a value that its field does
    not take there are no candidates, since no argv that starts that way can be bound.
    """
    return _complete(doc, words, [] if schema is None else [schema], per_command=False)


def _complete(doc: str, words: Sequence[str], schemas: Sequence[type[Any]], *, per_command: bool) -> list[str]:
    tokens = list(words)
    incomplete = tokens[-1] if tokens else ""
    typed = tokens[:-1]
    try:
        candidates = _resolve(doc, typed, *_fields(schemas, per_command))
    except (DocoptLanguageError, DocoptExit, RecursionError):
        # a malformed doc, a prefix ending mid-option-argument, or a pathologically deep pattern:
        # complete nothing rather than raising into the shell
        return []
    return [name for name in candidates if name.startswith(incomplete)]


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


def _fields(
    schemas: Sequence[type[Any]], per_command: bool
) -> tuple[Callable[[str], list[str]], Callable[[str, object], bool] | None]:
    """By the key of a usage element: the values to offer for it, and whether a text is one its field takes.

    With no schema there is nothing to offer and nothing to ask, so the second is None. Schemas that each bind
    the lines of one command take any text: which of them binds a line is not known before the line is whole.
    """
    if not schemas:
        return (lambda _key: []), None
    from docopt2._typed import _key_to_field, field_choices, field_takes  # deferred: only a schema asks for them

    choices = field_choices(schemas)
    takes = (lambda _field, _text: True) if per_command else field_takes(schemas[0])
    return (lambda key: choices.get(_key_to_field(key), [])), (lambda key, text: takes(_key_to_field(key), text))


def reply_to_completion_request(
    doc: str, schemas: Sequence[type[Any]] = (), *, per_command: bool = False
) -> str | None:
    """If a completion request is in the environment, return its reply, else None.

    ``per_command`` says that each of ``schemas`` binds the lines of one command, as in a handler table, and
    not every line of the usage.

    Each reply line is ``name\\tdescription`` (the description may be empty). The request var holds the
    completed tokens before the cursor. Only a [`generate_completion`][docopt2.generate_completion] script
    sets it, so a normal run returns None.

    Shells that show descriptions (zsh, fish, PowerShell, nushell) render the second
    column, while bash keeps the name only.
    """
    if os.environ.get(_TRIGGER_ENV) is None:
        return None
    raw = os.environ.get(_WORDS_ENV, "")
    words = raw.split("\n") if raw else []
    try:
        descriptions = _describe(doc)
    except DocoptLanguageError:
        descriptions = {}  # a malformed Options section must not raise into the shell on Tab
    candidates = _complete(doc, [*words, ""], schemas, per_command=per_command)
    # `--option=value` is described as its option is, and a value alone has no description
    return "\n".join(f"{name}\t{descriptions.get(name.partition('=')[0], '')}" for name in candidates)


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
        '    local reply; reply="$(__TRIGGER__=1 __WORDS__="$words" "${COMP_WORDS[0]}" 2>/dev/null | cut -f1)"\n'
        '    COMPREPLY=( $(compgen -W "$reply" -- "$current") )\n'
        "}\n"
        "complete -F __FUNC__ __PROG__\n"
    )
    return (
        template.replace("__PROG__", prog)
        .replace("__FUNC__", function)
        .replace("__TRIGGER__", _TRIGGER_ENV)
        .replace("__WORDS__", _WORDS_ENV)
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
        '    lines=("${(@f)$(__TRIGGER__=1 __WORDS__=$joined ${words[1]})}")\n'
        "    local line desc\n"
        "    for line in $lines; do\n"
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
        f"    env {_TRIGGER_ENV}=1 {_WORDS_ENV}=(string join \\n -- $tokens[2..-1] | string collect) $tokens[1]\n"
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
        "    $env:__TRIGGER__ = '1'\n"
        '    $env:__WORDS__ = ($words -join "`n")\n'
        "    try {\n"
        "        & $commandAst.CommandElements[0].ToString() 2>$null | ForEach-Object {\n"
        '            $parts = $_ -split "`t", 2\n'  # reply line is name`tdescription
        "            $name = $parts[0]\n"
        # StartsWith, not -like: a `*` or `[` in the partial word is a literal prefix, not a wildcard.
        "            if ($name.StartsWith($wordToComplete, [System.StringComparison]::Ordinal)) {\n"
        "                $tip = if ($parts.Count -ge 2 -and $parts[1]) { $parts[1] } else { $name }\n"
        "                [System.Management.Automation.CompletionResult]::new($name, $name, 'ParameterValue', $tip)\n"
        "            }\n"
        "        }\n"
        "    } finally {\n"
        "        Remove-Item Env:__TRIGGER__ -ErrorAction SilentlyContinue\n"
        "        Remove-Item Env:__WORDS__ -ErrorAction SilentlyContinue\n"
        "    }\n"
        "}\n"
    )
    return template.replace("__PROG__", prog).replace("__TRIGGER__", _TRIGGER_ENV).replace("__WORDS__", _WORDS_ENV)


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
        '    let reply = (with-env {__TRIGGER__: "1", __WORDS__: ($typed | str join (char newline))} '
        "{ ^__PROG__ | complete | get stdout })\n"
        "    $reply | lines | where {|line| ($line | str length) > 0} | each {|line|\n"
        "        let parts = ($line | split row (char tab))\n"  # reply line is name<TAB>description
        '        {value: ($parts | get 0), description: ($parts | get 1? | default "")}\n'
        "    } | where {|candidate| $candidate.value | str starts-with $partial}\n"
        "}\n"
        '@complete "__FUNC__"\n'
        'export extern "__PROG__" [ ...rest: string ]\n'
    )
    return (
        template.replace("__PROG__", prog)
        .replace("__FUNC__", function)
        .replace("__TRIGGER__", _TRIGGER_ENV)
        .replace("__WORDS__", _WORDS_ENV)
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
    single_usage_section(doc)
    return _RENDERERS[shell](prog, _function_name(prog))
