# Usage DSL

docopt2 reads the same usage DSL as docopt. The `Usage:` and `Options:` blocks in your help message *are*
the parser spec.

Nothing is configured in code. You write the interface the way you would document it, and docopt2 derives
the parser from that text.

This guide is the full reference: every form, the value it produces, and how to inspect the parse tree.
Every result below is real `docopt()` output for the usage and argv above it.

## The two blocks

A help message has two blocks docopt2 reads, both found case-insensitively:

- **`Usage:`** - one or more invocation patterns. Each line until the next blank line is an alternative
  way to call the program. The leading word is the program name and is ignored when matching.
- **`Options:`** - one line per option, giving its short and/or long form, whether it takes a value, and
  an optional `[default: ...]`.

```text
Naval Fate.

Usage:
  naval ship new <name>...
  naval ship <name> move <x> <y> [--speed=<kn>]
  naval --help

Options:
  --speed=<kn>  Speed in knots [default: 10].
```

## Elements

A quick reference, then a worked example of each form.

| Form | Meaning |
| --- | --- |
| `command` | A literal (sub)command, matched as-is |
| `<arg>`, `ARG` | A positional argument |
| `-o`, `--option` | An option (flag) |
| `--option=<val>` | An option that takes a value |
| `[ ]` | Optional |
| `( )` | Required group |
| `a \| b` | Mutually exclusive: pick one |
| `element...` | Repeatable: one or more |
| `[options]` | Every option from the `Options:` block |
| `--` | Ends option parsing. The rest is positional |
| `[default: <val>]` | An option's default, declared in `Options:` |
| `[env: <var>]` | An option's environment-variable fallback, resolved after the command line |
| `[config: <key>]` | An option's config-file fallback, resolved against the `docopt(config=...)` mapping |

### Commands

A bare word is a literal command, matched verbatim. Its key in the result is `True` when present and
`False` otherwise. Chaining words builds a command path.

```python
docopt("Usage: prog ship new <name>", "ship new titanic", complete=False)
# {'ship': True, 'new': True, '<name>': 'titanic'}
```

### Positional arguments

`<name>`, or the uppercase `NAME` form. The value is the raw string. An optional positional that is
absent is `None`.

```python
docopt("Usage: prog <name>", "alice", complete=False)    # {'<name>': 'alice'}
docopt("Usage: prog [<name>]", "", complete=False)        # {'<name>': None}
```

### Options (flags)

`-v` or `--verbose`. Present is `True`, absent is `False`. Short flags stack, so `-abc` is `-a -b -c`.

```python
docopt("Usage: prog [-v]", "-v", complete=False)   # {'-v': True}
docopt("Usage: prog [-v]", "", complete=False)     # {'-v': False}
docopt("Usage: prog [-a] [-b] [-c]", "-abc", complete=False)
# {'-a': True, '-b': True, '-c': True}
```

A repeatable flag counts instead of toggling:

```python
docopt("Usage: prog [-v...]", "-v -v -v", complete=False)   # {'-v': 3}
```

### Options with a value

`--port=<n>` takes an argument. On the command line both `--port=8080` and `--port 8080` are accepted, and
the value is always a string.

```python
docopt("Usage: prog --port=<n>", "--port=8080", complete=False)   # {'--port': '8080'}
docopt("Usage: prog --port=<n>", "--port 8080", complete=False)   # {'--port': '8080'}
```

### Defaults

A `[default: ...]` in the `Options:` block supplies the value when the option is omitted.

```python
doc = "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [default: 80]."
docopt(doc, "", complete=False)   # {'--port': '80'}
```

!!! note
    `[default: ...]` applies only to options declared in the `Options:` block. A variadic positional
    that is absent defaults to an empty list, any other absent optional is `None`, and an absent flag is
    `False`.

### Environment and config fallback

Two annotations declare where an omitted option's value comes from, layered under `[default: ...]`:

- `[env: VAR]` reads an environment variable.
- `[config: dotted.key]` reads the mapping you pass as `docopt(config=...)` - a config file you loaded.

