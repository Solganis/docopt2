# Schema stubs

A schema written by hand states a second time what the usage already states. Two declarations of one
interface, and the copy drifts the first time someone edits only one of them.

So don't write it. `generate_stub` (and the `docopt2 stub` CLI) derives the class from the usage message
itself, ready to pass back as `docopt(doc, schema=...)`. The grammar already fixes every value's type, so
the class is derived, not guessed, and the usage stays the only source of truth.

Pass it to a [typed result](typed-results.md) and each key comes back coerced, and completed in your editor.

## From code

`generate_stub(doc)` returns Python source as a string. Print it, or write it to a module beside your
CLI.

```python
from docopt2 import generate_stub

source = generate_stub("Usage: prog <host> <port>", name="Args")
print(source)
```

prints:

```python
import dataclasses


@dataclasses.dataclass
class Args:
    host: str
    port: str
```

Every field is typed from the grammar: `str`, `str | None`, `int`, `bool`, or `list[str]`.

Widen a field by hand (`port: int`) to get coercion for free.

A larger usage exercises every shape at once:

```python
from docopt2 import generate_stub

doc = """Usage:
  deploy <app> [<env>] [--replicas=<n>] [--force] [-v...] <targets>...

Options:
  --replicas=<n>  Replica count [default: 3]."""
print(generate_stub(doc, name="Deploy"))
```

```python
import dataclasses


@dataclasses.dataclass
class Deploy:
    app: str
    env: str | None
    replicas: str
    force: bool
    v: int
    targets: list[str]
```

The annotation follows the [usage form](usage-dsl.md#what-each-form-produces), read across the whole usage:
a positional is `str` only when *every* usage line requires it, since a line that omits it can leave it unset.

| Grammar form | Field type |
| --- | --- |
| required positional `<app>` | `str` |
| optional positional `[<env>]` | `str \| None` |
| flag `--force`, command | `bool` |
| repeatable flag `-v...` | `int` (a count) |
| variadic positional `<targets>...` | `list[str]` |
| valued option with `[default: ...]` | `str` |
| valued option, no default | `str \| None` |

A `[default: ...]` fixes the value to a string, so `--replicas` lands as `str`. Widen it to `int` by
hand when you want the number coerced.

!!! note
    A usage key the typed API cannot represent does not silently vanish. It becomes a leading `# note`
    comment instead of a field, so the output is always valid Python.

    Two things trigger it:

    - two names collapsing to one field (`--file` and `<file>` both map to `file`)
    - a key that is not a valid identifier (`<class>`)

    ```python
    # note: usage keys `--file`, `<file>` all map to `file`; give them distinct names to type them

    import dataclasses


    @dataclasses.dataclass
    class Args:
        pass
    ```

    Rename the offending element in the usage, regenerate, and the field appears.

## The three styles

`style=` selects the output shape:

- `"dataclass"` (default) - a `@dataclasses.dataclass`, shown above.
- `"typeddict"` - a `TypedDict`.
- `"cli"` - a [`Cli`](../reference/cli.md) subclass with the usage embedded, so `Name.parse()` works
  standalone.

The same `deploy` usage as a `TypedDict`:

```python
print(generate_stub(doc, name="Deploy", style="typeddict"))
```

```python
from typing import TypedDict


class Deploy(TypedDict):
    app: str
    env: str | None
    replicas: str
    force: bool
    v: int
    targets: list[str]
```

As a `Cli` subclass the usage travels with the class in `__cli_doc__`, so `Deploy.parse(argv)` matches
and returns a typed `Deploy` with no separate `docopt()` call:

```python
print(generate_stub(doc, name="Deploy", style="cli"))
```

```python
from docopt2 import Cli


class Deploy(Cli):
    __cli_doc__ = """Usage:
  deploy <app> [<env>] [--replicas=<n>] [--force] [-v...] <targets>...

Options:
  --replicas=<n>  Replica count [default: 3]."""
    app: str
    env: str | None
    replicas: str
    force: bool
    v: int
    targets: list[str]
```

The field types are identical across styles. Only the container changes.

Pick `dataclass` or `typeddict` to feed [`docopt(doc, schema=...)`](typed-results.md), and `cli` when you want
the usage and the schema to live in one self-contained class.

## From the command line

```console
$ docopt2 stub naval.py
```

`docopt2 stub <source>` reads the usage from one of three input sources:

- a **Python file** (`.py`), whose module docstring is read without importing the module
- any other **text file**, whose raw content is the usage
- **`-`**, for standard input

Given a `naval.py` whose module docstring is the Naval Fate usage, the default `dataclass` style prints:

```console
$ docopt2 stub naval.py
import dataclasses


@dataclasses.dataclass
class Args:
    ship: bool
    new: bool
    name: list[str]
    move: bool
    x: str | None
    y: str | None
    speed: str
    shoot: bool
    mine: bool
    set: bool
    remove: bool
    moored: bool
    drifting: bool
    help: bool
    version: bool
```

Two flags shape the output:

- `--name=<name>` sets the class name (default `Args`).
- `--style=<style>` picks `dataclass`, `typeddict`, or `cli` (default `dataclass`).

```console
$ docopt2 stub naval.py --style=typeddict --name=Naval
from typing import TypedDict


class Naval(TypedDict):
    ship: bool
    new: bool
    name: list[str]
    move: bool
    x: str | None
    y: str | None
    speed: str
    shoot: bool
    mine: bool
    set: bool
    remove: bool
    moored: bool
    drifting: bool
    help: bool
    version: bool
```

Reading from stdin lets you pipe a usage straight in:

```console
$ printf 'Usage: prog <host> <port>' | docopt2 stub -
import dataclasses


@dataclasses.dataclass
class Args:
    host: str
    port: str
```

An unknown style is rejected before anything is generated:

```console
$ docopt2 stub naval.py --style=pydantic
error: --style must be dataclass, typeddict, or cli, not 'pydantic'
```

## See also

- [`generate_stub`](../reference/stub.md) in the API reference.
- [Typed results](typed-results.md) for what to do with the generated schema.
- [Usage DSL](usage-dsl.md) - the grammar forms each generated field is derived from.
