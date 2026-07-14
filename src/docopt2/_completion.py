from __future__ import annotations

import itertools
import os
import re
from typing import TYPE_CHECKING, cast

from docopt2._errors import DocoptExit, DocoptLanguageError
from docopt2._parser import (
    MATCH_LIMIT,
    Argument,
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

# Environment protocol shared with the generated shell scripts: when completion fires, the script
# sets these variables and re-invokes the program, whose docopt() call answers with the candidates.
_TRIGGER_ENV = "_DOCOPT2_COMPLETE"
_WORDS_ENV = "_DOCOPT2_WORDS"


# --- the resolver: which tokens may legally come next -------------------------------------------


def _frontier(node: Pattern, left: list[Pattern], *, block: bool) -> Iterator[tuple[list[Pattern], set[Pattern], bool]]:
    """Yield ``(remaining, frontier, blocks)`` per partial-consumption path; a token sequence is a
    valid prefix iff some path leaves ``remaining == []``.

    ``frontier`` is the leaves that could match the NEXT token. An option floats (offerable, and the
    path proceeds past it, non-blocking); an unfilled positional/command sets ``blocks`` to ``block``,
    so the command pass (``block=True``) stops at the next positional while the option pass
    (``block=False``) floats past it to reach later options. A present positional that fails is dead.
    """
    if isinstance(node, LeafPattern):
        position, matched = node.single_match(left)
        if matched is not None and position is not None:
            yield left[:position] + left[position + 1 :], set(), False  # already typed; consume it
        elif isinstance(node, Option):
            yield left, {node}, False  # floats: offerable next, sequence proceeds (deferred)
        elif not any(type(leaf) is Argument for leaf in left):
            yield left, {node}, block  # unfilled positional/command (only options, if any, remain)
        return
    if isinstance(node, Either):
        for child in node.children:
            yield from _frontier(child, left, block=block)
        return
    if isinstance(node, OneOrMore):
        for remaining, frontier, blocks in _frontier(node.children[0], left, block=block):
            yield remaining, frontier, blocks
            if not frontier and len(remaining) < len(left):  # consumed one and progressed: may repeat
                yield from _frontier(node, remaining, block=block)
        return
    if isinstance(node, (Optional, OptionsShortcut)):
        yield from _frontier_seq(node.children, left, optional=True, block=block)
        return
    yield from _frontier_seq(cast("Required", node).children, left, optional=False, block=block)


def _frontier_seq(
    children: list[Pattern], left: list[Pattern], *, optional: bool, block: bool
) -> Iterator[tuple[list[Pattern], set[Pattern], bool]]:
    if not children:
        yield left, set(), False
        return
    head, rest = children[0], children[1:]
    for remaining, frontier, blocks in _frontier(head, left, block=block):
        if blocks:  # an unfilled required positional; stop, do not advance past it
            yield remaining, frontier, True
        else:  # head consumed input or floated past; advance, carrying its frontier along
            for tail_remaining, tail_frontier, tail_blocks in _frontier_seq(
                rest, remaining, optional=optional, block=block
            ):
                yield tail_remaining, frontier | tail_frontier, tail_blocks
    if optional:  # an optional child may be skipped entirely
        yield from _frontier_seq(rest, left, optional=optional, block=block)


def _resolve(doc: str, typed: list[str]) -> list[str]:
    """Names (commands and options) that may legally follow the already-typed ``typed`` tokens."""
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_usage(single_usage_section(doc)), options)
    expand_options_shortcut(pattern, options)
    base = parse_argv(Tokens(list(typed)), list(options))
    after_separator = "--" in typed and not any(leaf.name == "--" for leaf in pattern.flat(Command))
    # Command pass: the typed positionals only (options and `--` stripped), positionals blocking so
    # only the next command in order is offered. Bounded, so an exponential-skip pattern cannot hang.
    positionals: list[Pattern] = [leaf for leaf in base if type(leaf) is Argument and leaf.value != "--"]
    command_paths = itertools.islice(_frontier(pattern, positionals, block=True), MATCH_LIMIT)
    command_frontiers = [frontier for remaining, frontier, _b in command_paths if remaining == []]
    if not command_frontiers:
        return []  # the typed positionals cannot be consumed - not a valid prefix, nothing to complete
    names: set[str] = {
        cast("str", leaf.name) for frontier in command_frontiers for leaf in frontier if type(leaf) is Command
    }
    if after_separator:
        return sorted(names)  # options are not parsed after a POSIX `--` separator
    # Option pass: over the full prefix, positionals do NOT block, so the walk floats past unfilled
    # positionals to every reachable unconsumed option (repeats return via `...`); dead branches prune.
    for remaining, frontier, _b in itertools.islice(_frontier(pattern, base, block=False), MATCH_LIMIT):
        if remaining == []:
            names.update(str(leaf.long or leaf.short) for leaf in frontier if isinstance(leaf, Option))
    return sorted(names)


def complete(doc: str, words: Sequence[str]) -> list[str]:
    """Return the completion candidates for the last (cursor) word of ``words``.

    Earlier tokens are consumed against the usage pattern; the command literals and option names
    (never positional values) that could legally come next are returned, filtered to the partial
    word. A malformed doc or a prefix ending mid-option-argument yields no candidates, never raises.
    """
    tokens = list(words)
    incomplete = tokens[-1] if tokens else ""
    typed = tokens[:-1]
    try:
        candidates = _resolve(doc, typed)
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


def reply_to_completion_request(doc: str) -> str | None:
    """If a completion request is in the environment, return its reply, else None.

    Each reply line is ``name\\tdescription`` (the description may be empty). The request var holds the
    completed tokens before the cursor; only a :func:`generate_completion` script sets it, so a normal
    run returns None. Shells that show descriptions (zsh, fish, PowerShell) render the second column;
    bash keeps the name only.
    """
    if os.environ.get(_TRIGGER_ENV) is None:
        return None
    raw = os.environ.get(_WORDS_ENV, "")
    words = raw.split("\n") if raw else []
    try:
        descriptions = _describe(doc)
    except DocoptLanguageError:
        descriptions = {}  # a malformed Options section must not raise into the shell on Tab
    return "\n".join(f"{name}\t{descriptions.get(name, '')}" for name in complete(doc, [*words, ""]))


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
        "    local IFS=$'\\n'\n"
        '    local words="${typed[*]}"\n'  # completed tokens, glued back, without the program name
        '    local reply; reply="$(__TRIGGER__=1 __WORDS__="$words" "${COMP_WORDS[0]}" 2>/dev/null | cut -f1)"\n'
        '    COMPREPLY=( $(compgen -W "$reply" -- "${COMP_WORDS[COMP_CWORD]}") )\n'
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


_RENDERERS: dict[str, Callable[[str, str], str]] = {
    "bash": _render_bash,
    "zsh": _render_zsh,
    "fish": _render_fish,
    "powershell": _render_powershell,
}


def generate_completion(doc: str, prog: str, shell: str = "bash") -> str:
    """Return a context-aware shell completion script for the CLI described by ``doc``.

    ``shell`` is one of ``"bash"``, ``"zsh"``, ``"fish"`` or ``"powershell"`` - the same four Click
    and Typer emit. The script is a thin callback: at each Tab it re-invokes the program with a
    completion request in the environment, and the program's :func:`docopt` call resolves the
    tokens legal at the cursor from the usage grammar (so suggestions narrow to the matched
    subcommand's options and arguments, not a flat global list).

    A docopt program answers the script's requests by default; a program that does not want this
    passes ``docopt(..., complete=False)`` to opt out.
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