The precedence is **command-line argument > `[env: VAR]` > `[config: key]` > `[default: ...]`**. An explicit
argument always wins, and the default is the last resort.

So below, `8080` comes from the config, `7000` from `APP_PORT` once it is set, and `9000` from the explicit
`--port`:

```python
import os
from docopt2 import docopt

doc = """Usage: prog [--port=<n>]

Options:
  --port=<n>  Port [default: 80] [env: APP_PORT] [config: server.port]."""
cfg = {"server": {"port": 8080}}

os.environ.pop("APP_PORT", None)
docopt(doc, "", config=cfg, complete=False)             # {'--port': '8080'}
os.environ["APP_PORT"] = "7000"
docopt(doc, "", config=cfg, complete=False)             # {'--port': '7000'}
docopt(doc, "--port=9000", config=cfg, complete=False)  # {'--port': '9000'}
```

docopt2 never reads a file itself. That would add a dependency and lock in a format.

You load the config however you like (TOML, JSON, a `[tool.<prog>]` table) and pass the resulting mapping.
`[config: a.b.c]` walks the dotted path into it.

On a flag the value is read as a boolean: set, unless it reads as empty, `0`, `false`, `no`, or `off`.

Both fallbacks are opt-in per option, apply only to options that appear in the usage, and coerce through a
[schema](typed-results.md) like any other value.

Where a value came from stays visible:

