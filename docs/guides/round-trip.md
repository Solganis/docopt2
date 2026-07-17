# Round-trip: results back to argv

Sometimes you have the parsed result and need the command back: to log the exact invocation behind a run, or
to hand an argv to a subprocess. Rebuilding it by gluing strings together is where the quoting bugs live.

`docopt` turns an argv into a result. [`format_argv`](../reference/docopt.md) does the inverse, so one usage
message drives *both* directions. The same spec that parses `./data ./backups --compress` also synthesizes
it from the parsed values.

```python
from docopt2 import docopt, format_argv

doc = """Usage: prog <source> <dest> [--compress] [--keep=<n>]

Options:
  --keep=<n>  Keep [default: 5]."""

args = docopt(doc, "./data ./backups --compress --keep=10", complete=False)
format_argv(args, doc)   # ['./data', './backups', '--compress', '--keep=10']
```

## The contract

`format_argv(result, doc)` returns an argv token list (no program name) that parses back to `result`:

```python
docopt(doc, format_argv(args, doc), complete=False) == args   # always True
```

That equality is the whole point, and it is a **guarantee, not a hope**. Internally `format_argv` generates a
candidate argv from each usage line and re-parses it, returning the first that reproduces the result.

So the output is always *a* valid argv, though not necessarily the shortest one, nor the exact string the
user typed. The canonical form is fixed and predictable:

- **Everything that carries a value.** What the user supplied, plus whatever `[env:]` or `[config:]` resolved.
  Only elements left at their `[default: ...]` are omitted, so a defaulted `--keep` would not appear and an
  explicit one would.
- **Env and config values are written out**, never skipped, so the argv stands on its own. A persisted command
  that silently depended on an unrecorded variable would not reproduce the run.
- **Usage order.** Tokens follow the order of the matched usage line.
- **Long form.** An option is written `--name=value` when it has a long form, `-x value` when it is short only.
  A counted flag repeats (`-v -v -v`), a repeatable option repeats (`--x=1 --x=2`).
- **The line the result took.** For a multi-pattern usage, the alternative the result matched is chosen (the
  `commit` line for a commit result), verified by the re-parse.

A result that no usage pattern can reproduce raises `ValueError` rather than return a wrong argv.

That means a hand-built or inconsistent mapping, or a degenerate grammar in which one value is reachable
through differently-shaped positions (`(-a | -b)...`, `[<name>] <path> <name>`). Such a shape has a genuinely
ambiguous argv, so there is no single canonical form to return.

## What it is for

- **Reproducible commands.** Log or persist the exact invocation behind a run, the "copy as command" button,
  rebuilt from the typed values rather than by string-mangling the original input. Because env- and
  config-sourced values are written out rather than skipped, the logged command still reproduces the run on a
  machine where `APP_PORT` was never set.
- **Safe subprocess construction.** `format_argv` returns a token list, which is exactly the shape
  `subprocess.run` wants. Build the child's argv from a validated result instead of interpolating strings and
  hoping the quoting survives a path with a space in it.
- **Diffing invocations.** Two runs typed differently normalize to the same canonical argv, since `--keep 10`
  and `--keep=10` both come back as `--keep=10`. A diff then shows what actually differed, not how it was
  typed.
- **Property testing.** Combined with the [Hypothesis strategy](examples.md#property-testing-with-hypothesis),
  `docopt(format_argv(x)) == x` is a round-trip invariant your own CLI inherits for free.

```python
from hypothesis import given

from docopt2 import docopt, format_argv
from docopt2.hypothesis import argv_strategy

DOC = "Usage:\n  git push [--force] <remote>\n  git commit --message=<msg>"


@given(argv_strategy(DOC))
def test_every_result_round_trips(argv):
    result = docopt(DOC, argv, help=False)
    assert docopt(DOC, format_argv(result, DOC), help=False) == result
```

## See also

- [`docopt` and `format_argv`](../reference/docopt.md) in the API reference.
- [Example generation](examples.md) - synthesize *sample* argvs from the grammar, rather than one from a result.
- [Typed results](typed-results.md) - the `Arguments` mapping `format_argv` reads, including `provided`.
