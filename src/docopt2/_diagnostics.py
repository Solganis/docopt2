from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TextIO

# Zero-dependency ANSI. Rendering defaults to plain text (color off), since the message travels on
# an exception and is often inspected as a string; color belongs at the print site, not in str(exc).
_RESET, _BOLD, _DIM = "\033[0m", "\033[1m", "\033[2m"
_RED, _YELLOW, _CYAN, _GREEN = "\033[31m", "\033[33m", "\033[36m", "\033[32m"
_TAB = 8  # tab stop width; source lines are expanded to spaces so carets align under real columns


def use_color(stream: TextIO | None) -> bool:
    """Whether to emit ANSI to ``stream``: only to a real terminal, and never when ``NO_COLOR`` is set.

    A stream that cannot answer is not a terminal: ``pythonw.exe`` and a windowed build hand a GUI
    program ``sys.stderr is None``, and a closed stream raises - neither must turn a parse error into
    an ``AttributeError`` from inside the error's own constructor.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if stream is None:
        return False
    try:
        return stream.isatty()
    except ValueError:
        return False


@dataclass
class Caret:
    """A ``[start, end)`` range in a snippet's source, drawn as ``^`` with a short label beneath."""

    start: int
    end: int
    label: str = ""


@dataclass
class Snippet:
    """One captioned source (a usage string or an argv line) and the carets drawn under it."""

    source: str
    intro: str
    carets: list[Caret]


def _source_line(source: str, offset: int) -> tuple[int, str]:
    """The line ``offset`` falls on: its start index in ``source``, and its text without the newline."""
    start = source.rfind("\n", 0, offset) + 1
    end = source.find("\n", start)
    return start, source[start : len(source) if end == -1 else end]


def _caret_lines(snippet: Snippet) -> list[tuple[int, str, list[Caret]]]:
    """The snippet's source lines that carry a caret, each with the carets that fall on it.

    A snippet is not always one line: `(` can open on one usage line and be closed on the next, and a
    group's span covers everything between. Drawing every caret under a single line would point at
    columns that line does not have. A snippet with no carets still shows its first line.
    """
    if not snippet.carets:
        return [(*_source_line(snippet.source, 0), [])]
    grouped: dict[int, list[Caret]] = {}
    for caret in sorted(snippet.carets, key=lambda item: item.start):
        start, _ = _source_line(snippet.source, caret.start)
        grouped.setdefault(start, []).append(caret)
    return [(start, _source_line(snippet.source, start)[1], carets) for start, carets in sorted(grouped.items())]


@dataclass
class Diagnostic:
    """An error lowered to a uniform shape: a summary, captioned snippets, and note/help lines.

    Every error path renders through here, so all messages share one visual grammar; a snippet per
    source lets a single error point a caret at both the input and the usage that rejected it.
    """

    summary: str
    snippets: list[Snippet] = field(default_factory=list)
    note: str | None = None
    help: str | None = None
    level: str = "error"  # "error" (red) or "warning" (yellow, used by the static linter)

    def render(self, *, color: bool = False) -> str:
        def paint(code: str, text: str) -> str:
            return f"{code}{text}{_RESET}" if color else text

        gutter = "   |"
        heading = _YELLOW if self.level == "warning" else _RED
        lines = [paint(_BOLD + heading, self.level) + paint(_BOLD, f": {self.summary}")]
        for snippet in self.snippets:
            lines.append(gutter)
            lines.append(f"{gutter}  {paint(_DIM, snippet.intro)}")
            for line_start, line, carets in _caret_lines(snippet):
                lines.append(f"{gutter}    {line.expandtabs(_TAB)}")
                for caret in carets:
                    # pad by the DISPLAY width of the prefix (tabs expanded), not its character count
                    pad = " " * len(line[: caret.start - line_start].expandtabs(_TAB))
                    # a group's span can run past this line; clamp it, so the caret marks where it opens
                    end = min(caret.end, line_start + len(line))
                    underline = paint(_RED, "^" * max(1, end - caret.start))
                    lines.append(f"{gutter}    {pad}{underline} {paint(_YELLOW, caret.label)}".rstrip())
        if self.snippets:  # close the gutter only when a source block was drawn
            lines.append(gutter)
        if self.note is not None:
            lines.append(f"   = {paint(_CYAN, 'note')}: {self.note}")
        if self.help is not None:
            lines.append(f"   = {paint(_GREEN, 'help')}: {self.help}")
        return "\n".join(lines)