- [`was_given`](typed-results.md#the-arguments-mapping) reports an env- or config-sourced value as *not*
  given, since it did not come from the command line.
- [`args.source(name)`](typed-results.md#where-a-value-came-from) reports which layer actually supplied it.
- The [rich `--help`](help.md#value-provenance) screen documents the same source chain, so users see where a
  value resolves from without reading the code.

!!! note "Empty is treated as absent"
    A blank or unset source falls through to the next layer - the shell `${VAR:-default}` convention - so
    an empty `APP_PORT=` never silently overrides the config or the default with an empty string. The same
    holds for a `null` or empty config value.

!!! warning "A config key must name a value, not a table"
    An option takes one value, so `[config: server]` against `{"server": {"port": 80}}` is a mistake. The
    key stops one level short.

    docopt2 says so, with a caret and the keys that would have worked, instead of handing `--server` the
    string `{'port': 80}`. Scalars, dates and times pass through as written.

### Generate a config skeleton

Once options declare `[config: key]`, [`generate_config_template`](../reference/config-templates.md) turns
those annotations into a ready-to-fill TOML file. It is the mirror image of the resolution above: the file
that the `docopt(config=...)` mapping is loaded from.

Each key lands under its table, seeded with the option's `[default: ...]`, and commented with the flag and
any `[env: VAR]` it also reads.

```python
from docopt2 import generate_config_template

doc = """Usage: prog [options]

Options:
  --host=<h>   Bind address [default: 0.0.0.0] [config: server.host].
  --port=<n>   Port [default: 8080] [env: APP_PORT] [config: server.port].
  --verbose    Log verbosely [config: logging.verbose]."""

print(generate_config_template(doc))
# [server]
# host = "0.0.0.0"  # --host
# port = 8080       # --port, env APP_PORT
#
# [logging]
# verbose = false  # --verbose
```

Options without a `[config:]` key are left out, and the output is valid TOML - integers, floats, and
booleans stay bare, everything else is quoted - so it round-trips straight back through `tomllib`.

!!! note "Contradictory keys fail loudly"
    Config keys that cannot coexist in one TOML document raise `DocoptLanguageError` rather than emit a
    broken file:

    - a duplicate key
    - a path that is a prefix of another. `[config: server]` beside `[config: server.port]` would use
      `server` as both a value and a table.

    Sibling keys under one table (`server.host` and `server.port`) are fine.

The `docopt2 config-template <source>` CLI prints the same skeleton from a `.py` module docstring, a
usage file, or `-` for standard input:

<div class="docopt2-term"><span class="dt-fg">$ docopt2 config-template serve.py</span>

<span class="dt-label">[server]</span>
<span class="dt-help">host</span><span class="dt-fg"> = "0.0.0.0"  </span><span class="dt-dim"># --host</span>
<span class="dt-help">port</span><span class="dt-fg"> = 8080       </span><span class="dt-dim"># --port, env APP_PORT</span>

<span class="dt-label">[logging]</span>
<span class="dt-help">verbose</span><span class="dt-fg"> = false  </span><span class="dt-dim"># --verbose</span></div>

### Optional `[ ]` and required `( )`

`[ ]` wraps elements that may be omitted. `( )` groups elements that must all be present, most often to
scope an alternation so the `|` binds where you intend.

### Mutually exclusive `|`

Inside a group, `|` offers a choice and exactly one branch matches. Branches that were not taken still
appear in the result, as `False`.

```python
docopt("Usage: prog (add|rm) <x>", "add foo", complete=False)
# {'add': True, 'rm': False, '<x>': 'foo'}
```

### Repetition `...`

A trailing `...` means one or more. A repeated positional collects into a list, and a repeated flag counts.

```python
docopt("Usage: prog <name>...", "a b c", complete=False)   # {'<name>': ['a', 'b', 'c']}
```

### The `[options]` shortcut

`[options]` stands in for every option described in the `Options:` block, so a pattern does not have to
list them all.

```python
doc = "Usage: prog [options] <f>\n\nOptions:\n  -v  Verbose.\n  --port=<n>  Port."
docopt(doc, "-v --port=9 file", complete=False)
# {'-v': True, '--port': '9', '<f>': 'file'}
```

### End of options `--`

A literal `--` on the command line stops option parsing. Everything after it is positional, even if it
looks like an option. Allow it in a pattern with `[--]`.

```python
docopt("Usage: prog [--] <args>...", "-- -x -y", complete=False)
# {'--': True, '<args>': ['-x', '-y']}
```

## What each form produces

The value type is fixed by the form, which is exactly what the [typed schema](typed-results.md) keys off:

| Form | Present | Absent |
| --- | --- | --- |
| flag `-v` | `True` | `False` |
| repeatable flag `-v...` | count (`int`) | `0` |
| command `cmd` | `True` | `False` |
| positional `<x>` | `str` | `None` |
| variadic positional `<x>...` | `list[str]` | `[]` |
| option `--opt=<v>` | `str` | the `[default:]`, otherwise `None` |

Those are the docopt-native forms: a flag or command answers with a boolean (a count, once it repeats),
and anything that carries a value answers with a string, or a list of them. Coercion to your own field
types happens when you pass a [schema](typed-results.md).

## Multiple usage patterns

Each line under `Usage:` is a full alternative. docopt2 matches the argument vector against the set of
patterns and accepts the first that fits. If none fit, it raises the [diagnostic](diagnostics.md) that
points at where the argv diverged from the usage.

## Inspecting the parse tree

`parse_tree(doc)` builds the usage-pattern tree without matching any argv, so you can `repr()` it, walk
it, or diff how a grammar change reshapes parsing. The `[options]` shortcut stays an `OptionsShortcut`
node rather than being expanded.

```python
from docopt2 import parse_tree

parse_tree("Usage: prog <host> <port>")
# Required(Required(Argument('<host>', None), Argument('<port>', None)))
```

## Parser primitives

The [pattern node classes](../reference/grammar.md) (`Pattern`, `Argument`, `Command`, `Option`, `Required`,
`Optional`, `Either`, `OneOrMore`, `OptionsShortcut`) and the low-level parser functions are exported,
because tools built on docopt reach into them.

They are the parser's own vocabulary, not a promise. The drop-in guarantee covers `docopt()` and the mapping
it returns, nothing below it. These names also follow docopt's unreleased master rather than the 0.6.2
spelling (`TokenStream`, `ChildPattern`, `ParentPattern`, `AnyOptions`).

For new code, prefer `docopt()` with a [schema](typed-results.md).

## See also

- [Usage linting](check.md) - validate a usage message statically before it ships.
- [Typed results](typed-results.md) - map the DSL onto a dataclass, `TypedDict`, `Cli`, or pydantic model.
- [Usage grammar](../reference/grammar.md) - the pattern node classes in the API reference.
