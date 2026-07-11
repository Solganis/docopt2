from assertpy2 import assert_that

from docopt2 import Source, docopt

_DOC = (
    "Usage: prog [--port=<n>] [--host=<h>] [--tag=<t>] [<file>]\n\nOptions:\n"
    "  --port=<n>  Port [default: 80] [env: APP_PORT] [config: server.port].\n"
    "  --host=<h>  Host [config: server.host].\n"
    "  --tag=<t>   Tag [default: latest]."
)
_CFG = {"server": {"port": 8080, "host": "db.local"}}


def test_source_reports_cli_for_a_value_given_on_argv(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    result = docopt(_DOC, "--port=99", complete=False, config=_CFG)
    assert_that(result.source("--port")).is_equal_to(Source.CLI)


def test_source_reports_env_when_the_variable_supplies_it(monkeypatch):
    monkeypatch.setenv("APP_PORT", "7000")
    result = docopt(_DOC, "", complete=False, config=_CFG)
    assert_that(result.source("--port")).is_equal_to(Source.ENV)


def test_source_reports_config_when_only_the_file_supplies_it(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    result = docopt(_DOC, "", complete=False, config=_CFG)
    assert_that(result.source("--port")).is_equal_to(Source.CONFIG)  # env unset, config has server.port
    assert_that(result.source("--host")).is_equal_to(Source.CONFIG)  # dotted server.host


def test_source_reports_default_when_nothing_overrides_it(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    result = docopt(_DOC, "", complete=False)  # no config
    assert_that(result.source("--port")).is_equal_to(Source.DEFAULT)
    assert_that(result.source("--tag")).is_equal_to(Source.DEFAULT)


def test_source_reflects_the_full_precedence_chain_at_once(monkeypatch):
    monkeypatch.setenv("APP_PORT", "7000")
    result = docopt(_DOC, "--tag=rc", complete=False, config=_CFG)
    assert_that(result.source("--tag")).is_equal_to(Source.CLI)  # given on argv
    assert_that(result.source("--port")).is_equal_to(Source.ENV)  # env beats config and default
    assert_that(result.source("--host")).is_equal_to(Source.CONFIG)  # only config supplies it


def test_source_of_a_provided_positional_is_cli():
    result = docopt(_DOC, "notes.txt", complete=False)
    assert_that(result.source("<file>")).is_equal_to(Source.CLI)


def test_source_of_an_unknown_name_defaults():
    result = docopt(_DOC, "", complete=False)
    assert_that(result.source("--nonexistent")).is_equal_to(Source.DEFAULT)


def test_source_enum_values_read_as_their_layer_names():
    assert_that([member.value for member in Source]).is_equal_to(["cli", "env", "config", "default"])
