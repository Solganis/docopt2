# Formatting usage messages

Your usage message is source you maintain by hand, so it drifts: option columns stop lining up, separators
get inconsistent, trailing whitespace creeps in. [`format_usage`](../reference/fmt.md) (and the `docopt2 fmt`
CLI) tidies it - the formatter to what [`check`](check.md) is as a linter. `check` finds defects;
`format_usage` reformats the layout of an otherwise valid usage.

It **aligns every `Options:` description into one column**, normalizes each option spec (comma separators
become spaces, runs of whitespace collapse), and strips trailing whitespace:

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

- **Layout-only.** The change is cosmetic: `docopt2.docopt` parses the formatted usage to exactly the same
  result for every argument vector, and the options (names, defaults, `[env:]`/`[config:]`) are unchanged. A
  property test pins this over many randomly-laid-out usages.
- **Idempotent.** Running it on already-formatted output is a no-op, so it is safe in a pre-commit hook or a
  format-check step.
- **The `Usage:` patterns are left untouched** - reformatting a grammar back to canonical text is a harder
  problem than aligning the options block, and this stays out of it deliberately.

Because the usage is text (not code, as in argparse or Click), docopt2 can format it the way `ruff`/`black`
format source - a lint-and-format pair (`check` + `fmt`) that no code-driven CLI library can offer.

## From the command line

`docopt2 fmt <source>` prints the formatted usage, reading from a `.py` module docstring, a usage text file,
or `-` for standard input. It always exits `0`; pipe it back to rewrite the file, or diff it in CI to flag a
usage that is not formatted.

## See also

- [`format_usage`](../reference/fmt.md) in the API reference.
- [Usage linting](check.md) - the lint half of the pair; run it to catch defects a formatter cannot.
