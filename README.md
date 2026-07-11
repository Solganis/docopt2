<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/logo.png">
    <img src="docs/assets/logo.png" alt="docopt2" width="200">
  </picture>
  <br>
  <b>Typed successor to docopt. The usage message is the parser spec.</b>
  <br>
  A drop-in replacement for <a href="https://github.com/docopt/docopt">docopt</a> - a superset, not a rewrite.
</p>

<p align="center">
  <a href="https://github.com/Solganis/docopt2/actions/workflows/ci.yml"><img src="https://github.com/Solganis/docopt2/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/docopt2/"><img src="https://img.shields.io/pypi/v/docopt2" alt="PyPI version"></a>
  <a href="https://pypi.org/project/docopt2/"><img src="https://img.shields.io/pypi/pyversions/docopt2" alt="Python"></a>
  <a href="https://codecov.io/gh/Solganis/docopt2"><img src="https://codecov.io/gh/Solganis/docopt2/graph/badge.svg" alt="Coverage"></a>
  <br>
  <a href="https://solganis.github.io/docopt2/"><img src="https://img.shields.io/badge/Docs-online-black" alt="Documentation"></a>
  <a href="https://docs.astral.sh/ruff/"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"></a>
  <a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json" alt="uv"></a>
  <a href="https://github.com/astral-sh/ty"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json" alt="ty"></a>
  <a href="https://scorecard.dev/viewer/?uri=github.com/Solganis/docopt2"><img src="https://api.scorecard.dev/projects/github.com/Solganis/docopt2/badge" alt="OpenSSF Scorecard"></a>
  <br>
  <img src="https://img.shields.io/badge/runtime%20deps-0-2ea043" alt="zero runtime dependencies, pydantic support optional">
  <img src="https://img.shields.io/badge/type--checked-ty%20%7C%20mypy%20%7C%20pyright-2ea043" alt="the typed API is checked by ty, mypy --strict, and pyright">
</p>

---

<h2 align="center"><a href="https://solganis.github.io/docopt2/getting-started/">Quick start</a></h2>

```bash
pip install docopt2  # just change the import
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

Every argument vector the original docopt accepts, docopt2 accepts identically -<br>
so switching over is a one-line import change, and everything below is opt-in.

<h2 align="center"><a href="https://solganis.github.io/docopt2/guides/usage-dsl/">Usage syntax</a></h2>

docopt2 reads the same usage DSL as docopt - the `Usage:` and `Options:` blocks *are* the spec. Quick legend:

<details>
<summary><b>Symbol reference</b></summary>

| Syntax | Meaning |
| --- | --- |
| `command` | A literal (sub)command, matched as-is. |
| `<arg>`, `ARG` | A positional argument. |
| `-o`, `--option` | An option (flag). |
| `--option=<val>` | An option that takes a value. |
| `[ ]` | Optional element(s). |
| `( )` | Required group. |
| `a \| b` | Mutually exclusive: choose one. |
| `element...` | Repeatable: one or more. |
| `[options]` | Stands in for every option listed under `Options:`. |
| `--` | Ends option parsing; the rest is positional. |
| `[default: <val>]` | An option's default value, declared under `Options:`. |

</details>

The legend covers the essentials; the [full usage grammar](https://solganis.github.io/docopt2/guides/usage-dsl/) - precedence, edge cases, and how each form maps to the parsed result - lives on the site.

<h2 align="center"><a href="https://solganis.github.io/docopt2/guides/typed-results/">Why typed docopt?</a></h2>

**docopt** hands you a dict of strings - no autocomplete, no static types, coercion by hand at every call site:

```python
args = docopt("Usage: app <host> <port> [--verbose]")
host = args["<host>"]        # unchecked, a bare string
port = int(args["<port>"])   # coerce by hand, at every call site
```

**docopt2** takes a schema and gives you a typed result back:

```python
@dataclasses.dataclass
class Args:
    host: str
    port: int                  # coerced from the parsed string
    verbose: bool

args = docopt("Usage: app <host> <port> [--verbose]", schema=Args)
args.port                      # statically an int, not a string
```

A dataclass, a `TypedDict`, the `Cli` base class, or a pydantic model all work as `schema=` -<br>
and you don't hand-write it, `docopt2 stub` generates it from the usage.

<h2 align="center"><a href="https://solganis.github.io/docopt2/guides/diagnostics/">Diagnostics that point at the problem</a></h2>

When the arguments don't match, **docopt** reprints the usage and leaves you to find the mistake:

```text
Usage:
  git commit [--message=<msg>] [--amend]
  git push [--force] <remote>
