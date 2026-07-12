# Typed results

Pass a schema to `docopt` and the parsed result comes back as a typed object with values coerced to
the field types, instead of an `Arguments` mapping of strings. The schema is the single source of truth
for both the runtime values and the static type: type checkers see the concrete schema type, not
`dict[str, Any]`, so `result.port` is a known `int` and a typo in a field name is caught before you run.

!!! note "How keys become field names"
    A docopt key is normalized to a Python identifier: the leading `-`/`--` is dropped, the surrounding
    `<`/`>` is stripped, letters are lowercased, and spaces and hyphens become underscores. So `--dry-run`
    binds to `dry_run`, `<input file>` to `input_file`, `NAME` to `name`, and a command `add` to `add`.
    Every field the schema declares must have exactly one matching usage element, or binding raises
    `DocoptLanguageError`.

## The four schema shapes

`schema=` accepts any of:

- a `@dataclasses.dataclass`
- a `TypedDict`
- a [`Cli`](../reference/cli.md) subclass (class-first API)
- a pydantic model (reflective, optional - no `import pydantic` in the core)

### Dataclass

The plain case: annotate the fields, and each is coerced to its declared type.

```python
import dataclasses
from docopt2 import docopt

@dataclasses.dataclass
class Args:
    host: str
    port: int
    verbose: bool

doc = "Usage: prog [--verbose] <host> <port>"
docopt(doc, "--verbose 127.0.0.1 8080", schema=Args, complete=False)
# Args(host='127.0.0.1', port=8080, verbose=True)
```

### TypedDict

Same field declarations, but the result is a plain `dict` whose values are typed by the `TypedDict`. A
`total=False` class, or per-field `NotRequired[...]`, marks a key that may be left out when its element
is absent.

```python
from typing import TypedDict
from docopt2 import docopt

class Args(TypedDict):
    host: str
    port: int
    verbose: bool

doc = "Usage: prog [--verbose] <host> <port>"
docopt(doc, "127.0.0.1 8080", schema=Args, complete=False)
# {'host': '127.0.0.1', 'port': 8080, 'verbose': False}
```

### `Cli` base class

The class-first form: subclass [`Cli`](../reference/cli.md), put the usage in `__cli_doc__`, and call
`.parse(argv)`. It returns an instance typed as the subclass, so the doc and the schema live together in
one class.

```python
from docopt2 import Cli

class Server(Cli):
    __cli_doc__ = "Usage: server [--verbose] <host> <port>"
    host: str
    port: int
    verbose: bool

server = Server.parse("--verbose 127.0.0.1 8080", complete=False)
server.host, server.port, server.verbose   # ('127.0.0.1', 8080, True)
```

### Pydantic model

A pydantic model is detected reflectively (by its `model_validate` method), so the core never imports
pydantic and the dependency stays optional. The mapping is remapped to field names and handed to
pydantic, which does its own validation and coercion.

```python
import pydantic
from docopt2 import docopt

class Settings(pydantic.BaseModel):
    host: str
    port: int
    verbose: bool

doc = "Usage: prog [--verbose] <host> <port>"
docopt(doc, "127.0.0.1 8080", schema=Settings, complete=False)
# Settings(host='127.0.0.1', port=8080, verbose=False)
```

!!! note "Pydantic coerces itself"
    With a pydantic model, docopt does not run the coercion below; pydantic validates every field. Keys
    are matched to the model's field names and aliases (pydantic validates by alias), and any parsed
    element the model does not declare is dropped rather than rejected.

## Coercion

For a dataclass, `TypedDict`, or `Cli` subclass, each parsed value is coerced from its docopt-native
form (a `str`, a container of `str`, a `bool`, or an `int` flag count) to the declared field type. The
supported set is closed:

| Annotation | Coerced with | Note |
| --- | --- | --- |
| `str` | unchanged | the raw token |
| `int` | `int(value)` | also a repeatable flag's count |
| `float` | `float(value)` | |
| `bool` | truthiness of the flag | must map to a flag, not a value-bearing element |
| `list[T]`, `list` | each item coerced to `T` | `T` defaults to `str` |
| `T \| None` | `None` stays `None`, else coerce to `T` | for an optional element |
| `Literal["a", "b"]` | the value, if it is one of the literals | a closed set of choices; validated |
| `enum.Enum` subclass | `EnumType(value)` | matched by member value |
| `pathlib.Path` | `Path(value)` | |
| `decimal.Decimal` | `Decimal(value)` | |
| `uuid.UUID` | `UUID(value)` | |
| `datetime.datetime` | `datetime.fromisoformat(value)` | ISO 8601 |
| `datetime.date` | `date.fromisoformat(value)` | ISO 8601 |

Any other annotation raises `DocoptLanguageError` (typed docopt cannot coerce it).

