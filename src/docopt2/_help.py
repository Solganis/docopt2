from __future__ import annotations

import re

from docopt2._diagnostics import _BOLD, _DIM, _GREEN, _RESET
from docopt2._parser import _CONFIG_PATTERN, _DEFAULT_PATTERN, _ENV_PATTERN, Option, _option_chunks, parse_section

# A short/long option token as written in a usage line or an option spec (`-v`, `--speed`, `--dry-run`).
_OPTION_TOKEN = re.compile(r"-{1,2}[A-Za-z][\w-]*")
# A bare-word command literal in a usage line (not an option, not a <placeholder> or UPPER arg).
_COMMAND_LITERAL = re.compile(r"[a-z][\w-]*", re.IGNORECASE)


def _usage_lines(doc: str) -> list[str]:
    """The pattern lines of the ``Usage:`` section (the header and program name kept, one per line)."""
    sections = parse_section("usage:", doc)
    if not sections:
        return []
    _, _, rest = sections[0].partition(":")  # drop the `Usage` header word, keep the patterns after it
    return [line.strip() for line in rest.splitlines() if line.strip()]


def _provenance(description: str, *, has_default: bool) -> str:
    """The value-resolution chain declared in a description, as `[env: X, config: Y, default: Z]` or ``""``.

    Reads the same `[env:]`/`[config:]`/`[default:]` annotations docopt() resolves against, in precedence
    order, so the rendered help documents where each value comes from. ``has_default`` is False for a flag:
    docopt ignores a flag's `[default:]` (a flag is present or absent), so showing one would name a value
    the parser never uses.
    """
    env = _ENV_PATTERN.search(description)
    config = _CONFIG_PATTERN.search(description)
    without_sources = _CONFIG_PATTERN.sub("", _ENV_PATTERN.sub("", description))  # then the greedy default
    default = _DEFAULT_PATTERN.search(without_sources) if has_default else None
    sources = [
        *([f"env: {env.group(1)}"] if env else []),
        *([f"config: {config.group(1)}"] if config else []),
        *([f"default: {default.group(1).strip()}"] if default else []),
    ]
    return f"[{', '.join(sources)}]" if sources else ""


def _option_entries(doc: str) -> list[tuple[str, frozenset[str], str, str]]:
    """Each ``Options:`` line as ``(spec, {names}, description, provenance)`` - the annotations pulled out
    of the description into a source chain, so the help text stays human-readable."""
    entries: list[tuple[str, frozenset[str], str, str]] = []
    for chunk in _option_chunks(doc):
        spec, _, description = chunk.strip().partition("  ")
        provenance = _provenance(description, has_default=bool(Option.parse(chunk).argcount))
        clean = _DEFAULT_PATTERN.sub("", _CONFIG_PATTERN.sub("", _ENV_PATTERN.sub("", description)))
        # close the gap the removed annotations leave before trailing punctuation ("bind ." -> "bind."),
        # anchored at the end so a legitimate mid-text "a : b" is left alone
        clean = re.sub(r"\s+([.,;:!?]+)$", r"\1", " ".join(clean.split()))
        entries.append((spec.strip(), frozenset(_OPTION_TOKEN.findall(spec)), clean, provenance))
    return entries


def _intro(doc: str) -> str:
    """The free text before the ``Usage:`` section (the program's one-line description), if any."""
    lines: list[str] = []
    for line in doc.splitlines():
        if re.match(r"\s*usage:", line, re.IGNORECASE):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _option_names_in(line: str) -> set[str]:
    """The option names a usage line uses, expanding a short cluster: ``-hso`` is ``-h``, ``-s``, ``-o``.

    A single-dash run of letters is a cluster of short flags, so ``[-hso FILE]`` uses ``-h``/``-s``/``-o`` -
    matching those Options entries. A ``--long`` or a lone ``-h`` is taken verbatim.
    """
    names: set[str] = set()
    for token in _OPTION_TOKEN.findall(line):
        if not token.startswith("--") and len(token) > 2 and token[1:].isalpha():
            names |= {f"-{letter}" for letter in token[1:]}
        else:
            names.add(token)
    return names


def _scope(usage_lines: list[str], argv_tokens: tuple[str, ...]) -> list[str]:
    """Keep only usage lines matching the command path in ``argv_tokens``; all lines if none match."""
    literals = {token for line in usage_lines for token in line.split() if _COMMAND_LITERAL.fullmatch(token)}
    commands = [token for token in argv_tokens if token in literals]
    scoped = [line for line in usage_lines if all(command in line.split() for command in commands)]
    return scoped or usage_lines  # never render an empty usage: fall back to the whole thing


def render_help(doc: str, argv_tokens: tuple[str, ...] = (), *, color: bool = False) -> str:
    """Render ``doc`` as an aligned, optionally colored help screen scoped to the typed command path.

    ``argv_tokens`` are the positional tokens before ``--help``. The usage is narrowed to the lines that
    match them (e.g. ``git commit --help`` shows only the ``commit`` line), and the options list to those
    the shown lines use. An empty path, or one that matches nothing, shows the whole usage.
    """

    def paint(code: str, text: str) -> str:
        return f"{code}{text}{_RESET}" if color else text

    all_lines = _usage_lines(doc)
    usage_lines = _scope(all_lines, argv_tokens)
    named_anywhere = {name for line in all_lines for name in _option_names_in(line)}
    used_options: set[str] = set()
    has_shortcut = False
    for line in usage_lines:
        if "[options]" in line:
            has_shortcut = True
        used_options |= _option_names_in(line)
    entries = _option_entries(doc)
    # A scoped `[options]` fills the options NOT named on any usage line (what expand_options_shortcut
    # does), NOT every option: `serve [options]` must not list `--minify` that only the `build` line takes.
    shown = [
        entry for entry in entries if (entry[1] & used_options) or (has_shortcut and not (entry[1] & named_anywhere))
    ]

    blocks: list[str] = []
    intro = _intro(doc)
    if intro:
        blocks.append(intro)
    usage = [paint(_BOLD, "Usage:"), *(f"  {line}" for line in usage_lines)]
    blocks.append("\n".join(usage))
    if shown:
        width = max(len(entry[0]) for entry in shown)
        rows: list[str] = []
        for spec, _, description, provenance in shown:
            row = f"  {paint(_GREEN, spec.ljust(width))}  {description}"
            if provenance:  # the value-resolution chain, dimmed so it reads as secondary to the description
                row += f"  {paint(_DIM, provenance)}"
            rows.append(row.rstrip())
        blocks.append("\n".join([paint(_BOLD, "Options:"), *rows]))
    return "\n\n".join(blocks)
