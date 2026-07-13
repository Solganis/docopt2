# Example generation

`generate_examples` (and the `docopt2 examples` CLI) samples argument vectors from the usage grammar:
concrete invocations that your usage message accepts, walked straight out of the same pattern tree
[`docopt`](../reference/docopt.md) matches against. It never parses your program's real input and it is
not a test generator in the "assert the right answer" sense. It answers a narrower, useful question:
*what does my usage actually accept?* - and gives you those shapes as data you can diff, replay, or
fuzz against.

Every example is derived from the grammar, so it cannot drift from what `docopt` parses: if an edit to
the usage narrows or widens the accepted set, the generated examples change with it.

!!! note "Structural, not semantic"
    Positionals and option values are filled with placeholders (`v1`, `v2`, ...), not realistic domain
    values. The generator samples the *structure* of accepted invocations - which commands, options, and
    positionals may combine - not whether a `<port>` is a valid port. It exercises the shape of your CLI
    surface; your own validation is a separate concern.

## From code

`generate_examples(doc, *, count=10, valid=True, seed=None)` returns a list of argv token lists (no
program name). Each valid example is one `docopt` accepts:

```python
from docopt2 import generate_examples

doc = """Usage:
  naval ship new <name>...
  naval ship <name> move <x> <y> [--speed=<kn>]
  naval mine (set | remove) <x> <y>
  naval --help

Options:
  --speed=<kn>  Speed in knots [default: 10]."""

generate_examples(doc, count=6, seed=7)
# [['mine', 'set', 'v1', 'v2'],
#  ['--help'],
#  ['ship', 'new', 'v3'],
#  ['ship', 'new', 'v4', 'v5'],
#  ['ship', 'new', 'v6'],
#  ['ship', 'new', 'v7']]
```

The sampler covers every construct: alternation picks a branch (`mine set` vs the `ship` lines), a
`...` repetition emits one or more values (`new v4 v5`), an optional group is taken or skipped
(`[--speed=<kn>]`), and each positional or valued option gets a fresh placeholder.

`seed` makes the output reproducible - the same seed yields the same list, so you can commit it as a
golden file. Duplicates are dropped, so a grammar with few accepted shapes returns fewer than `count`:

```python
generate_examples("Usage: prog [-v]\n\nOptions:\n  -v  Verbose.", count=10, seed=1)
# [['-v'], []]   # only two argvs are accepted, so that is all you get - in seeded order

generate_examples("Usage: prog <x>", count=0)
# []
```

### Invalid examples

`valid=False` returns argvs the usage *rejects*: a valid shape with an undefined option appended. They
give you the reject-set to check your program's error handling against, the same way the valid set
checks its happy paths.

```python
generate_examples(doc, count=4, valid=False, seed=7)
# [['mine', 'set', 'v1', 'v2', '--unknown'],
#  ['--help', '--unknown'],
#  ['ship', 'new', 'v3', '--unknown'],
#  ['ship', 'new', 'v4', 'v5', '--unknown']]
```

Every one of these raises [`DocoptExit`](../reference/exceptions.md) when passed to `docopt`.

## What it is for

The examples are structural, so they will not catch a domain bug (a port out of range, a path that does
not exist). They catch *grammar* drift and exercise your *parsing* boundary:

- **Drift detection.** Golden-file `generate_examples(doc, seed=...)` in a test. When someone edits the
  usage, the diff shows exactly how the accepted set changed - a new shape appears, an old one vanishes -
  before the change ships. A silent narrowing of what your CLI accepts stops being silent.
- **Parser fuzzing.** Feed the valid set into your program and assert it never crashes on a shape its own
  usage accepts; feed the `valid=False` set in and assert each is rejected cleanly. It is a cheap smoke
  test that your `docopt` call and everything immediately behind it survive the full surface, not just
  the two argvs you happened to write by hand.

For property-based testing with shrinking, use the Hypothesis strategy below rather than a fixed list.

## From the command line

`docopt2 examples <source>` prints one example invocation per line, reading the usage from a `.py`
module docstring (without importing it), a text file of raw usage, or `-` for standard input:

<div class="docopt2-term"><span class="dt-fg">$ docopt2 examples naval.txt --count=5 --seed=7</span>
<span class="dt-fg">mine set v1 v2</span>
<span class="dt-fg">--help</span>
<span class="dt-fg">ship new v3</span>
<span class="dt-fg">ship new v4 v5</span>
<span class="dt-fg">ship new v6</span></div>

`--invalid` prints the reject-set instead, and `--seed=<n>` fixes the output:

<div class="docopt2-term"><span class="dt-fg">$ docopt2 examples naval.txt --count=3 --invalid --seed=7</span>
<span class="dt-fg">mine set v1 v2 --unknown</span>
<span class="dt-fg">ship new v3 --unknown</span>
<span class="dt-fg">ship new v4 v5 --unknown</span></div>

The flags are `--count=<n>` (how many, default 10), `--invalid` (reject-set), and `--seed=<n>`
(reproducible output). A non-integer `--count` or `--seed` exits `1` with an `error:` message.

## Property testing with Hypothesis

For real property-based tests, `docopt2.hypothesis.argv_strategy(doc)` turns the same sampler into a
[Hypothesis](https://hypothesis.readthedocs.io/) strategy. It needs the optional extra:

```bash
pip install docopt2[hypothesis]
```

Every drawn argv is one `docopt` accepts, and because each branch pick, repeat count, and optional is a
separate Hypothesis draw, a failing case shrinks toward a minimal one - optionals dropped, first
alternatives taken, fewest repeats:

```python
from hypothesis import given

from docopt2 import docopt
from docopt2.hypothesis import argv_strategy

DOC = """Usage:
  naval ship new <name>...
  naval ship <name> move <x> <y> [--speed=<kn>]
  naval mine (set | remove) <x> <y>"""


@given(argv_strategy(DOC))
def test_program_survives_every_accepted_shape(argv):
    run(docopt(DOC, argv))  # never crashes on an argv the usage accepts
```

Unlike a fixed list from `generate_examples`, the strategy keeps exploring new shapes across runs and
shrinks a failure to the smallest argv that still triggers it. `argv_strategy` raises
[`DocoptLanguageError`](../reference/exceptions.md) at once on a malformed usage, before any draw.

## See also

- [`generate_examples` and `argv_strategy`](../reference/examples.md) in the API reference.
- [Usage linting](check.md) - the static counterpart, checking the grammar without sampling it.
- [Usage DSL](usage-dsl.md) - the grammar the examples are sampled from.
