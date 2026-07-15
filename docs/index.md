# docopt2

Typed successor to docopt. The usage message is the parser spec.

`docopt2` is a drop-in replacement for [docopt](https://github.com/docopt/docopt): it parses the same
usage grammar and returns the same mapping, so switching over is a one-line import change. It is a
compatible superset rather than a bit-identical clone - it also accepts argvs the original rejects, and
it corrects three of the original's parsing bugs
([every divergence is pinned by name](concepts/design-boundaries.md#drop-in-compatibility)).

Diagnostics come with it. Everything else - typed results, linting, stubs, completion, dispatch - is opt-in.

!!! note "Zero dependencies"
    The core runs on the standard library alone - nothing to install, nothing to audit. pydantic and
    Hypothesis are optional extras (`docopt2[pydantic]`, `docopt2[hypothesis]`), used only when you pass a
    pydantic model as a schema or reach for the Hypothesis strategy.

## Why docopt2

<div class="grid cards" markdown>

-   :material-shield-check:{ .lg .middle } __Typed results__

    ---

    Pass a dataclass, `TypedDict`, `Cli` base class, or pydantic model as `schema=` and get a typed
    object back, with string values coerced to the field types instead of a `dict[str, Any]`.

    [:octicons-arrow-right-24: Typed results](guides/typed-results.md)

-   :material-alert-circle:{ .lg .middle } __Diagnostics that point at the problem__

    ---

    On a mismatch, a caret marks the offending token in the argument vector, cross-referenced to the usage
    that rejected it when the usage names that token. An argv that gets partway into a usage line gets a
    caret under the one element it still needs. Pass `suggest=True` for a spell-checked "did you mean" hint.

    [:octicons-arrow-right-24: Diagnostics](guides/diagnostics.md)

-   :material-sitemap:{ .lg .middle } __Subcommand dispatch__

    ---

    `Dispatch` routes a matched command path to a handler, optionally typed per command - the
    dispatch layer docopt itself omits.

    [:octicons-arrow-right-24: Subcommand dispatch](guides/dispatch.md)

-   :material-console-line:{ .lg .middle } __Shell completion__

    ---

    Context-aware completion scripts generated for bash, zsh, fish, and PowerShell.

    [:octicons-arrow-right-24: Shell completion](guides/completion.md)

-   :material-file-code:{ .lg .middle } __Schema codegen__

    ---

    `docopt2 stub` (or `generate_stub`) writes the typed schema from your usage, in three styles, so
    you never hand-write it.

    [:octicons-arrow-right-24: Schema stubs](guides/stub.md)

-   :material-layers-triple:{ .lg .middle } __Layered value resolution__

    ---

    Declare an option's fallback sources in the usage with `[env: VAR]` and `[config: key]`; docopt2
    resolves command line over environment over config over default, and `args.source()` reports which
    layer supplied each value. `generate_config_template` scaffolds the config file itself.

    [:octicons-arrow-right-24: Layered fallback](guides/usage-dsl.md#environment-and-config-fallback)

-   :material-card-text-outline:{ .lg .middle } __Self-documenting `--help`__

    ---

    Opt into `help_style="rich"` for an aligned, colored help screen that scopes to the subcommand the
    user typed and documents where each value resolves from - the `[env, config, default]` chain, taken
    straight from the usage text.

    [:octicons-arrow-right-24: Rich help](guides/help.md)

-   :material-flask-outline:{ .lg .middle } __Example generation__

    ---

    `docopt2 examples` (or `generate_examples`) samples the argvs your usage accepts - for drift
    detection, parser fuzzing, and a Hypothesis strategy.

    [:octicons-arrow-right-24: Example generation](guides/examples.md)

-   :material-spellcheck:{ .lg .middle } __Static usage linter__

    ---

    `docopt2 check` (or `check`) lints the usage grammar itself - dead defaults, unusable options,
    ambiguous variadics - before it ships.

    [:octicons-arrow-right-24: Usage linting](guides/check.md)

-   :material-format-align-left:{ .lg .middle } __Usage formatter__

    ---

    `docopt2 fmt` (or `format_usage`) reformats the `Options:` block - aligning descriptions into one
    column, tidying each spec - the format half to `check`'s lint, without changing what the usage parses to.

    [:octicons-arrow-right-24: Formatting usage](guides/fmt.md)

-   :material-swap-horizontal:{ .lg .middle } __Round-trip codec__

    ---

    `format_argv` is the inverse of `docopt`: it rebuilds a canonical argv from a parsed result and verifies
    it by re-parsing, so the argv it returns always parses back to `x` (a grammar whose argv is genuinely
    ambiguous raises rather than return a wrong one). One usage spec drives both parsing and synthesis.

    [:octicons-arrow-right-24: Round-trip to argv](guides/round-trip.md)

-   :material-compare:{ .lg .middle } __Compatibility checking__

    ---

    `check_compat` (or `docopt2 compat`) reports the invocations an old usage accepts that a new one
    rejects - the breaking changes to your CLI - so it drops into a release gate. It reports only breaks it
    can prove; an empty result means none was found, never that the two are compatible.

    [:octicons-arrow-right-24: Compatibility checking](guides/compat.md)

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
