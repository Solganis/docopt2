from __future__ import annotations

import dataclasses
import html as _html
import sys
from pathlib import Path

from docopt2 import DocoptExit, check, docopt
from docopt2._help import _OPTION_TOKEN, _intro, _option_entries, _scope, _usage_lines

_ASSETS = Path(__file__).resolve().parent.parent / "docs" / "assets"

_STYLE = """
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
html,body{margin:0;padding:0;background:transparent}
.docopt2-term{font-family:'JetBrains Mono',ui-monospace,Consolas,monospace;white-space:pre;
  line-height:1.5;padding:28px 34px;border:1px solid #30363d;border-radius:12px;font-size:28px;
  background:#161b22;color:#c9d1d9;display:inline-block}
.dt-b{font-weight:700}.dt-fg{color:#c9d1d9}.dt-err{color:#ff7b72}.dt-warn{color:#e3b341}
.dt-caret{color:#ff7b72}.dt-label{color:#e3b341}.dt-help{color:#56d364}.dt-note{color:#56d4dd}
.dt-dim{color:#8b949e}
"""


def _esc(text: str) -> str:
    return _html.escape(text, quote=False)


def to_term_html(text: str) -> str:
    """Convert one rendered diagnostic (plain text) into the span-classed `.docopt2-term` inner HTML."""
    lines = text.rstrip("\n").splitlines()
    kind, _, summary = lines[0].partition(":")
    head = "dt-err" if kind == "error" else "dt-warn"
    out = [f'<span class="{head} dt-b">{_esc(kind)}</span><span class="dt-fg dt-b">:{_esc(summary)}</span>']
    for line in lines[1:]:
        after = line[4:]  # everything past the 4-char gutter ('   |' or '   =')
        if line.strip() == "|":
            out.append('<span class="dt-fg">   |</span>')
        elif "^" in line:
            start = line.index("^")
            end = len(line) - len(line[start:].lstrip("^"))
            out.append(
                f'<span class="dt-fg">   |</span><span class="dt-fg">{_esc(line[4:start])}</span>'
                f'<span class="dt-caret">{line[start:end]}</span><span class="dt-label">{_esc(line[end:])}</span>'
            )
        elif after.strip().startswith("in ") and after.rstrip().endswith(":"):
            out.append(f'<span class="dt-fg">   |</span><span class="dt-dim">{_esc(after)}</span>')
        elif line[:4] == "   =":
            word, _, rest = after.strip().partition(":")
            css_class = {"help": "dt-help", "note": "dt-note"}.get(word, "dt-fg")
            out.append(
                f'<span class="dt-fg">   = </span><span class="{css_class}">{_esc(word)}</span>'
                f'<span class="dt-fg">:{_esc(rest)}</span>'
            )
        else:
            out.append(f'<span class="dt-fg">   |</span><span class="dt-fg">{_esc(after)}</span>')
    return "\n".join(out)


# --- the sources: exactly what each screenshot shows -----------------------------------------------


@dataclasses.dataclass
class _Port:
    port: int


_DIAGNOSTIC_DOC = (
    "Usage:\n  git commit [--message=<msg>] [--amend]\n  git push [--force] <remote>\n\nOptions:\n"
    "  --message=<msg>  Commit message.\n  --amend          Amend the last commit.\n"
    "  --force          Force the push.\n"
)
_CHECK_DOC = (
    "Naval Fate.\n\nUsage:\n  naval ship new <name>...\n  naval ship <name> move <x> <y> [--speed=<kn>]\n"
    "  naval --help\n\nOptions:\n  --speed=<kn>  Speed in knots [default: 10].\n  --verbose     Extra logging.\n"
)
_RICH_DOC = (
    "Serve a directory over HTTP.\n\nUsage:\n  serve [--port=<n>] [--host=<h>] [--log=<lvl>] <root>\n\nOptions:\n"
    "  --port=<n>  Port to bind [default: 8080] [env: PORT] [config: server.port].\n"
    "  --host=<h>  Interface to bind [default: 127.0.0.1] [env: HOST].\n"
    "  --log=<lvl>  Log verbosity [default: info] [config: logging.level]."
)


def _diagnostic(doc: str, argv: str, **kwargs: object) -> str:
    try:
        docopt(doc, argv, complete=False, **kwargs)  # ty: ignore[invalid-argument-type] - docopt's own kwargs
    except DocoptExit as exit_signal:
        return str(exit_signal).removesuffix("\n" + exit_signal.usage)
    raise AssertionError(f"{argv!r} was expected to fail")  # pragma: no cover - a broken source, not a screenshot


def _rich_help_markup() -> str:
    """The rich `--help` screen is not a diagnostic, so its span markup is built from the doc directly."""
    usage = _scope(_usage_lines(_RICH_DOC), ())
    used: set[str] = set()
    shortcut = False
    for line in usage:
        shortcut = shortcut or "[options]" in line
        used |= set(_OPTION_TOKEN.findall(line))
    entries = _option_entries(_RICH_DOC)
    shown = entries if shortcut else [entry for entry in entries if entry[1] & used]
    out = [f'<span class="dt-fg">{_esc(_intro(_RICH_DOC))}</span>', "", '<span class="dt-fg dt-b">Usage:</span>']
    out += [f'<span class="dt-fg">  {_esc(line)}</span>' for line in usage]
    if shown:
        out += ["", '<span class="dt-fg dt-b">Options:</span>']
        width = max(len(entry[0]) for entry in shown)
        for spec, _names, description, provenance in shown:
            row = (
                f'<span class="dt-fg">  </span><span class="dt-help">{_esc(spec)}{" " * (width - len(spec))}</span>'
                f'<span class="dt-fg">  {_esc(description)}</span>'
            )
            if provenance:
                row += f'<span class="dt-dim">  {_esc(provenance)}</span>'
            out.append(row)
    return "\n".join(out)


def sources() -> dict[str, str]:
    """What each screenshot shows, as the tool renders it right now. The single source of truth."""
    return {
        "diagnostic": _diagnostic(_DIAGNOSTIC_DOC, "push --forcce origin", suggest=True),
        "check": check(_CHECK_DOC)[0].render(),
        "coercion": _diagnostic("Usage: prog --port=<n>", "--port=abc", schema=_Port),
        "rich-help": _rich_help_markup(),
    }


def main() -> None:  # pragma: no cover - a developer command, not library code
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(device_scale_factor=2)
        for name, text in sources().items():
            # The text and the image are written together and only here: test_screenshots.py pins the text
            # against the live tool, so writing one without the other would leave a stale picture unguarded.
            (_ASSETS / f"{name}.txt").write_text(text, encoding="utf-8", newline="\n")
            markup = text if name == "rich-help" else to_term_html(text)
            page.set_content(f"<style>{_STYLE}</style><div class='docopt2-term'>{markup}</div>")
            page.wait_for_timeout(400)  # let the web font land before the shot
            element = page.locator(".docopt2-term")
            element.screenshot(path=str(_ASSETS / f"{name}.png"), omit_background=True)
            print(f"wrote {name}.png and {name}.txt", file=sys.stderr)
        browser.close()


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
