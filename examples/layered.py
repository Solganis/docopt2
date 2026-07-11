"""Serve an app, configured in layers.

Usage:
  layered [--host=<h>] [--port=<n>] [--log=<lvl>]

Options:
  --host=<h>   Bind address [default: 127.0.0.1] [config: server.host].
  --port=<n>   Port to bind [default: 8000] [env: APP_PORT] [config: server.port].
  --log=<lvl>  Log level [default: info] [env: APP_LOG].
"""

from docopt2 import docopt

# A config mapping you loaded however you like (TOML, JSON, a [tool.<prog>] table). docopt2 never reads
# files itself - you pass the mapping, and [config: dotted.key] walks the dotted path into it.
CONFIG = {"server": {"host": "0.0.0.0", "port": 8080}}

# Each option resolves in layers: command line > [env: VAR] > [config: key] > [default: ...].
# args.source(name) reports which layer actually won, so you can log or branch on provenance. Try:
#   python examples/layered.py                       # host/port from CONFIG, log from its default
#   APP_PORT=9000 python examples/layered.py         # the environment overrides the config port
#   python examples/layered.py --host=example.com    # the command line overrides everything
# and scaffold a starter config file for these keys with:
#   docopt2 config-template examples/layered.py
if __name__ == "__main__":
    args = docopt(__doc__, config=CONFIG)
    for name in ("--host", "--port", "--log"):
        print(f"{name:6} = {args[name]!r:16} (from {args.source(name).value})")
