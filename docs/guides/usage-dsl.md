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
