# Diagnostics

When the arguments don't match, docopt2 does not just reprint the usage - it points at the offending
token, in the argument vector and in the usage that rejected it, with a two-span caret and a
"did you mean" hint where one applies.

Every error, whether the user mistyped an argument or the developer wrote a malformed usage, is lowered
to one shape: a bold `error:` heading with a one-line summary, then captioned source snippets with
carets, then optional `note:` and `help:` lines. The static [usage linter](check.md) reuses the same
grammar with a yellow `warning:` heading, so a warning and a hard error read the same way.

## A mismatch at parse time

A failed parse raises [`DocoptExit`](../reference/exceptions.md), carrying the rendered diagnostic.

<div class="docopt2-term"><span class="dt-err dt-b">error</span><span class="dt-fg dt-b">: unknown option `--forcce`</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the arguments:</span>
<span class="dt-fg">   |</span><span class="dt-fg">    push --forcce origin</span>
<span class="dt-fg">   |</span><span class="dt-fg">         </span><span class="dt-caret">^^^^^^^^</span><span class="dt-label"> not a known option</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the usage:</span>
<span class="dt-fg">   |</span><span class="dt-fg">      git push [--force] &lt;remote&gt;</span>
<span class="dt-fg">   |</span><span class="dt-fg">                </span><span class="dt-caret">^^^^^^^</span><span class="dt-label"> `--force` is defined here</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: did you mean `--force`?</span></div>

That block is exactly what `str(exc)` prints for the run below (minus the usage message that
`DocoptExit` always appends beneath the diagnostic):

```python
from docopt2 import docopt

doc = """Git push.

Usage:
  git push [--force] <remote>

Options:
  --force  Force the push.
"""

docopt(doc, "push --forcce origin", suggest=True)   # raises the diagnostic above
```

Read the two snippets top to bottom:

- **`in the arguments:`** - your argv, joined with spaces, with a caret under `--forcce`, the token that
  had no place in the usage.
- **`in the usage:`** - the usage line that declares the option you probably meant, with a caret under
  `--force`. This is the cross-reference: it ties the mistake in argv to the exact spot in the spec that
  rejected it, so you are not left scanning the whole usage yourself.

