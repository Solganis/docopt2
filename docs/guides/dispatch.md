# Subcommand dispatch

docopt hands you a parsed mapping and stops there. Routing `git commit` to the code that commits is left to
you, and it usually grows into an `if`/`elif` ladder over the parsed keys.

`Dispatch` is that missing layer.

## Register and run

Register one handler per command path. `run` then parses argv and calls the handler for the most specific
path that matched.

```python
from docopt2 import Dispatch

app = Dispatch(doc)


@app.on("user", "create")
def create(args):
    ...


app.run()
```

An `on()` with no command path registers a fallback, used when no more specific path matches.

A complete git-like CLI. The module docstring *is* the usage message, so `Dispatch(__doc__)` needs
nothing else:

```python
"""A tiny git-like CLI.

Usage:
  app add <path>...
  app commit --message=<msg>
  app push [--force]
  app

Options:
  --message=<msg>  Commit message.
  --force          Force the push.
"""

from docopt2 import Dispatch

app = Dispatch(__doc__)


@app.on("add")
def add(args):
    print(f"adding {args['<path>']}")


@app.on("commit")
def commit(args):
    print(f"committing: {args['--message']!r}")


@app.on("push")
def push(args):
    print("force push" if args["--force"] else "push")


@app.on()
def default(args):
    print("no subcommand given")


if __name__ == "__main__":
    app.run()
```

Each invocation is parsed once, then routed to the single handler whose command path matched:

```console
$ python app.py add src tests
adding ['src', 'tests']
$ python app.py commit --message="first commit"
committing: 'first commit'
$ python app.py push --force
force push
$ python app.py
no subcommand given
```

`run()` returns whatever the handler returns, so its value can serve as the process exit code or be
asserted in a test.

### Most specific path wins

`on("user", "create")` matches only when both `user` and `create` are truthy in the parsed result, and a
longer registered path outranks a shorter one.

So a generic `on("user")` acts as a group fallback, while `on("user", "create")` and `on("user", "list")`
handle the leaves:

```python
@app.on("user")
def user(args): ...            # user, with no known leaf

@app.on("user", "create")
def user_create(args): ...     # user create <name>

@app.on("user", "list")
def user_list(args): ...       # user list
```

Given the argv `user create alice`, the two-segment handler wins over the one-segment `on("user")`.

!!! note "Two different ways an argv can go unhandled"
    - **A usage pattern matches, but no registered path fits it**, not even the empty fallback. `run()`
      raises `DocoptExit` carrying `error: no handler is registered for the given command`.
    - **No usage pattern matches at all.** `docopt` itself rejects the argv earlier, with the usual
      [diagnostic](diagnostics.md).

## Options every subcommand shares

A global `--verbose` (or `--config`, `--dry-run`) belongs to no single subcommand.

Where you write it in a usage line does not constrain where the user types it. Options match
position-independently, so `app --verbose add src` and `app add src --verbose` are the same parse either
way.

The choice is only about how you *declare* it, and it trades repetition against scope.

Declare it per line and each subcommand accepts its own options and no others:

```python
"""Usage:
  app add <path>... [--verbose]
  app commit --message=<msg> [--verbose]
  app push [--force] [--verbose]

Options:
  --verbose        Chatty.
  --message=<msg>  Commit message.
  --force          Force the push.
"""
```

Here `app commit --message=m --force` is rejected: the commit line never declared `--force`.

