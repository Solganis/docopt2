"""A CLI with shell completion.

Usage:
  completion serve <host> [--port=<n>]
  completion build <target>
  completion --completion=<shell>

Options:
  --port=<n>            Port to bind [default: 8000].
  --completion=<shell>  Print a completion script for bash, zsh, fish or powershell.
"""

import sys

from docopt2 import docopt, generate_completion

# The generated script is a thin callback: at each Tab it re-invokes THIS program, and docopt() answers with
# the candidates its own usage allows. So the program has to CALL docopt - printing the script is not enough,
# and a program that only prints it hands the shell no completions at all. Try:
#
#   python examples/completion.py --completion=bash > _completion.bash && source _completion.bash
#   completion <TAB>        -> build  serve
#   completion serve <TAB>  -> --port
if __name__ == "__main__":
    arguments = docopt(__doc__)  # answers the completion protocol first, when a shell is the one asking
    shell = arguments["--completion"]
    if shell is not None:
        print(generate_completion(__doc__, prog="completion", shell=shell))
        sys.exit(0)
    print(arguments)
