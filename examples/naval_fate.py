"""Naval Fate.

Usage:
  naval_fate ship new <name>...
  naval_fate ship <name> move <x> <y> [--speed=<kn>]
  naval_fate ship shoot <x> <y>
  naval_fate mine (set|remove) <x> <y> [--moored | --drifting]
  naval_fate -h | --help
  naval_fate --version

Options:
  -h --help     Show this screen.
  --version     Show the version.
  --speed=<kn>  Speed in knots [default: 10].
  --moored      Moored (anchored) mine.
  --drifting    Drifting mine.
"""

from docopt2 import docopt

# The classic docopt example, verbatim in spirit: the usage message above is the whole parser.
# `from docopt2 import docopt` is the only change a docopt user makes. Try:
#   python examples/naval_fate.py ship new Titanic Bismarck
#   python examples/naval_fate.py ship Titanic move 1 2 --speed=15
if __name__ == "__main__":
    arguments = docopt(__doc__, version="Naval Fate 2.0")
    print(arguments)
