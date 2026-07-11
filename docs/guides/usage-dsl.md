# Usage DSL

docopt2 reads the same usage DSL as docopt: the `Usage:` and `Options:` blocks in your help message
*are* the parser spec. Nothing is configured in code - you write the interface the way you would
document it, and docopt2 derives the parser from it. This guide is the full reference: every form, the
value it produces, and how to inspect the parse tree. Every result shown below is the actual `docopt()`
output for the usage and argv above it.

## The two blocks

A help message has two blocks docopt2 reads, both found case-insensitively:

- **`Usage:`** - one or more invocation patterns. Each line until the next blank line is an alternative
  way to call the program; the leading word is the program name and is ignored when matching.
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
| `--` | Ends option parsing; the rest is positional |
| `[default: <val>]` | An option's default, declared in `Options:` |
| `[env: <var>]` | An option's environment-variable fallback, resolved after the command line |
| `[config: <key>]` | An option's config-file fallback, resolved against the `docopt(config=...)` mapping |

### Commands

A bare word is a literal command, matched verbatim. Its key in the result is `True` when present and
`False` otherwise; chaining words builds a command path.

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

`--port=<n>` takes an argument. On the command line both `--port=8080` and `--port 8080` are accepted;
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

The precedence is **command-line argument > `[env: VAR]` > `[config: key]` > `[default: ...]`**: an
explicit argument always wins, then the environment, then the config, then the default.

```python
import os
from docopt2 import docopt

doc = "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [default: 80] [env: APP_PORT] [config: server.port]."
cfg = {"server": {"port": 8080}}

os.environ.pop("APP_PORT", None)
docopt(doc, "", config=cfg, complete=False)              # {'--port': '8080'}  - from the config mapping
os.environ["APP_PORT"] = "7000"
docopt(doc, "", config=cfg, complete=False)              # {'--port': '7000'}  - the environment wins
docopt(doc, "--port=9000", config=cfg, complete=False)   # {'--port': '9000'}  - the argument wins
```

docopt2 never reads a file itself - that would add a dependency and lock in a format. You load the config
however you like (TOML, JSON, a `[tool.<prog>]` table) and pass the resulting mapping; `[config: a.b.c]`
walks the dotted path into it. On a flag the value is read as a boolean (set unless it reads as empty,
`0`, `false`, `no`, or `off`). Both fallbacks are opt-in per option, apply only to options that appear in
the usage, and coerce through a [schema](typed-results.md) like any other. A value from env or config is
still reported as *not* given by [`was_given`](typed-results.md#the-arguments-mapping), since it did not
come from the command line. The [rich `--help`](help.md#value-provenance) screen documents each option's
source chain, so users see where a value resolves from without reading the code.

!!! note "Empty is treated as absent"
    A blank or unset source falls through to the next layer - the shell `${VAR:-default}` convention - so
    an empty `APP_PORT=` never silently overrides the config or the default with an empty string. The same
    holds for a `null` or empty config value.

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

A trailing `...` means one or more. A repeated positional collects into a list; a repeated flag counts.

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

A literal `--` on the command line stops option parsing; everything after it is positional, even if it
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

Every value is a string, or a container of strings; coercion to `int`, `bool` fields, and so on happens
when you pass a [schema](typed-results.md).

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

The [pattern node classes](../reference/grammar.md) (`Pattern`, `Argument`, `Command`, `Option`,
`Required`, `Optional`, `Either`, `OneOrMore`, `OptionsShortcut`) and the low-level `parse_*` functions
are re-exported for drop-in compatibility with the original docopt module, whose users import them
directly. They are a compatibility surface: for new code, prefer `docopt()` with a
[schema](typed-results.md).

## See also

- [Usage linting](check.md) - validate a usage message statically before it ships.
- [Typed results](typed-results.md) - map the DSL onto a dataclass, `TypedDict`, `Cli`, or pydantic model.
- [Usage grammar](../reference/grammar.md) - the pattern node classes in the API reference.
