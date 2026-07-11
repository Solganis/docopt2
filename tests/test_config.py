import dataclasses

from assertpy2 import assert_that

from docopt2 import Cli, Dispatch, docopt
from docopt2._parser import parse_defaults

_DOC = (
    "Usage: prog [--port=<n>] [--host=<h>] [--verbose]\n\nOptions:\n"
    "  --port=<n>  Port [default: 80] [env: APP_PORT] [config: server.port].\n"
    "  --host=<h>  Host [config: server.host].\n"
    "  --verbose   Loud [config: flags.verbose]."
)
_CFG = {"server": {"port": 8080, "host": "db.local"}, "flags": {"verbose": True}}


def test_cli_argument_wins_over_config(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    assert_that(docopt(_DOC, "--port=99", complete=False, config=_CFG)["--port"]).is_equal_to("99")


def test_env_wins_over_config(monkeypatch):
    monkeypatch.setenv("APP_PORT", "7000")
    assert_that(docopt(_DOC, "", complete=False, config=_CFG)["--port"]).is_equal_to("7000")


def test_config_fills_when_no_cli_or_env(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    result = docopt(_DOC, "", complete=False, config=_CFG)
    assert_that(result["--port"]).is_equal_to("8080")  # server.port
    assert_that(result["--host"]).is_equal_to("db.local")  # dotted server.host
    assert_that(result["--verbose"]).is_true()  # flag truthy from config


def test_default_applies_when_config_lacks_the_key(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    assert_that(docopt(_DOC, "", complete=False, config={"server": {}})["--port"]).is_equal_to("80")


def test_config_none_leaves_the_annotation_inert(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    result = docopt(_DOC, "", complete=False)  # no config passed
    assert_that(result["--port"]).is_equal_to("80")  # default
    assert_that(result["--host"]).is_none()  # nothing supplies it


def test_a_non_mapping_intermediate_key_falls_through(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    # server is a scalar, so `server.port` cannot resolve - fall back to the default, never crash.
    assert_that(docopt(_DOC, "", complete=False, config={"server": "not-a-mapping"})["--port"]).is_equal_to("80")


def test_an_empty_env_falls_through_to_config(monkeypatch):
    # A blank env var is treated as unset (the shell ${VAR:-default} convention), so config still applies.
    monkeypatch.setenv("APP_PORT", "")
    assert_that(docopt(_DOC, "", complete=False, config=_CFG)["--port"]).is_equal_to("8080")


def test_an_empty_config_value_falls_through_to_the_default(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    assert_that(docopt(_DOC, "", complete=False, config={"server": {"port": ""}})["--port"]).is_equal_to("80")


def test_config_value_coerces_through_the_schema(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)

    @dataclasses.dataclass
    class Args:
        port: int
        host: str | None
        verbose: bool

    args = docopt(_DOC, "", complete=False, config=_CFG, schema=Args)
    assert_that(args.port).is_equal_to(8080)
    assert_that(type(args.port)).is_equal_to(int)
    assert_that(args.verbose).is_true()


def test_dispatch_forwards_config():
    app = Dispatch("Usage: prog run [--port=<n>]\n\nOptions:\n  --port=<n>  Port [config: server.port].")

    @app.on("run")
    def _run(args):
        return args["--port"]

    assert_that(app.run("run", config=_CFG)).is_equal_to("8080")


def test_cli_parse_forwards_config():
    class Server(Cli):
        __cli_doc__ = "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [config: server.port]."
        port: int

    assert_that(Server.parse("", complete=False, config=_CFG).port).is_equal_to(8080)


def test_config_annotation_parses_without_breaking_default_extraction():
    option = next(o for o in parse_defaults(_DOC) if o.long == "--port")
    assert_that(option.value).is_equal_to("80")  # greedy [default: (.*)] must not swallow [env:]/[config:]
    assert_that(option.env).is_equal_to("APP_PORT")
    assert_that(option.config_key).is_equal_to("server.port")
