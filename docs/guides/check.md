# Usage linting

A usage message can be wrong in ways docopt accepts in silence. Describe `--verbose` under `Options:` and
forget to put it on a usage line, and your help text advertises a flag the parser then rejects with
`unexpected argument`. Nothing complains until a user tries it.

`check` (and the `docopt2 check` CLI) lints the grammar itself, before any argv is parsed. It never raises
and never touches parsing: it reads the `Usage:`, `Options:` and `Arguments:` blocks, and reports what it
finds as a list of warnings.

So you can wire it into a test or a CI step, and fail the build on a grammar mistake instead of shipping it.

## From code

`check(doc)` takes the help string and returns a `list[Diagnostic]`, every entry at `"warning"`
level. An empty list means the grammar is clean.

```python
from docopt2 import check

doc = "Usage: prog\n\nOptions:\n  --verbose  Extra logging."
warnings = check(doc)
len(warnings)          # 1
warnings[0].level      # 'warning'
print(warnings[0].render())
```

Each entry is the same kind of [diagnostic](diagnostics.md) the runtime uses for parse errors.
`warning.render()` returns the block as text, and `warning.render(color=True)` produces the ANSI color shown
in the blocks below.

The list is purely informational. `check` does not mutate `doc`, and does not change how `docopt()` later
parses it.

!!! note
    A usage message too malformed to parse (an unbalanced group, say) returns no warnings - that error
    is not a lint, it surfaces at parse time when you call `docopt()`. `check` only reports grammar that
    parses but reads wrong.

## What it flags

`check` applies six rules. Each catches a construct the parser tolerates but that almost always means
the usage message says something you did not intend.

| Warning | Fires when |
| --- | --- |
| unusable option | an option in `Options:` appears in no usage line and no `[options]` shortcut is present to absorb it |
| dead default (option) | a `[default: ...]` sits on a value-taking option that every usage pattern requires, so it can never be applied |
| dead default (argument) | a `[default: ...]` in an `Arguments:` section sits on an always-required positional |
| ambiguous variadics | two `...` positionals share one sequence, leaving the token split between them undefined |
| redundant alternative | two branches of one alternation group are identical, so one can never be reached |
| empty `[options]` | a usage line uses `[options]` but no options are described |

Every warning is a `Diagnostic`. The unusable-option case, rendered, looks like this - the caret points
at the exact token in your source:

<div class="docopt2-term"><span class="dt-warn dt-b">warning</span><span class="dt-fg dt-b">: option `--verbose` is declared but never used</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the options:</span>
<span class="dt-fg">   |</span><span class="dt-fg">      --verbose</span><span class="dt-fg">  Extra logging.</span>
<span class="dt-fg">   |</span><span class="dt-fg">      </span><span class="dt-caret">^^^^^^^^^</span><span class="dt-label"> declared here</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: add `--verbose` to a usage line, or add `[options]` to accept it</span></div>

The other rules render the same way. Each example below pairs the smallest usage that triggers the
rule with the exact warning `check` returns.

### Unusable options

An option described in `Options:` but named on no usage line can never be set, unless a `[options]` shortcut
is there to accept it. Three ways to fix it:

- add the option to a usage line
- add `[options]`, which accepts every described option and suppresses the warning
- delete the description

```python
check("Usage: prog [options]\n\nOptions:\n  --verbose  Be loud.")   # []
```

### Dead defaults

A `[default: ...]` only applies when the element is absent, so if every usage pattern requires the element,
the default is unreachable.

It fires on options declared in `Options:`:

```python
doc = "Usage: prog --port=<n>\n\nOptions:\n  --port=<n>  Port [default: 80]."
print(check(doc)[0].render(color=True))
```

<div class="docopt2-term"><span class="dt-warn dt-b">warning</span><span class="dt-fg dt-b">: dead default on `--port`, which the usage always requires</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the options:</span>
<span class="dt-fg">   |</span><span class="dt-fg">      --port=&lt;n&gt;  Port [default: 80].</span>
<span class="dt-fg">   |</span><span class="dt-fg">                       </span><span class="dt-caret">^^^^^^^^^^^^^</span><span class="dt-label"> never applies</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: make `--port` optional with `[ ... ]`, or drop the default</span></div>

and, identically, on positionals documented in an `Arguments:` section:

```python
doc = "Usage: prog <host>\n\nArguments:\n  <host>  Host name [default: localhost]."
print(check(doc)[0].render(color=True))
```

