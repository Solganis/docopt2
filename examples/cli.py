"""Back up a directory.

Usage:
  cli <source> <dest> [--compress] [--keep=<n>]

Options:
  --compress  Compress the archive.
  --keep=<n>  How many old backups to keep [default: 5].
"""

from docopt2 import Cli


class Backup(Cli):
    __cli_doc__ = __doc__
    source: str
    dest: str
    compress: bool
    keep: int  # coerced from the parsed string


# The class-first form: subclass Cli, put the usage in __cli_doc__, declare the fields, and call
# .parse() - you get a typed Backup instance, no separate docopt() call. Try:
#   python examples/cli.py ./data ./backups --compress --keep=10
if __name__ == "__main__":
    args = Backup.parse()
    print(f"backing up {args.source!r} -> {args.dest!r} (compress={args.compress}, keep={args.keep})")
    print(f"(args.keep is a real {type(args.keep).__name__})")