```

**docopt2** points at it - in the argv *and* the usage that rejected it:

<p align="center">
  <img src="docs/assets/diagnostic.png" width="620" alt="A docopt2 error: 'unknown option --forcce' with a caret under the token in the argument vector and a second caret under --force in the usage, plus a 'did you mean --force?' hint">
</p>

Malformed usage gets the same two carets, at import time - a broken spec fails loudly, not silently.

<h2 align="center"><a href="https://solganis.github.io/docopt2/guides/stub/">Generate the schema from the usage</a></h2>

Don't hand-write the schema - `docopt2 stub` generates it from your usage (a module docstring, a text file, or stdin):

```console
$ docopt2 stub naval.py
```

```python
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

Add `--style=typeddict` or `--style=cli` for the other shapes.<br>
Widen a field by hand (`speed: int`) and the coercion is automatic.

<h2 align="center"><a href="https://solganis.github.io/docopt2/guides/check/">Lint the usage before it ships</a></h2>

`docopt2 check` (or `docopt2.check(doc)` in code) lints the usage grammar itself -<br>
catching defects the parser would otherwise accept in silence:

<p align="center">
  <img src="docs/assets/check.png" width="857" alt="A docopt2 check warning: option --verbose is declared but never used, with a caret under its declaration in the options section and a help line on how to fix it">
</p>

It flags dead `[default: ...]` values, options declared but never usable,<br>
ambiguous variadic positionals, and redundant alternatives.

<h2 align="center"><a href="https://solganis.github.io/docopt2/guides/completion/">Shell completion</a></h2>

<p align="center">
  <img src="https://img.shields.io/badge/bash-3E4349?logo=gnubash&logoColor=white" alt="bash">
  <img src="https://img.shields.io/badge/zsh-3E4349?logo=zsh&logoColor=white" alt="zsh">
  <img src="https://img.shields.io/badge/fish-3E4349?logo=fishshell&logoColor=white" alt="fish">
  <img src="https://img.shields.io/badge/PowerShell-3E4349?logo=powershell&logoColor=white" alt="PowerShell">
</p>

Generate the completion script for your shell; Tab then narrows to exactly what is valid at the cursor -<br>
commands and options, never positional values - straight from the usage:

```console
$ naval <TAB>
--help  --speed  ship
$ naval ship <TAB>
--speed  new
$ naval ship titanic move 1 2 <TAB>
--speed
```

<h2 align="center"><a href="https://solganis.github.io/docopt2/guides/dispatch/">Subcommand dispatch</a></h2>

`Dispatch` routes each command to its own handler - no `if args["..."]` ladder:

```python
from docopt2 import Dispatch

app = Dispatch("""Usage:
  git add <path>...
  git commit --message=<msg>
""")

@app.on("add")
def add(args):
    print(f"adding {args['<path>']}")

@app.on("commit")
def commit(args):
    print(f"committing {args['--message']!r}")

app.run()   # parse argv, call the matched command's handler
```

<h2 align="center">Features</h2>

<table>
<tr>
<td valign="top" width="50%">
<a href="https://solganis.github.io/docopt2/guides/typed-results/"><b>Typed results</b></a><br>
A dataclass, <code>TypedDict</code>, <code>Cli</code>, or pydantic model as <code>schema=</code> - values coerced, result typed, not <code>Any</code>.
</td>
<td valign="top" width="50%">
<a href="https://solganis.github.io/docopt2/guides/diagnostics/"><b>Rustc-style diagnostics</b></a><br>
Two-span carets tie an argv mistake to the usage that rejected it, in color.
</td>
</tr>
<tr>
<td valign="top">
<a href="https://solganis.github.io/docopt2/guides/stub/"><b>Schema codegen</b></a><br>
<code>docopt2 stub</code> writes the typed schema from your usage, in three styles.
</td>
<td valign="top">
<a href="https://solganis.github.io/docopt2/guides/check/"><b>Static usage linter</b></a><br>
<code>docopt2 check</code> flags dead defaults, unusable options, and ambiguous variadics before they ship.
</td>
</tr>
<tr>
<td valign="top">
<a href="https://solganis.github.io/docopt2/guides/completion/"><b>Shell completion</b></a><br>
Context-aware scripts for bash, zsh, fish, and PowerShell.
</td>
<td valign="top">
<a href="https://solganis.github.io/docopt2/guides/dispatch/"><b>Subcommand dispatch</b></a><br>
<code>Dispatch</code> routes a matched command path to a handler, optionally typed per command.
</td>
</tr>
</table>

---

<p align="center">
  <a href="https://github.com/Solganis/docopt2/blob/main/LICENSE">MIT License</a> ·
  derived from docopt · see
  <a href="https://github.com/Solganis/docopt2/blob/main/NOTICE">NOTICE</a>
</p>