```python
import dataclasses, enum
from datetime import datetime
from decimal import Decimal
from docopt2 import docopt

class Level(enum.Enum):
    LOW = "low"
    HIGH = "high"

@dataclasses.dataclass
class Job:
    when: datetime
    level: Level
    retries: int
    ratio: float
    price: Decimal
    tags: list[str]

doc = "Usage: run <when> <level> <retries> <ratio> <price> <tags>..."
docopt(doc, "2026-07-11T09:00 high 3 0.75 9.99 web api", schema=Job, complete=False)
# Job(when=datetime.datetime(2026, 7, 11, 9, 0), level=<Level.HIGH: 'high'>,
#     retries=3, ratio=0.75, price=Decimal('9.99'), tags=['web', 'api'])
```

An absent optional element yields `None`, so its field must be optional (`T | None`) or carry a default:

```python
@dataclasses.dataclass
class Args:
    host: str
    label: str | None = None

docopt("Usage: prog <host> [<label>]", "127.0.0.1", schema=Args, complete=False)
# Args(host='127.0.0.1', label=None)
```

### When coercion fails

The two failure modes are distinct.

A **user** value that cannot be coerced (say `int("eighty")`) raises `DocoptExit`, the same exception a
non-matching argv raises, rendered as the same
[two-span diagnostic](diagnostics.md#a-value-that-does-not-fit-its-type): a caret under the value in the
argv, cross-referenced to the usage element that typed it. It exits with the `exit_code` (`1` by default),
so bad input is reported like any other command-line error. For a closed set of choices - a `Literal[...]`
or an `Enum` - the diagnostic lists the valid values (`expected one of debug, info, warn`), and a mistyped
value gets a spell-checked `did you mean` suggestion (`inof` -> `did you mean info?`, transpositions
included), so the user sees exactly what is allowed rather than a bare type name.

```python
@dataclasses.dataclass
class P:
    port: int

docopt("Usage: prog <port>", "eighty", schema=P)   # raises the diagnostic below
```

<div class="docopt2-term"><span class="dt-err dt-b">error</span><span class="dt-fg dt-b">: invalid value for `&lt;port&gt;`</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the arguments:</span>
<span class="dt-fg">   |</span><span class="dt-fg">    eighty</span>
<span class="dt-fg">   |</span><span class="dt-fg">    </span><span class="dt-caret">^^^^^^</span><span class="dt-label"> expected int</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   |</span><span class="dt-dim">  in the usage:</span>
<span class="dt-fg">   |</span><span class="dt-fg">    Usage: prog &lt;port&gt;</span>
<span class="dt-fg">   |</span><span class="dt-fg">                </span><span class="dt-caret">^^^^^^</span><span class="dt-label"> typed as int</span>
<span class="dt-fg">   |</span>
<span class="dt-fg">   = </span><span class="dt-help">help</span><span class="dt-fg">: `eighty` is not a valid int</span></div>

A **schema** that disagrees with the usage raises `DocoptLanguageError` (a programmer error, not a user
one): a field with no matching element, two elements colliding on one field, a non-optional field bound to
an element that may be absent, an unsupported annotation, or a `bool` field mapped to a value-bearing
element rather than a flag.

## The Arguments mapping

Without a schema, `docopt` returns an [`Arguments`](../reference/docopt.md) mapping - a `dict` subclass
of element names to values. Alongside the items it carries two extras:

- `provided`, the frozenset of names actually supplied in argv, so a value left at its `[default: ...]`
  is distinguishable from one the user typed. `was_given(name)` is the membership test.
- `extra`, the surplus tokens kept when `allow_extra=True` lets a partial match through.

```python
doc = "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [default: 80]."

args = docopt(doc, "", complete=False)
args["--port"], args.was_given("--port")        # ('80', False)  -> defaulted

args = docopt(doc, "--port 9000", complete=False)
args["--port"], args.was_given("--port")        # ('9000', True) -> explicit
```

### Where a value came from

`was_given` answers *did the user type this?*; `source(name)` answers the sharper *which layer supplied
it?* when an option has [`[env:]`/`[config:]` fallbacks](usage-dsl.md#environment-and-config-fallback). It
returns a [`Source`](../reference/docopt.md) enum member - `CLI`, `ENV`, `CONFIG`, or `DEFAULT` - in the
same precedence order docopt2 resolves them, so you can log or branch on provenance instead of guessing.

```python
import os
from docopt2 import Source, docopt

doc = """Usage: prog [--port=<n>]

Options:
  --port=<n>  Port [default: 80] [env: APP_PORT] [config: server.port]."""
cfg = {"server": {"port": 8080}}

os.environ.pop("APP_PORT", None)
args = docopt(doc, "", config=cfg, complete=False)
args["--port"], args.source("--port")   # ('8080', Source.CONFIG) - config file

os.environ["APP_PORT"] = "7000"
args = docopt(doc, "--port=9000", config=cfg, complete=False)
args.source("--port") is Source.CLI     # True - the command line still wins
```

```python
doc = "Usage: prog <cmd>"
args = docopt(doc, "run leftover1 leftover2", allow_extra=True, complete=False)
args.extra                              # ['leftover1', 'leftover2']
```

## See also

- [`docopt` and `Arguments`](../reference/docopt.md) in the API reference.
- [`Cli` base class](../reference/cli.md) for the class-first form.
- [Schema stubs](stub.md) to generate a schema from the usage.