<div class="docopt2-term"><span class="dt-warn dt-b">warning</span><span class="dt-fg dt-b">: dead default on `&lt;host&gt;`, which the usage always requires</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the arguments:</span>
<span class="dt-fg">   |</span><span class="dt-fg">      &lt;host&gt;  Host name [default: localhost].</span>
<span class="dt-fg">   |</span><span class="dt-fg">                        </span><span class="dt-caret">^^^^^^^^^^^^^^^^^^^^</span><span class="dt-label"> never applies</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: make `&lt;host&gt;` optional with `[&lt;host&gt;]`, or drop the default</span></div>

The fix is either to wrap the element in `[ ... ]` so it becomes optional (and the default can fill
in), or to drop the default.

### Ambiguous variadics

Two variadic positionals in the same sequence have no defined boundary. Given `prog a b c`, docopt2 cannot
know where `<a>...` stops and `<b>...` starts.

This warning carries no caret, since the defect is the pair, not one token.

```python
print(check("Usage: prog <a>... <b>...")[0].render(color=True))
```

<div class="docopt2-term"><span class="dt-warn dt-b">warning</span><span class="dt-fg dt-b">: ambiguous grammar: two variadic positionals share one sequence</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: the token split between them is undefined; make one non-variadic, or split into branches</span></div>

It counts each `...` over a positional as one unit along a single path. So both of these are fine:

- `(<a> <b>)...` is one repeat with a fixed interleaving, not two competing ones.
- Two variadics in separate `|` branches never meet on the same path.

```python
check("Usage: prog (<a> <b>)...")        # []
check("Usage: prog (<a>... | <b>...)")   # []
```

### Redundant alternatives

Two identical branches inside one alternation group mean one of them can never match. Usually it is a
copy-paste slip or a typo in what was meant to be a distinct branch.

```python
print(check("Usage: prog (add | add)")[0].render(color=True))
```

<div class="docopt2-term"><span class="dt-warn dt-b">warning</span><span class="dt-fg dt-b">: redundant alternative: this branch repeats an earlier one</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: one of the identical `|` alternatives can never be reached; remove it or fix the typo</span></div>

### Empty `[options]`

A usage line uses the `[options]` shortcut, but there is no `Options:` section for it to expand, so it
matches nothing.

```python
print(check("Usage: prog [options] <f>")[0].render(color=True))
```

<div class="docopt2-term"><span class="dt-warn dt-b">warning</span><span class="dt-fg dt-b">: `[options]` accepts nothing - no options are described</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the usage:</span>
<span class="dt-fg">   |</span><span class="dt-fg">    Usage: prog [options] &lt;f&gt;</span>
<span class="dt-fg">   |</span><span class="dt-fg">                </span><span class="dt-caret">^^^^^^^^^</span><span class="dt-label"> expands to nothing</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: describe options in an `Options:` section, or remove `[options]`</span></div>

## From the command line

`docopt2 check <source>` runs the same lint over a usage message read from `<source>`, which is one of:

- a `.py` file - its module docstring is read (without importing the module),
- a text file of raw usage,
- `-` for standard input.

Warnings are written to standard error. The command exits `0` when the grammar is clean and `1` when
any warning was reported, so it drops into a pre-commit hook or a CI job as a gate:

<div class="docopt2-term"><span class="dt-fg">$ docopt2 check cli.py</span>
<span class="dt-warn dt-b">warning</span><span class="dt-fg dt-b">: dead default on `--name`, which the usage always requires</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the options:</span>
<span class="dt-fg">   |</span><span class="dt-fg">      --name=&lt;who&gt;  Who to greet [default: world].</span>
<span class="dt-fg">   |</span><span class="dt-fg">                                 </span><span class="dt-caret">^^^^^^^^^^^^^^^^</span><span class="dt-label"> never applies</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: make `--name` optional with `[ ... ]`, or drop the default</span>
<span class="dt-warn dt-b">warning</span><span class="dt-fg dt-b">: option `--shout` is declared but never used</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the options:</span>
<span class="dt-fg">   |</span><span class="dt-fg">      --shout       Upper-case the greeting.</span>
<span class="dt-fg">   |</span><span class="dt-fg">      </span><span class="dt-caret">^^^^^^^</span><span class="dt-label"> declared here</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: add `--shout` to a usage line, or add `[options]` to accept it</span></div>

The `cli.py` above is the module whose docstring is:

```text
Usage: greet --name=<who>

Options:
  --name=<who>  Who to greet [default: world].
  --shout       Upper-case the greeting.
```

!!! tip
    Because a warning sets exit status `1`, `docopt2 check src/app.py` in CI fails the build on a
    grammar defect - the same guarantee the [`check`](../reference/check.md) function gives a test,
    without importing your program.

## See also

- [`check`](../reference/check.md) in the API reference.
- [Diagnostics](diagnostics.md) for the runtime (mismatch) counterpart.
- [Usage DSL](usage-dsl.md) - the grammar `check` lints.
- [Generate a stub](stub.md) - the other `docopt2` subcommand.
