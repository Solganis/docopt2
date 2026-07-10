<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Solganis/docopt2/main/docs/assets/logo-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/Solganis/docopt2/main/docs/assets/logo.png">
    <img src="https://raw.githubusercontent.com/Solganis/docopt2/main/docs/assets/logo.png" alt="docopt2" width="200">
  </picture>
</p>

<p align="center">
  <b>Typed successor to docopt. The usage message is the parser spec.</b><br>
  A drop-in replacement for <a href="https://github.com/docopt/docopt">docopt</a> - a superset, not a rewrite.
</p>

<p align="center">
  <a href="https://github.com/Solganis/docopt2/actions/workflows/ci.yml"><img src="https://github.com/Solganis/docopt2/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/docopt2/"><img src="https://img.shields.io/pypi/v/docopt2" alt="PyPI version"></a>
  <a href="https://pypi.org/project/docopt2/"><img src="https://img.shields.io/pypi/pyversions/docopt2" alt="Python"></a>
  <a href="https://codecov.io/gh/Solganis/docopt2"><img src="https://codecov.io/gh/Solganis/docopt2/graph/badge.svg" alt="Coverage"></a>
  <br>
  <a href="https://docs.astral.sh/ruff/"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"></a>
  <a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json" alt="uv"></a>
  <a href="https://github.com/astral-sh/ty"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json" alt="ty"></a>
  <a href="https://scorecard.dev/viewer/?uri=github.com/Solganis/docopt2"><img src="https://api.scorecard.dev/projects/github.com/Solganis/docopt2/badge" alt="OpenSSF Scorecard"></a>
  <br>
  <img src="https://img.shields.io/badge/type--checked-ty%20%7C%20mypy%20%7C%20pyright-2ea043" alt="the typed API is checked by ty, mypy --strict, and pyright">
</p>

---

<h2 align="center">Quick start</h2>

```bash
pip install docopt2  # drop-in replacement for docopt, just change the import
```

```python
"""Naval Fate.

Usage:
  naval ship new <name>...
  naval ship <name> move <x> <y> [--speed=<kn>]
  naval --help

Options:
  --speed=<kn>  Speed in knots [default: 10].
"""
from docopt2 import docopt

args = docopt(__doc__)
# args is a dict: {"ship": True, "<name>": ["titanic"], "move": True, "--speed": "10", ...}
```

Every argument vector the original docopt accepts, docopt2 accepts identically - so
switching over is a one-line import change, and everything below is opt-in.

<h2 align="center">Why typed docopt?</h2>

**docopt** hands you a dict of strings - no autocomplete, no static types, coercion by hand at every call site:

```python
# docopt today
args = docopt("Usage: app <host> <port> [--verbose]")
host = args["<host>"]        # unchecked, a bare string
port = int(args["<port>"])   # coerce by hand, at every call site
```

**docopt2** takes a schema and gives you a typed result back:

```python
# docopt2
@dataclasses.dataclass
class Args:
    host: str
    port: int                  # coerced from the parsed string
    verbose: bool

args = docopt("Usage: app <host> <port> [--verbose]", schema=Args)
args.port                      # int, narrowed under mypy, pyright, and ty
```

A dataclass, a `TypedDict`, the `Cli` base class, or a pydantic model all work as `schema=` - and you don't hand-write it, `docopt2 stub` generates it from the usage.

<h2 align="center">Diagnostics that point at the problem</h2>

When the arguments don't match, **docopt** reprints the usage and leaves you to find the mistake:

```text
Usage:
  git commit [--message=<msg>] [--amend]
  git push [--force] <remote>
```

**docopt2** points at it - in the argv *and* the usage that rejected it:

<p align="center">
  <img src="https://raw.githubusercontent.com/Solganis/docopt2/main/docs/assets/diagnostic.png" width="620" alt="A docopt2 error: 'unknown option --forcce' with a caret under the token in the argument vector and a second caret under --force in the usage, plus a 'did you mean --force?' hint">
</p>

Malformed usage gets the same two carets, at import time - a broken spec fails loudly, not silently.

<h2 align="center">Generate the schema from the usage</h2>

Don't hand-write the schema - `docopt2 stub` generates it from your usage (a module docstring, a text file, or stdin):

```console
$ docopt2 stub naval.py
```

```python
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
    help: bool
```

Add `--style=typeddict` or `--style=cli` for the other shapes. Widen a field by hand
(`speed: int`) and the coercion is automatic.

<h2 align="center">Lint the usage before it ships</h2>

`docopt2 check` (or `docopt2.check(doc)` in code) lints the usage grammar itself - catching defects the parser would otherwise accept in silence:

<p align="center">
  <img src="https://raw.githubusercontent.com/Solganis/docopt2/main/docs/assets/check.png" width="620" alt="A docopt2 check warning: option --verbose is declared but never used, with a caret under its declaration in the options section and a help line on how to fix it">
</p>

It flags dead `[default: ...]` values, options declared but never usable, ambiguous variadic
positionals, and redundant alternatives.

<h2 align="center">Features</h2>

- **Drop-in compatibility** - `from docopt2 import docopt`; a superset of docopt.
- **Typed results** - a dataclass, `TypedDict`, `Cli` base class, or pydantic model as `schema=`; string values coerced to the field types, the result statically typed instead of `Any`.
- **Schema codegen** - `docopt2 stub` writes the typed schema from your usage, in three styles.
- **Rustc-style diagnostics** - two-span carets tie an argv mistake to the usage that rejected it, in color.
- **Static usage linter** - `docopt2 check` flags dead defaults, unusable options, and ambiguous variadics before they ship.
- **Shell completion** - context-aware, generated for bash, zsh, fish, and PowerShell.
- **Subcommand dispatch** - `Dispatch` routes a matched command path to a handler, optionally typed per command.
- **Zero runtime dependencies** - pydantic support is reflective and optional; the core imports nothing outside the standard library.

---

<p align="center">
  <a href="https://github.com/Solganis/docopt2/blob/main/LICENSE">MIT License</a> ·
  derived from docopt · see
  <a href="https://github.com/Solganis/docopt2/blob/main/NOTICE">NOTICE</a>
</p>
