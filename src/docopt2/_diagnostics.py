from __future__ import annotations

from dataclasses import dataclass, field

# Zero-dependency ANSI. Rendering defaults to plain text (color off), since the message travels on
# an exception and is often inspected as a string; color belongs at the print site, not in str(exc).
_RESET, _BOLD, _DIM = "\033[0m", "\033[1m", "\033[2m"
_RED, _YELLOW, _CYAN, _GREEN = "\033[31m", "\033[33m", "\033[36m", "\033[32m"
_TAB = 8  # tab stop width; source lines are expanded to spaces so carets align under real columns


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
            anchor = min((caret.start for caret in snippet.carets), default=0)
            line_start = snippet.source.rfind("\n", 0, anchor) + 1
            newline = snippet.source.find("\n", line_start)
            line = snippet.source[line_start : len(snippet.source) if newline == -1 else newline]
            lines.append(f"{gutter}    {line.expandtabs(_TAB)}")
            for caret in sorted(snippet.carets, key=lambda item: item.start):
                # pad by the DISPLAY width of the prefix (tabs expanded), not its character count
                pad = " " * len(line[: caret.start - line_start].expandtabs(_TAB))
                underline = paint(_RED, "^" * max(1, caret.end - caret.start))
                lines.append(f"{gutter}    {pad}{underline} {paint(_YELLOW, caret.label)}".rstrip())
        if self.snippets:  # close the gutter only when a source block was drawn
            lines.append(gutter)
        if self.note is not None:
            lines.append(f"   = {paint(_CYAN, 'note')}: {self.note}")
        if self.help is not None:
            lines.append(f"   = {paint(_GREEN, 'help')}: {self.help}")
        return "\n".join(lines)
