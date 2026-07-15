# CodSpeed regression gate: micro-benchmarks of docopt2's own hot paths, measured commit-over-commit under
# CPU simulation. Distinct from bench.py, which compares docopt2 against argparse/click/docopt-ng for the
# docs. Run manually with `uv run --group benchmark pytest benchmarks/ --codspeed --no-cov`; the CodSpeed
# CI job runs the same. Not collected by the default suite (testpaths=tests), so it never gates on the
# machine's noise - only CodSpeed's simulated instruction count does.
from __future__ import annotations

import dataclasses

from docopt2 import complete, docopt

# A git/naval-shaped CLI: subcommands, a variadic, a default, and two mutex groups.
NAVAL = """Usage:
  naval ship new <name>...
  naval ship <name> move <x> <y> [--speed=<kn>]
  naval mine (set | remove) <x> <y> [--moored | --drifting]
  naval --help

Options:
  --speed=<kn>  Speed in knots [default: 10].
  --moored      Moored (anchored) mine.
  --drifting    Drifting mine.
"""

# Eight optionals on one line: exercises the _combine search that the match budget bounds - a guard against
# a regression in the matcher's cost.
MANY_OPTIONALS = "usage: prog [-a] [-b] [-c] [-d] [-e] [-f] [-g] [-h] <src> <dst>"

TYPED_DOC = "Usage: app <host> <port> [--verbose] [--retries=<n>]"


@dataclasses.dataclass
class Config:
    host: str
    port: int
    verbose: bool
    retries: int


def test_single_shot_parse_and_match(benchmark):
    # The realistic per-invocation cost: parse the usage and match one argv (docopt2 reparses every call).
    benchmark(lambda: docopt(NAVAL, ["ship", "Titanic", "move", "1", "2", "--speed=20"], help=False))


def test_match_many_optionals(benchmark):
    benchmark(lambda: docopt(MANY_OPTIONALS, ["-a", "-c", "-e", "in.txt", "out.txt"], help=False))


def test_typed_binding_and_coercion(benchmark):
    benchmark(lambda: docopt(TYPED_DOC, ["localhost", "8080", "--verbose", "--retries=3"], schema=Config, help=False))


def test_completion_latency(benchmark):
    benchmark(lambda: complete(NAVAL, ["ship"]))
