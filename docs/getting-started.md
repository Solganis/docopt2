# Getting started

## Install

```bash
pip install docopt2
```

docopt2 has zero runtime dependencies: the core imports nothing outside the Python standard library.
pydantic support is reflective and optional (`docopt2[pydantic]`).

!!! tip "Coming from the original docopt?"
    docopt2 is a drop-in replacement on Python 3.10+. Change the import and every argument vector the
    original accepts still parses identically; everything else is opt-in.

## Your first parse

The usage message is the parser spec. Describe the interface as text, hand it to `docopt`, and read the
parsed values back by name. Start with two positional arguments:

```python
from docopt2 import docopt

args = docopt("Usage: prog <host> <port>", "127.0.0.1 8080")
args["<host>"]  # "127.0.0.1"
args["<port>"]  # "8080"
```

(In a real program you call `docopt(__doc__)` and it reads `sys.argv`; passing the argv here just keeps
the examples self-contained.)

Add an **option that takes a value**. `[--port=<n>]` is optional, and the `[default: ...]` declared under
`Options:` fills it in when the flag is absent:

```python
doc = "Usage: prog <host> [--port=<n>]\n\nOptions:\n  --port=<n>  [default: 8000]"

docopt(doc, "localhost")["--port"]              # "8000" - the default fills in
docopt(doc, "localhost --port=9000")["--port"]  # "9000" - the argument wins
```

A bare **flag** carries no value: it is `True` when present, `False` when absent:

```python
doc = "Usage: prog [--verbose] <host>"

docopt(doc, "--verbose example.com")["--verbose"]  # True
docopt(doc, "example.com")["--verbose"]            # False
```

A **command** is a literal word (a bool, like a flag), and a trailing `...` makes an element
**repeatable** - its value comes back as a list:

```python
args = docopt("Usage: prog add <file>...", "add a.txt b.txt")
args["add"]     # True
args["<file>"]  # ['a.txt', 'b.txt']
```

Positionals, options with defaults, flags, commands, repetition - that is the whole vocabulary, and a real
program just combines them. Save this as `naval_fate.py`:

```python
"""Naval Fate.

Usage:
  naval_fate ship new <name>...
  naval_fate ship <name> move <x> <y> [--speed=<kn>]
  naval_fate ship shoot <x> <y>
  naval_fate mine (set|remove) <x> <y> [--moored | --drifting]
  naval_fate -h | --help
  naval_fate --version

Options:
  -h --help     Show this screen.
  --version     Show the version.
  --speed=<kn>  Speed in knots [default: 10].
  --moored      Moored (anchored) mine.
  --drifting    Drifting mine.

"""

from docopt2 import docopt

if __name__ == "__main__":
    arguments = docopt(__doc__, version="Naval Fate 2.0")
    print(arguments)
```

`from docopt2 import docopt` is the only line a docopt user changes. The module docstring is the whole
parser: `docopt(__doc__, ...)` reads the `Usage:` and `Options:` blocks out of it and matches
`sys.argv[1:]` against them. Run it:

```console
$ python naval_fate.py ship new Titanic Bismarck
{'--drifting': False,
 '--help': False,
 '--moored': False,
 '--speed': '10',
 '--version': False,
 '<name>': ['Titanic', 'Bismarck'],
 '<x>': None,
 '<y>': None,
 'mine': False,
 'move': False,
 'new': True,
 'remove': False,
 'set': False,
 'ship': True,
 'shoot': False}
```

Every element in the usage becomes a key: each command is `True` or `False`, each positional holds its
string (or a list under `...`, or `None` when absent), and `--speed` already carries its
`[default: 10]`. Read the values back by name. A second call fills different keys:

```console
$ python naval_fate.py ship Titanic move 1 2 --speed=15
```

```python
arguments["ship"]      # True
arguments["move"]      # True
arguments["<name>"]    # ['Titanic']
arguments["<x>"]       # '1'
arguments["--speed"]   # '15'
```

!!! note "Help and version are handled for you"
    Because `-h`/`--help` and `--version` appear in the usage, docopt2 answers them before your code
    runs: `--help` prints the docstring and exits, and `--version` prints the `version` you passed.

    ```console
    $ python naval_fate.py --version
    Naval Fate 2.0
    ```

When the arguments do not match, `docopt` does not return a broken result - it points at what is missing
and exits non-zero. Move a ship, but forget the second coordinate:

<div class="docopt2-term"><span class="dt-fg">$ python naval_fate.py ship Titanic move 1</span>
<span class="dt-err dt-b">error</span><span class="dt-fg dt-b">: missing required `&lt;y&gt;`</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the usage:</span>
<span class="dt-fg">   |</span><span class="dt-fg">      naval_fate ship &lt;name&gt; move &lt;x&gt; &lt;y&gt; [--speed=&lt;kn&gt;]</span>
<span class="dt-fg">   |</span><span class="dt-fg">                                      </span><span class="dt-caret">^^^</span><span class="dt-label"> required here</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-note">note</span><span class="dt-fg">: of 6 usage patterns, your arguments came closest to this one</span></div>

docopt2 finds the usage line you got closest to and carets the one element it still needs (the full usage
is printed beneath, trimmed here). Other mismatches - an unknown option, a value that will not fit its
type - get the same pointed treatment, cross-referencing your argv and the usage; see
[Diagnostics](guides/diagnostics.md). The full grammar behind the usage message - groups, alternation,
repetition, `[options]`, and `--` - is in [Usage DSL](guides/usage-dsl.md).

## Typed results

Reading string keys out of a mapping is the original docopt contract. The next step is to pass a schema
and get a typed object back, with values coerced to the field types:

```python
import dataclasses

from docopt2 import docopt


@dataclasses.dataclass
class Args:
    host: str
    port: int  # coerced from the parsed string


args = docopt("Usage: prog <host> <port>", "127.0.0.1 8080", schema=Args)
args           # Args(host='127.0.0.1', port=8080)
args.port      # 8080, now an int
```

The `port` field is annotated `int`, so the parsed `"8080"` comes back as an `int`, and static type
checkers see `args.port` as an `int`. A schema can be a dataclass, a `TypedDict`, a
[`Cli`](reference/cli.md) subclass, or a pydantic model. Each shape, the coercions docopt2 performs, and
how a coercion failure surfaces are covered in [Typed results](guides/typed-results.md).

You do not have to write the schema by hand. `docopt2 stub naval_fate.py` reads the usage and prints a
ready-to-edit dataclass (or a `TypedDict`, or a `Cli` subclass) with every field typed from the grammar;
widen a field like `speed: int` and the coercion follows. See [Schema stubs](guides/stub.md).

## Next steps

- [Usage DSL](guides/usage-dsl.md) for the full grammar the usage message accepts.
- [Typed results](guides/typed-results.md) for the schema shapes and coercion.
- [Diagnostics](guides/diagnostics.md) for the error output on a mismatch.
- [Schema stubs](guides/stub.md) to generate the schema from your usage.
- Browse the [API Reference](reference/overview.md) for every exported name.