The `help:` line carries the "did you mean" hint. It appears only with `suggest=True`; see
[Opting into hints](#opting-into-hints) below.

The second snippet is not exclusive to typos. Any time the offending argv token is an option the usage
actually declares, the diagnostic carets both places. Giving two branches of a mutually exclusive group
is the common case:

```python
doc = "Usage: prog (--fast | --slow)\n\nOptions:\n  --fast  Fast.\n  --slow  Slow."
docopt(doc, "--fast --slow")
```

<div class="docopt2-term"><span class="dt-err dt-b">error</span><span class="dt-fg dt-b">: unexpected argument `--slow`</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the arguments:</span>
<span class="dt-fg">   |</span><span class="dt-fg">    --fast --slow</span>
<span class="dt-fg">   |</span><span class="dt-fg">           </span><span class="dt-caret">^^^^^^</span><span class="dt-label"> not allowed here</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the usage:</span>
<span class="dt-fg">   |</span><span class="dt-fg">    Usage: prog (--fast | --slow)</span>
<span class="dt-fg">   |</span><span class="dt-fg">                          </span><span class="dt-caret">^^^^^^</span><span class="dt-label"> declared here</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: give it at most once, not with a mutually exclusive option</span></div>

!!! note
    The diagnostic on the exception is plain text: `render()` defaults to color off, because the message
    travels on `str(exc)` and is often inspected as a string. ANSI color is applied at the print site,
    not baked into the exception.

## The usage line you were closest to

When the usage lists several alternative invocations and the arguments fall short of one of them, docopt2
does not just say "no match" - it finds the line you got *furthest* into and points a caret at the one
element still missing. A matched command is strong evidence of intent, so the line whose command you typed
wins even when a later positional or option is absent:

```python
doc = """Usage:
  git push [--force] <remote>
  git commit --message=<msg>
  git add <path>...

Options:
  --force          Force.
  --message=<msg>  Message."""

docopt(doc, "push")
```

<div class="docopt2-term"><span class="dt-err dt-b">error</span><span class="dt-fg dt-b">: missing required `&lt;remote&gt;`</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the usage:</span>
<span class="dt-fg">   |</span><span class="dt-fg">      git push [--force] &lt;remote&gt;</span>
<span class="dt-fg">   |</span><span class="dt-fg">                         </span><span class="dt-caret">^^^^^^^^</span><span class="dt-label"> required here</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: closest of 3 usage patterns</span></div>

The snippet shows only the closest line - `git push`, not `commit` or `add` - because the caret is placed
in *that* line. Typing `git commit` instead carets `--message=<msg>` on the second line; `git deploy prod`
on a `deploy <env> <version>` line carets the missing `<version>`.

The ranking fires only with real evidence. A leading word that matches no line's command (`git clone`) is
not treated as a near-miss - there is nothing to be "closest" to - so docopt2 falls back to the plain
mismatch message rather than guess a line at random. A single-line usage has no alternatives to rank, so
it reports its missing element directly.

## A value that does not fit its type

A parse can succeed and still fail when a value cannot be coerced to its [schema](typed-results.md) field
type. That raises [`DocoptExit`](../reference/exceptions.md) too, rendered with the same two-span caret:
the offending value in the argv, tied to the usage element that declared its type.

```python
import dataclasses
from docopt2 import docopt

@dataclasses.dataclass
class Args:
    port: int

doc = "Usage: prog --port=<n>"
docopt(doc, "--port=abc", schema=Args)   # raises the diagnostic below
```

<div class="docopt2-term"><span class="dt-err dt-b">error</span><span class="dt-fg dt-b">: invalid value for `--port`</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the arguments:</span>
<span class="dt-fg">   |</span><span class="dt-fg">    --port=abc</span>
<span class="dt-fg">   |</span><span class="dt-fg">           </span><span class="dt-caret">^^^</span><span class="dt-label"> expected int</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the usage:</span>
<span class="dt-fg">   |</span><span class="dt-fg">    Usage: prog --port=&lt;n&gt;</span>
<span class="dt-fg">   |</span><span class="dt-fg">                </span><span class="dt-caret">^^^^^^^^^^</span><span class="dt-label"> typed as int</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: `abc` is not a valid int</span></div>

Only a **user value** gets this two-span treatment. A schema that disagrees with the usage - a field with
no matching element, an unsupported annotation - is the developer's error, not the user's, and raises
[`DocoptLanguageError`](../reference/exceptions.md) with no argv caret; see
[Typed results](typed-results.md#when-coercion-fails).

## A malformed usage at import time

A usage message that cannot be parsed raises [`DocoptLanguageError`](../reference/exceptions.md) with
the same caret treatment, so a broken spec fails loudly rather than silently. Because docopt2 parses the
usage on the first `docopt()` call, this is a developer error surfaced as soon as the interface is
exercised, not a user error.

An unclosed group points its single caret at the opener that was never closed:

```python
docopt("Usage: prog [--force <remote>", "push")
```

<div class="docopt2-term"><span class="dt-err dt-b">error</span><span class="dt-fg dt-b">: unclosed `[`</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the usage:</span>
<span class="dt-fg">   |</span><span class="dt-fg">    Usage: prog [--force &lt;remote&gt;</span>
<span class="dt-fg">   |</span><span class="dt-fg">                </span><span class="dt-caret">^</span><span class="dt-label"> opened here, but never closed</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: add `]` to close the group</span></div>

Mismatched delimiters draw two carets in one snippet, the opener and the closer that cannot match it:

```python
docopt("Usage: prog (a | b]", "a")
```

<div class="docopt2-term"><span class="dt-err dt-b">error</span><span class="dt-fg dt-b">: mismatched delimiters: `(` is closed by `]`</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the usage:</span>
<span class="dt-fg">   |</span><span class="dt-fg">    Usage: prog (a | b]</span>
<span class="dt-fg">   |</span><span class="dt-fg">                </span><span class="dt-caret">^</span><span class="dt-label"> `(` opens the group here</span>
<span class="dt-fg">   |</span><span class="dt-fg">                      </span><span class="dt-caret">^</span><span class="dt-label"> `]` cannot close it</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: close it with `)`, or open with `[`</span></div>

A closing bracket with nothing open is caught the same way, with the summary `unexpected closing`.

!!! tip
    To catch these before any argv is ever parsed, run the [usage linter](check.md). It renders the same
    diagnostics ahead of time, as warnings, so a malformed spec is reported in a test rather than on a
    user's first bad command.

## Opting into hints

The "did you mean" hint is opt-in. Without it, the same typo is reported by the generic mismatch path:

```python
doc = "Usage:\n  git push [--force] <remote>\n\nOptions:\n  --force  Force.\n"
docopt(doc, "push --forcce origin")   # suggest defaults to False
```

<div class="docopt2-term"><span class="dt-err dt-b">error</span><span class="dt-fg dt-b">: unexpected argument `--forcce`</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the arguments:</span>
<span class="dt-fg">   |</span><span class="dt-fg">    push --forcce origin</span>
<span class="dt-fg">   |</span><span class="dt-fg">         </span><span class="dt-caret">^^^^^^^^</span><span class="dt-label"> not allowed here</span>
<span class="dt-fg">   |</span></div>

Pass `suggest=True` and, when a mistyped long option resembles a known one within an edit-distance
threshold, docopt2 upgrades the message to the `unknown option` form: the "did you mean `--force`?"
help line plus the usage cross-reference shown at the top of this page.

The hint fires only on a genuine typo. With `allow_abbrev=True` (the default) an unambiguous prefix such
as `--for` already de-abbreviates to `--force`, so it is accepted and never flagged. A token like
`--forcce` is not a prefix of any known option, which is what marks it as a typo worth a suggestion.

!!! note
    `suggest` only affects long options (`--name`). Short flags and positional arguments fall through to
    the standard `unexpected argument` and `missing or mismatched arguments` diagnostics.

## See also

- [Exceptions](../reference/exceptions.md) - `DocoptExit` and `DocoptLanguageError`.
- [Usage linting](check.md) to catch defects before any argv is parsed.
- [Usage DSL](usage-dsl.md) - the grammar these diagnostics point back into.
