# docopt2

Typed successor to docopt. The usage message is the parser spec.

```python
from docopt2 import docopt

args = docopt("Usage: prog <host> <port>", "127.0.0.1 8080")
args
# {'<host>': '127.0.0.1', '<port>': '8080'}   -> an Arguments, a dict subclass
```

No builder, no decorators. You write the help text you would have written anyway, and that text parses the
argv.

Pass a `schema=` and the same usage returns a typed object, each value coerced to its field type:

```python
import dataclasses

from docopt2 import docopt


@dataclasses.dataclass
class Args:
    host: str
    port: int  # coerced from the parsed string


args = docopt("Usage: prog <host> <port>", "127.0.0.1 8080", schema=Args)
args
# Args(host='127.0.0.1', port=8080)   -> port is an int, not a str
```

## Drop-in for docopt

`docopt2` parses the same usage grammar and returns the same mapping, so switching over is a one-line
import change.

It is a superset, not a bit-identical clone. It accepts some argvs the original rejects, and it fixes three
of the original's parsing bugs.
[Every divergence is pinned by name](concepts/design-boundaries.md#drop-in-compatibility).

Diagnostics come with it. Everything else is opt-in: typed results, linting, stubs, completion, dispatch.

!!! note "Zero dependencies"
    The core runs on the standard library alone. Nothing to install, nothing to audit. pydantic and
    Hypothesis are optional extras (`docopt2[pydantic]`, `docopt2[hypothesis]`), used only when you pass a
    pydantic model as a schema or reach for the Hypothesis strategy.

## Why docopt2

<div class="grid cards" markdown>

-   :material-shield-check:{ .lg .middle } __Typed results__

    ---

    Pass a dataclass, `TypedDict`, `Cli` subclass, or pydantic model as `schema=`. Values come back coerced
    to their field types, never a `dict[str, Any]`.

    [:octicons-arrow-right-24: Typed results](guides/typed-results.md)

-   :material-alert-circle:{ .lg .middle } __Diagnostics that point at the problem__

    ---

    A mismatch carets the offending token in your argv and cross-references the usage that rejected it.
    `suggest=True` adds a spell-checked "did you mean".

    [:octicons-arrow-right-24: Diagnostics](guides/diagnostics.md)

-   :material-sitemap:{ .lg .middle } __Subcommand dispatch__

    ---

    `Dispatch` routes a matched command path to its handler, optionally typed per command. It is the
    dispatch layer docopt itself omits.

    [:octicons-arrow-right-24: Subcommand dispatch](guides/dispatch.md)

-   :material-console-line:{ .lg .middle } __Shell completion__

    ---

    Context-aware completion scripts for bash, zsh, fish, PowerShell, and nushell. Tab offers only what is
    valid at the cursor.

    [:octicons-arrow-right-24: Shell completion](guides/completion.md)

-   :material-file-code:{ .lg .middle } __Schema codegen__

    ---

    `docopt2 stub` (or `generate_stub`) writes the typed schema from your usage, in three styles, so you
    never hand-write it.

    [:octicons-arrow-right-24: Schema stubs](guides/stub.md)

-   :material-layers-triple:{ .lg .middle } __Layered value resolution__

    ---

    Declare `[env: VAR]` and `[config: key]` in the usage. docopt2 resolves CLI over env over config over
    default, and `args.source()` reports which layer won.

    [:octicons-arrow-right-24: Layered fallback](guides/usage-dsl.md#environment-and-config-fallback)

-   :material-card-text-outline:{ .lg .middle } __Self-documenting `--help`__

    ---

    `help_style="rich"` renders an aligned, colored help screen. It scopes to the subcommand the user typed
    and shows where each value resolves from.

    [:octicons-arrow-right-24: Rich help](guides/help.md)

-   :material-flask-outline:{ .lg .middle } __Example generation__

    ---

    `docopt2 examples` (or `generate_examples`) samples the argvs your usage accepts. Use it for drift
    detection, parser fuzzing, or a Hypothesis strategy.

    [:octicons-arrow-right-24: Example generation](guides/examples.md)

-   :material-spellcheck:{ .lg .middle } __Static usage linter__

    ---

    `docopt2 check` (or `check`) lints the usage grammar itself: dead defaults, unusable options, ambiguous
    variadics. It catches them before they ship.

    [:octicons-arrow-right-24: Usage linting](guides/check.md)

-   :material-format-align-left:{ .lg .middle } __Usage formatter__

    ---

    `docopt2 fmt` (or `format_usage`) aligns the `Options:` block into one column. It is the formatter to
    `check`'s linter, and it never changes what the usage parses to.

    [:octicons-arrow-right-24: Formatting usage](guides/fmt.md)

-   :material-swap-horizontal:{ .lg .middle } __Round-trip codec__

    ---

    `format_argv` is the inverse of `docopt`. It rebuilds a canonical argv from a parsed result and
    verifies it by re-parsing, so one usage spec drives both directions.

    [:octicons-arrow-right-24: Round-trip to argv](guides/round-trip.md)

-   :material-compare:{ .lg .middle } __Compatibility checking__

    ---

    `check_compat` (or `docopt2 compat`) reports the invocations an old usage accepts that a new one
    rejects. It surfaces only breaks it can prove, so it fits a release gate.

    [:octicons-arrow-right-24: Compatibility checking](guides/compat.md)

</div>

## Install

```bash
pip install docopt2  # just change the import
```

See [Getting started](getting-started.md) to dive in, or browse the [Guides](guides/typed-results.md)
and the [API Reference](reference/overview.md) for the full surface.
