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

The usage message is the parser spec. Describe the interface, hand it to `docopt`, and read the parsed
values back:

```python
from docopt2 import docopt

args = docopt("Usage: prog <host> <port>", "127.0.0.1 8080")
args["<host>"]  # "127.0.0.1"
args["<port>"]  # "8080"
```

A real program is the same shape, only longer. Save this as `naval_fate.py`:

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

When the arguments do not match any usage line, `docopt` prints the usage and exits non-zero instead of
returning:

```console
$ python naval_fate.py ship
error: arguments do not match this command
   = help: did you mean: ship new <name>
Usage:
  naval_fate ship new <name>...
  ...
```

The full grammar behind the usage message - groups, alternation, repetition, `[options]`, and `--` - is
covered in [Usage DSL](guides/usage-dsl.md); the error format above is covered in
[Diagnostics](guides/diagnostics.md).

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

## Next steps

- [Usage DSL](guides/usage-dsl.md) for the full grammar the usage message accepts.
- [Typed results](guides/typed-results.md) for the schema shapes and coercion.
- [Diagnostics](guides/diagnostics.md) for the error output on a mismatch.
- [Schema stubs](guides/stub.md) to generate the schema from your usage.
- Browse the [API Reference](reference/overview.md) for every exported name.
