"""Serve a directory over HTTP.

Usage:
  rich_help [--port=<n>] [--host=<h>] [--log=<lvl>] <root>

Options:
  --port=<n>   Port to bind [default: 8080] [env: PORT] [config: server.port].
  --host=<h>   Interface to bind [default: 127.0.0.1] [env: HOST].
  --log=<lvl>  Log verbosity [default: info] [config: logging.level].
  -h --help    Show this help and exit.
"""

from docopt2 import docopt

# Opt into a rich --help: an aligned, colored screen that also documents where each value resolves
# from - the [env, config, default] chain, straight from the usage text (and it scopes to the
# subcommand the user typed). The default help_style="raw" prints the usage verbatim instead. Try:
#   python examples/rich_help.py --help    # rich, colored, with the per-option source chain
#   python examples/rich_help.py ./public  # a normal run
if __name__ == "__main__":
    args = docopt(__doc__, help_style="rich")
    print(args)
