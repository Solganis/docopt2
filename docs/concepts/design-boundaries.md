# Design boundaries

docopt2 is a compatible superset of docopt, not a rewrite. The boundaries below are deliberate design
commitments, not gaps to fill later. Each is a feature docopt2 chooses not to have, with the reasoning
that keeps the tool small and the reasoning you can check against the code.

## Drop-in compatibility

docopt2 parses the same usage grammar and returns the same mapping the original returns, keyed by usage
element name. Switching over is a one-line import change - `from docopt import docopt` becomes
`from docopt2 import docopt` - and every added capability is opt-in. The return type is `Arguments`, a
plain `dict` subclass, so existing code that treats the result as a dictionary keeps working unchanged.

```python
from docopt2 import docopt

docopt("Usage: prog <host> <port>", "127.0.0.1 8080")
# {'<host>': '127.0.0.1', '<port>': '8080'}   -> an Arguments, a dict subclass
```

It is a compatible **superset**, not a bit-identical clone, and the difference is worth being precise
about. docopt2 computes the greedy match first - the exact result the original produces - and only when
that leaves tokens unconsumed does it keep looking, bounded by a match limit, for an alternative that
consumes the whole argv. So it accepts argvs the original rejects.

It also **corrects three of the original's parsing bugs**, and where the original misbehaved, the result
differs. A differential run over a corpus of usage messages found exactly these three, and nothing else:

| argv | the original | docopt2 |
| --- | --- | --- |
| `--to a --to b c`, where `--to` repeats across two usage lines | `{'--to': ['a', 'b', 'b']}` - the last value is duplicated | `{'--to': ['a', 'b']}` |
| `-s=25`, a short option written with `=` | `{'-s': '=25'}` - the separator is kept in the value | `{'-s': '25'}` |
| `-v -- -x`, where the usage does not declare `--` | `{'<args>': ['--', '-x']}` - the separator leaks in | `{'<args>': ['-x']}` |

