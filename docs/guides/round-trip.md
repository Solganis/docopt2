# Round-trip: results back to argv

`docopt` turns an argv into a result. [`format_argv`](../reference/docopt.md) does the inverse: it turns a
result back into an argv the usage accepts. One usage message thus drives *both* directions - the same spec
that parses `./data ./backups --compress` also synthesizes it from the parsed values.

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

That equality is the whole point, and it is a **guarantee, not a hope**: internally `format_argv` generates a
candidate argv from each usage line and re-parses it, returning the first that reproduces the result. So the
output is always *a* valid argv - though not necessarily the shortest one, nor the exact string the user
typed. The canonical form is fixed and predictable:

- **only what was supplied.** Elements left at their `[default: ...]` are omitted - `format_argv` emits exactly
  `result.provided` (see [the Arguments mapping](typed-results.md#the-arguments-mapping)), so a defaulted
  `--keep` would not appear, an explicit one would.
- **usage order.** Tokens follow the order of the matched usage line.
- **long form.** An option is written `--name=value` when it has a long form, `-x value` when it is short only;
  a counted flag repeats (`-v -v -v`), a repeatable option repeats (`--x=1 --x=2`).
- **the line the result took.** For a multi-pattern usage, the alternative the result matched is chosen (the
  `commit` line for a commit result), verified by the re-parse.

A result that no usage pattern can reproduce - only ever a hand-built or inconsistent mapping, never a genuine
`docopt` result - raises `ValueError` rather than return a wrong argv.

## What it is for

- **Reproducible commands.** Log or persist the exact invocation behind a run ("copy as command"), rebuilt from
  the typed values rather than by string-mangling the original input.
- **Safe subprocess construction.** Build an argv for a child process from a validated result, instead of
  interpolating strings and hoping the quoting is right.
- **Diffing invocations.** Normalize two results to their canonical argv and compare.
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
