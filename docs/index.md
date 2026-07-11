# docopt2

Typed successor to docopt. The usage message is the parser spec.

`docopt2` is a drop-in replacement for [docopt](https://github.com/docopt/docopt): every argument
vector the original accepts, docopt2 accepts identically, so switching over is a one-line import
change. Everything beyond that - typed results, diagnostics, linting, stubs, completion, dispatch -
is opt-in.

!!! note "Zero dependencies"
    The core imports nothing outside the Python standard library. pydantic support is optional and
    reflective (`pip install docopt2[pydantic]`), needed only when you pass a pydantic model as a schema.

## Why docopt2

<div class="grid cards" markdown>

-   :material-shield-check:{ .lg .middle } __Typed results__

    ---

    Pass a dataclass, `TypedDict`, `Cli` base class, or pydantic model as `schema=` and get a typed
    object back, with string values coerced to the field types instead of a `dict[str, Any]`.

    [:octicons-arrow-right-24: Typed results](guides/typed-results.md)

-   :material-alert-circle:{ .lg .middle } __Diagnostics that point at the problem__

    ---

    On a mismatch, a two-span caret ties the offending token in the argument vector to the usage that
    rejected it, in color, with a "did you mean" hint - not a bare reprint of the usage.

    [:octicons-arrow-right-24: Diagnostics](guides/diagnostics.md)

-   :material-file-code:{ .lg .middle } __Schema codegen__

    ---

    `docopt2 stub` (or `generate_stub`) writes the typed schema from your usage, in three styles, so
    you never hand-write it.

    [:octicons-arrow-right-24: Schema stubs](guides/stub.md)

-   :material-spellcheck:{ .lg .middle } __Static usage linter__

    ---

    `docopt2 check` (or `check`) lints the usage grammar itself - dead defaults, unusable options,
    ambiguous variadics - before it ships.

    [:octicons-arrow-right-24: Usage linting](guides/check.md)

-   :material-console-line:{ .lg .middle } __Shell completion__

    ---

    Context-aware completion scripts generated for bash, zsh, fish, and PowerShell.

    [:octicons-arrow-right-24: Shell completion](guides/completion.md)

-   :material-sitemap:{ .lg .middle } __Subcommand dispatch__

    ---

    `Dispatch` routes a matched command path to a handler, optionally typed per command - the
    dispatch layer docopt itself omits.

    [:octicons-arrow-right-24: Subcommand dispatch](guides/dispatch.md)

</div>

## Install

```bash
pip install docopt2  # just change the import
```

## Quick example

```python
from docopt2 import docopt

args = docopt("Usage: prog <host> <port>", "127.0.0.1 8080")
# args is an Arguments mapping: {"<host>": "127.0.0.1", "<port>": "8080"}
```

Pass a `schema=` and the same usage returns a typed object instead, with each value coerced to its
field type:

```python
import dataclasses

from docopt2 import docopt


@dataclasses.dataclass
class Args:
    host: str
    port: int  # coerced from the parsed string


args = docopt("Usage: prog <host> <port>", "127.0.0.1 8080", schema=Args)
# Args(host='127.0.0.1', port=8080) - args.port is statically an int, not a string
```

See [Getting started](getting-started.md) to dive in, or browse the [Guides](guides/typed-results.md)
and the [API Reference](reference/overview.md) for the full surface.