A program that leaned on one of those will notice; nothing else changes. Every divergence is pinned by
name in [`tests/test_divergences.py`](https://github.com/Solganis/docopt2/blob/main/tests/test_divergences.py).

!!! note
    The extra keyword parameters (`schema`, `suggest`, `allow_extra`, `negative_numbers`, and the rest)
    are all keyword-only and default to the original behavior, so adding them cannot change how an
    existing call parses.

## Zero runtime dependencies

The core imports nothing outside the standard library. pydantic support is reflective (docopt2 never
`import`s pydantic) and offered only as the optional `docopt2[pydantic]` extra. This is a property
people specifically value in the original docopt and it must never regress.

Reflective means the pydantic path is entered by duck typing, not by importing the package: when a
schema exposes a callable `model_validate`, docopt2 delegates coercion to it, otherwise it uses its own
binder. Importing docopt2 therefore never pulls pydantic into the process.

```python
import sys
import docopt2

"pydantic" in sys.modules
# False
```

The `docopt2[pydantic]` extra is only a convenience version pin for users who pass a pydantic model as
`schema=`; the package's own dependency list stays empty.

## The usage message is the spec

There is no separate parser-builder API. The `Usage:` and `Options:` blocks are the single source of
truth; typed schemas, stubs, linting, and completion are all derived from that same string.

This is the core docopt idea, and it sets the direction of the whole design. Frameworks like argparse,
Click, and Typer build the parser in code (`add_argument` calls, decorators, parameter annotations) and
generate the help text from that construction. docopt2 reverses the arrow: you write the help text, and
the parser is derived from it. So there is deliberately no `add_argument` and no parser object to
assemble. By default, `--help` prints the usage message verbatim.

```python
from docopt2 import docopt

doc = "Naval Fate.\n\nUsage:\n  naval ship <name> move <x> <y> [--speed=<kn>]\n\nOptions:\n  --speed=<kn>  Speed in knots [default: 10]."
docopt(doc, "--help")
# Naval Fate.
#
# Usage:
#   naval ship <name> move <x> <y> [--speed=<kn>]
#
# Options:
#   --speed=<kn>  Speed in knots [default: 10].
```

The boundary here is against a second *source of truth*, not against presentation.
[`help_style="rich"`](../guides/help.md) renders an aligned, colored help screen, and it does not cross
that line: it is rendered from the same string, out of the annotations the parser already reads, so there
is nothing to keep in sync. What docopt2 will not have is a help layout you *define* separately from the
usage - a second definition that could disagree with the string that actually drives parsing.

Because there is only one string, the [stub generator](../guides/stub.md), the
[usage linter](../guides/check.md), [shell completion](../guides/completion.md) and the
[rich help](../guides/help.md) all read the same grammar the parser reads, and cannot drift from it.

## A parser, not an interaction framework

docopt2 turns an argv into values and stops. It never reads from stdin, never prompts for a missing
value, and never renders a TUI, a menu, or a progress display. A missing required argument produces a
[diagnostic](../guides/diagnostics.md) and a non-zero exit, not a "please enter host:" prompt.

The public surface reflects this. There is no `prompt`, `input`, `confirm`, or widget in the API: every
exported name is a parse entry point (`docopt`, `Cli`, `Dispatch`), a tool derived from the same usage
string, or a parser primitive kept for compatibility. `Dispatch` routes a parsed command to a handler,
but it is still routing, not interaction - it calls your function, it does not talk to the user.

Keeping docopt2 to the deterministic parse step is what makes it composable and trivially testable: pass
an argv, get values or a diagnostic. The only outside state a parse reads is what an option explicitly
asks for - an [`[env: VAR]`](../guides/usage-dsl.md#environment-and-config-fallback) annotation reads
that one variable, and a config mapping is one you hand in yourself - so a test sets the inputs rather
than stubbing a channel. Prompting, spinners, tables, and colors beyond the diagnostic itself belong to
the surrounding program or a dedicated library, layered on top of the parsed result.

## Typing without runtime magic

The typed surface is plain typing with no runtime cost. The [`Cli`](../reference/cli.md) base class is
the only decorator-shaped sugar, and it is deliberately a base class rather than a method-injecting
decorator, so the result keeps real static types a type checker can see instead of degrading to `Any`.

Typing is a layer over the drop-in core, not a rewrite of it. The same `docopt()` call runs the same
parse; passing `schema=` adds one final bind step that coerces the string values to the field types you
declared and returns a typed object instead of the mapping. Omit `schema=` and you get the plain dict.

```python
from dataclasses import dataclass
from docopt2 import docopt

@dataclass
class Args:
    host: str
    port: int

docopt("Usage: prog <host> <port>", "127.0.0.1 8080", schema=Args)
# Args(host='127.0.0.1', port=8080)   -> port coerced from '8080' to int
```

`Cli` is a base class you subclass, not a decorator, for a precise reason: a decorator that injected a
`.parse()` method would erase the subclass type to `Any` under static checkers, defeating the point of
typing the result. A base class keeps `YourCli.parse(...)` statically typed as `YourCli`.

```python
from dataclasses import dataclass
from docopt2 import Cli

@dataclass
class Move(Cli):
    __cli_doc__ = "Usage: naval <x> <y>"
    x: int
    y: int

Move.parse("10 20")
# Move(x=10, y=20)
```

There is no metaclass, no code generation, and no annotation rewriting behind this. Binding is ordinary
`get_type_hints` reflection performed once, at parse time; nothing is patched onto your class.

## See also

- [Usage DSL](../guides/usage-dsl.md) - the help-message grammar the parser is derived from.
- [Typed results](../guides/typed-results.md) - opt into a dataclass, `TypedDict`, `Cli`, or pydantic schema.
- [Cli base class](../reference/cli.md) - the class-first typed entry point.
- [docopt & results](../reference/docopt.md) - the drop-in function and the `Arguments` mapping.
