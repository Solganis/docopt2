"""A tiny git-like CLI.

Usage:
  dispatch add <path>...
  dispatch commit --message=<msg>
  dispatch push [--force]

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
    print(f"committing: {args['--message']}")


@app.on("push")
def push(args):
    print("force push" if args["--force"] else "push")


# Register one handler per command; `run()` parses argv and calls the matched command's handler. Try:
#   python examples/dispatch.py commit --message="first commit"
#   python examples/dispatch.py add src tests
if __name__ == "__main__":
    app.run()
