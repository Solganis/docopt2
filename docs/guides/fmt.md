# Formatting usage messages

Your usage message is source you maintain by hand, so it drifts. Option columns stop lining up, separators
get inconsistent, trailing whitespace creeps in.

[`format_usage`](../reference/fmt.md) (and the `docopt2 fmt` CLI) tidies it. It is to [`check`](check.md)
what a formatter is to a linter: `check` finds defects, `format_usage` reformats the layout of an otherwise
valid usage.

It does three things:

- **aligns every `Options:` description into one column**
- normalizes each option spec, so comma separators become spaces and runs of whitespace collapse
- strips trailing whitespace

<div class="docopt2-term"><span class="dt-fg">$ docopt2 fmt serve.py</span>
<span class="dt-fg dt-b">Usage:</span>
<span class="dt-fg">  serve [--port=&lt;n&gt;] [--host=&lt;h&gt;] &lt;root&gt;</span>

<span class="dt-fg dt-b">Options:</span>
<span class="dt-fg">  --port=&lt;n&gt;    Port [default: 8080].</span>
<span class="dt-fg">  --host=&lt;h&gt;    Interface [default: 127.0.0.1].</span>
<span class="dt-fg">  -v --verbose  Be loud.</span></div>

```python
from docopt2 import format_usage

format_usage("Usage: p\n\nOptions:\n  -v, --verbose      Loud.   \n")
# 'Usage: p\n\nOptions:\n  -v --verbose  Loud.\n'
```

## Guarantees

- **Layout-only.** The change is cosmetic. `docopt2.docopt` parses the formatted usage to exactly the same
  result for every argument vector, and the options (names, defaults, `[env:]`/`[config:]`) are unchanged.
  A property test pins this over many randomly-laid-out usages.
- **Idempotent.** Running it on already-formatted output is a no-op, so it is safe in a pre-commit hook or a
  format-check step.
- **Only the `options:` sections are re-aligned** - the same lines the parser reads options from. A `-`-led
  line anywhere else is prose, not an option, and prose keeps every character (trailing whitespace aside).
- **The `Usage:` patterns are left untouched** - reformatting a grammar back to canonical text is a harder
  problem than aligning the options block, and this stays out of it deliberately.

The usage is text, not code, which is what makes this possible at all. docopt2 formats it the way `ruff` and
`black` format source, giving the interface its own lint-and-format pair: `check` plus `fmt`.

Where the interface is built in code, there is no such text to align. Formatting it is just formatting
Python, which your existing formatter already does.

## From the command line

`docopt2 fmt <source>` prints the formatted usage, reading from a `.py` module docstring, a usage text file,
or `-` for standard input. Pipe it back to rewrite the file, or diff it in CI to flag a usage that is not
formatted.

A *malformed* usage still exits `0`, since validating is [`check`](check.md)'s job, not the formatter's. An
unreadable source (a missing file, a `.py` with no module docstring) exits `1`.

## See also

- [`format_usage`](../reference/fmt.md) in the API reference.
- [Usage linting](check.md) - the lint half of the pair. Run it to catch defects a formatter cannot.
