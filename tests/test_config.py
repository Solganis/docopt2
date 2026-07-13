import dataclasses
import datetime
import decimal
import sys
import uuid

import pytest
from assertpy2 import assert_that
from pytest import importorskip

from docopt2 import Cli, Dispatch, DocoptExit, docopt
from docopt2._parser import parse_defaults

# tomllib is stdlib from 3.11; on the 3.10 floor the dev group installs tomli. The value set below is only
# sound if it matches what a real loader emits, so this asserts against the loader rather than a hand list.
tomllib = importorskip("tomllib" if sys.version_info >= (3, 11) else "tomli")

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


_UNDER = "Usage: prog [--x=<v>]\n\nOptions:\n  --x=<v>  X [config: a.b]."


@pytest.mark.parametrize(
    ("held", "kind"),
    [
        ({"c": 1, "d": 2}, "dict"),  # the key stops one level short of the value
        ({}, "dict"),  # a declared but empty table is still not a value
        ([1, 2], "list"),
        ({1, 2}, "set"),
        (b"raw", "bytes"),
        (object(), "object"),  # not a container, and str() is a memory address: a blacklist would miss it
    ],
)
def test_a_config_key_holding_something_that_is_not_a_value_fails_loudly(held, kind):
    # str() would hand the option a repr - `{'c': 1}`, `[1, 2]`, `<object object at 0x...>` - and the
    # program would run on garbage. The one thing this must never do is succeed quietly.
    with pytest.raises(DocoptExit) as raised:
        docopt(_UNDER, "", complete=False, config={"a": {"b": held}})
    rendered = str(raised.value)
    assert_that(rendered).contains("invalid config value for `--x`")
    assert_that(rendered).contains(f"`a.b` has type `{kind}` in the config")
    assert_that(rendered).contains("^^^")  # the usage element that declared the annotation is carets


def test_the_failure_fires_without_a_schema():
    # The precedent it mirrors (a value the schema cannot coerce) only fires when there IS a schema. A
    # schema-less call never coerces, so nothing downstream would catch this - it has to fail in the resolver.
    with pytest.raises(DocoptExit):
        docopt(_UNDER, "", complete=False, config={"a": {"b": {"c": 1}}})  # no schema= at all


def test_the_failure_names_the_leaf_keys_that_would_work():
    with pytest.raises(DocoptExit) as raised:
        docopt(_UNDER, "", complete=False, config={"a": {"b": {"c": 1, "d": 2}}})
    assert_that(str(raised.value)).contains("point the annotation at a single value: `a.b.c`, `a.b.d`")


def test_the_failure_degrades_to_a_caretless_diagnostic_behind_the_options_shortcut():
    # Reached only via `[options]`, the option has no span in the usage line, so there is nothing to caret.
    doc = "Usage: prog [options]\n\nOptions:\n  --x=<v>  X [config: a.b]."
    with pytest.raises(DocoptExit) as raised:
        docopt(doc, "", complete=False, config={"a": {"b": [1]}})
    rendered = str(raised.value)
    assert_that(rendered).contains("`a.b` has type `list` in the config")
    assert_that(rendered).does_not_contain("^^^")  # no span, so the snippet is dropped rather than misplaced


@pytest.mark.parametrize(
    ("held", "expected"),
    [
        (8080, "8080"),
        ("host", "host"),
        (False, "False"),
        # tomllib yields date, datetime and time natively. `time` is the sharp one: no schema annotation
        # names it, so a value set copied from the coercible types would reject a legitimate TOML value.
        (datetime.date(2020, 1, 1), "2020-01-01"),
        (datetime.datetime(2020, 1, 1, 10, 0), "2020-01-01 10:00:00"),
        (datetime.time(10, 30), "10:30:00"),
        (decimal.Decimal("1.5"), "1.5"),
        (uuid.UUID("12345678-1234-5678-1234-567812345678"), "12345678-1234-5678-1234-567812345678"),
    ],
)
def test_a_config_value_still_reaches_the_option(held, expected):
    assert_that(docopt(_UNDER, "", complete=False, config={"a": {"b": held}})["--x"]).is_equal_to(expected)


def test_every_type_tomllib_can_produce_is_either_a_value_or_a_loud_failure():
    # The value set is only sound if it lines up with what a real config loader emits. Enumerate them.
    loaded = tomllib.loads(
        's = "x"\ni = 1\nf = 1.5\nb = true\nd = 2020-01-01\ndt = 2020-01-01T10:00:00\nt = 10:30:00\n'
        "arr = [1]\n\n[tbl]\nk = 1\n"
    )
    values, failures = [], []
    for key in loaded:
        doc = f"Usage: prog [--x=<v>]\n\nOptions:\n  --x=<v>  X [config: {key}]."
        try:
            docopt(doc, "", complete=False, config=loaded)
        except DocoptExit:
            failures.append(key)
        else:
            values.append(key)
    assert_that(values).is_equal_to(["s", "i", "f", "b", "d", "dt", "t"])  # every scalar TOML has
    assert_that(failures).is_equal_to(["arr", "tbl"])  # and only its two containers fail


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