Or use the [`[options]` shortcut](usage-dsl.md#the-options-shortcut) - declare them once under `Options:`
and let every line take the lot:

```python
"""Usage:
  app add [options] <path>...
  app commit [options] --message=<msg>
  app push [options]

Options:
  --verbose        Chatty.
  --message=<msg>  Commit message.
  --force          Force the push.
"""
```

That is the DRY form, but it is deliberately loose. `[options]` expands to *every* option in the section, so
`app commit --message=m --force` now parses, `--force` and all.

`check` does not flag it. This is a legitimate shape, not a mistake.

Reach for it when the options really are shared, and for the per-line form when a subcommand must refuse
another's flags.

Either way the handler reads the shared option from its own `args`, like any other key:

```python
@app.on("add")
def add(args):
    if args["--verbose"]:
        ...
```

## Typed per command

Passing `schema=` to `on(...)` binds the parsed result to that schema, so each subcommand handler
receives its own typed view instead of the raw `Arguments` mapping.

```python
@app.on("user", "create", schema=CreateArgs)
def create(args: CreateArgs):
    ...
```

Dispatch always matches on the parsed mapping first, then binds per handler. That is why `schema` lives on
`on()` and is never forwarded through `run()`.

A schema only needs to declare the fields that handler reads, and keys belonging to other subcommands are
ignored. For the git-like CLI, typing just the `commit` leaf:

```python
from dataclasses import dataclass

from docopt2 import Dispatch

app = Dispatch(__doc__)


@dataclass
class CommitArgs:
    message: str


@app.on("commit", schema=CommitArgs)
def commit(args: CommitArgs):
    print(f"committing: {args.message!r}")
```

```console
$ python app.py commit --message="first commit"
committing: 'first commit'
```

The field name comes from the usage key. `--message` maps to `message`, `<path>` to `path`, and the value is
coerced to the declared field type.

See [Typed results](typed-results.md) for the full key-to-field mapping, and the four schema shapes a handler
can receive.

### Completing values

A table answers a shell's completion request itself, and the schemas of its handlers say which values there
are. Take two commands that share an option:

```python
from dataclasses import dataclass
from typing import Literal

from docopt2 import Dispatch

deploy_doc = """Usage:
  app deploy <env> [--format=<f>]
  app status [--format=<f>]

Options:
  --format=<f>  Output format.
"""
tool = Dispatch(deploy_doc)


@dataclass
class DeployArgs:
    env: Literal["dev", "prod"]
    format: Literal["json", "yaml"] | None


@dataclass
class StatusArgs:
    format: Literal["yaml", "table"] | None


@tool.on("deploy", schema=DeployArgs)
def deploy(args: DeployArgs): ...


@tool.on("status", schema=StatusArgs)
def status(args: StatusArgs): ...
```

```console
$ app deploy <TAB>
--format  --format=json  --format=yaml  dev  prod
$ app deploy dev --format <TAB>
json  yaml
$ app status --format <TAB>
table  yaml
```

The typed words leave some handlers in reach: those that can still be the one run once the line is whole.
After `deploy` that is the `deploy` handler alone, so its schema completes the line. `json` is its format
and `table` the `status` handler's, and `--format` completes each for its own command. Its schema reads the
words already typed too: after `app deploy nowhere` nothing is offered.

While several handlers are in reach, the value of an option is offered only where each of them that
declares the field takes it: before any command, `app --format <TAB>` offers `yaml`. A positional is
completed by the handler that is run for the line as it would be finished. On a line that two commands
share, `app (deploy | status) <env>`, each command is offered the environments of its own handler. See
[Completing values](completion.md#completing-values).

### Checking the table

[`check(doc, schema=...)`](check.md#checking-a-schema) holds a schema against the whole usage, as
`docopt(doc, schema=...)` binds it. A handler binds its schema only on the lines it is run for, so held
that way an element that those lines always give is reported as one that may be absent:

```python
from docopt2 import check

[found.summary for found in check(deploy_doc, schema=DeployArgs)]
# ['usage element `<env>` may be absent, but field `env` is not optional']
```

`tool.check()` holds each schema against the lines of its own handler, and has nothing to report here:

```python
tool.check()
# []
```

A usage line is held whole. Where one line serves two commands, `app (add <name> | list)`, `<name>` is
reported as one that may be absent for the handler of `add` too: give such commands lines of their own.

A finding names its handler. A handler that no argv can reach is reported as well, a mistyped command
among them:

```python
typo = Dispatch(deploy_doc)


@typo.on("staus")
def mistyped(args): ...


[found.summary for found in typo.check()]
# ['handler `staus` can never run: the usage has no `staus`']
```

## Forwarding options

Extra keyword arguments to `run(...)` pass straight through to [`docopt`](../reference/docopt.md), so
anything the parser accepts works from dispatch too:

```python
app.run(version="app 2.0")   # --version prints "app 2.0" and exits
```

`suggest`, `exit_code`, `version`, `help_style`, `config`, `allow_extra` and the rest all forward unchanged.

`schema` is the one exception, and `run()` refuses it rather than quietly ignoring it:

```text
TypeError: Dispatch.run() takes no `schema`; register one per handler with `on(..., schema=...)`
```

Dispatch matches on the parsed mapping first, and binds each handler its own typed view only afterwards. A
schema on `run()` would type the very thing being routed on, so it belongs on `on()`.

## See also

- [`Dispatch`](../reference/dispatch.md) in the API reference.
- [Typed results](typed-results.md) for the schema shapes a handler can receive.
