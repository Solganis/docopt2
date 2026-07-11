# Subcommand dispatch

`Dispatch` routes a matched command path to a handler - the subcommand dispatch layer docopt itself
omits. Register one handler per command path, then `run` parses argv and calls the handler for the most
specific path that matched.

## Register and run

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

`on("user", "create")` matches only when both `user` and `create` are truthy in the parsed result, and
a longer registered path outranks a shorter one. So a generic `on("user")` acts as a group fallback
while `on("user", "create")` and `on("user", "list")` handle the leaves:

```python
@app.on("user")
def user(args): ...            # user, with no known leaf

@app.on("user", "create")
def user_create(args): ...     # user create <name>

@app.on("user", "list")
def user_list(args): ...       # user list
```

Given the argv `user create alice`, the two-segment handler wins over the one-segment `on("user")`.

!!! note
    If a usage pattern matches but no registered path (not even the empty fallback) fits it, `run()`
    raises `DocoptExit` carrying `error: no handler is registered for the given command`. Argv that
    matches no usage pattern at all is rejected earlier by `docopt` itself, with the usual
    [diagnostic](diagnostics.md).

## Typed per command

Passing `schema=` to `on(...)` binds the parsed result to that schema, so each subcommand handler
receives its own typed view instead of the raw `Arguments` mapping.

```python
@app.on("user", "create", schema=CreateArgs)
def create(args: CreateArgs):
    ...
```

Dispatch always matches on the parsed mapping first, then binds per handler, so `schema` lives on
`on()` and is never forwarded through `run()`. A schema only needs to declare the fields that handler
reads; keys belonging to other subcommands are ignored. For the git-like CLI, typing just the `commit`
leaf:

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

The field name comes from the usage key: `--message` maps to `message`, `<path>` to `path`, and the
value is coerced to the declared field type. See [Typed results](typed-results.md) for the full key to
field mapping and the four schema shapes a handler can receive.

## Forwarding options

Extra keyword arguments to `run(...)` are forwarded to [`docopt`](../reference/docopt.md) (`suggest`,
`exit_code`, `version`, and so on). `schema` is not among them, since dispatch binds per handler.

```python
app.run(version="app 2.0")   # --version prints "app 2.0" and exits
```

## See also

- [`Dispatch`](../reference/dispatch.md) in the API reference.
- [Typed results](typed-results.md) for the schema shapes a handler can receive.
