"""Deploy a service.

Usage:
  typed <host> <port> [--workers=<n>] [--verbose]

Options:
  --workers=<n>  Worker processes [default: 4].
  --verbose      Enable verbose logging.
"""

import dataclasses

from docopt2 import docopt


@dataclasses.dataclass
class Args:
    host: str
    port: int  # coerced from the parsed string
    workers: int  # coerced too; the [default: 4] applies when omitted
    verbose: bool


# Pass a schema and get a typed result back, statically narrowed by your type checker. Try:
#   python examples/typed.py localhost 8080 --verbose
if __name__ == "__main__":
    args = docopt(__doc__, schema=Args)
    print(f"host={args.host!r} port={args.port!r} workers={args.workers} verbose={args.verbose}")
    print(f"(args.port is a real {type(args.port).__name__}, not a string)")
