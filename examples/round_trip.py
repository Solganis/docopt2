"""Deploy a service.

Usage:
  deploy <service> [--replicas=<n>] [--force]

Options:
  --replicas=<n>  How many replicas [default: 1].
"""

from docopt2 import docopt, format_argv

# format_argv is the inverse of docopt: it rebuilds a canonical argv from a parsed result, verified by a
# re-parse, so docopt(format_argv(args)) == args. Handy for reproducible-run logging, "copy as command",
# or building a subprocess argv from validated values. It emits every element that carries a value - what you
# supplied, plus whatever [env:] or [config:] resolved, so the argv stands on its own - in long form. Try:
#   python examples/round_trip.py web --replicas=3 --force
#   python examples/round_trip.py web                    # --replicas left at its default is not re-emitted
if __name__ == "__main__":
    args = docopt(__doc__)
    print("parsed :", dict(args))
    print("rebuilt:", "deploy " + " ".join(format_argv(args, __doc__)))
