import sys

from assertpy2 import assert_that
from pytest import importorskip

from docopt2 import DocoptLanguageError, generate_config_template
from docopt2._generate import _toml_value

# tomllib is stdlib from 3.11; on the 3.10 floor the dev group installs tomli, so the round-trip
# below is verified on every supported version instead of quietly skipping on the oldest one.
_TOML = "tomllib" if sys.version_info >= (3, 11) else "tomli"

_DOC = (
    "Usage: p [--port=<n>] [--host=<h>] [--verbose] [--token=<t>]\n\nOptions:\n"
    "  --port=<n>   Port [default: 8080] [env: PORT] [config: server.port].\n"
    "  --host=<h>   Host [default: 0.0.0.0] [config: server.host].\n"
    "  --verbose    Loud [config: verbose].\n"
    "  --token=<t>  Token [env: TOKEN] [config: server.token].\n"
    "  --plain      No config key here.\n"
)


def test_config_template_emits_root_first_tables_defaults_and_comments():
    out = generate_config_template(_DOC)
    assert_that(out).contains("[server]")  # a named table from the dotted config keys
    assert_that(out).contains("port = 8080").contains("# --port, env PORT")  # int default + flag/env comment
    assert_that(out).contains('host = "0.0.0.0"')  # string default, quoted
    assert_that(out).contains('token = ""')  # no default -> empty placeholder
    assert_that(out.index("verbose = false")).is_less_than(out.index("[server]"))  # root key before any table
    assert_that(out).does_not_contain("plain")  # an option without [config:] is not in the file


def test_config_template_with_only_nested_keys_has_no_root_block():
    out = generate_config_template("Usage: p [--port=<n>]\n\nOptions:\n  --port=<n>  Port [config: server.port].")
    assert_that(out).starts_with("[server]")


def test_config_template_is_valid_round_trippable_toml():
    tomllib = importorskip(_TOML)
    parsed = tomllib.loads(generate_config_template(_DOC))
    assert_that(parsed).is_equal_to(
        {"verbose": False, "server": {"port": 8080, "host": "0.0.0.0", "token": ""}}
    )  # port coerces to int, host to str, verbose to bool - ready to feed back as config=


def test_config_template_is_empty_without_config_keys():
    assert_that(generate_config_template("Usage: prog <x>")).is_empty()


def test_config_template_raises_on_a_malformed_options_line():
    # an options line run together with its description (no double space) fails loudly, as in the other tools
    doc = "Usage: prog\n\nOptions:\n  --opt arg1 arg2 desc"
    assert_that(generate_config_template).raises(DocoptLanguageError).when_called_with(doc)


def test_config_template_rejects_a_value_and_table_collision():
    # `srv` (a value) and `srv.port` (under table [srv]) cannot coexist in one TOML file - fail loudly.
    doc = "Usage: p [--x=<v>] [--y=<v>]\n\nOptions:\n  --x=<v>  X [config: srv].\n  --y=<v>  Y [config: srv.port]."
    assert_that(generate_config_template).raises(DocoptLanguageError).when_called_with(doc)


def test_config_template_rejects_a_duplicate_config_key():
    doc = "Usage: p [--x=<v>] [--y=<v>]\n\nOptions:\n  --x=<v>  X [config: srv.port].\n  --y=<v>  Y [config: srv.port]."
    assert_that(generate_config_template).raises(DocoptLanguageError).when_called_with(doc)


def test_config_template_allows_sibling_keys_under_one_table():
    doc = "Usage: p [--x=<v>] [--y=<v>]\n\nOptions:\n  --x=<v>  X [config: srv.host].\n  --y=<v>  Y [config: srv.port]."
    assert_that(generate_config_template(doc)).contains("[srv]").contains("host = ").contains("port = ")


def test_toml_value_renders_each_scalar_kind():
    assert_that(_toml_value(None)).is_equal_to('""')
    assert_that(_toml_value(True)).is_equal_to("true")
    assert_that(_toml_value(False)).is_equal_to("false")
    assert_that(_toml_value("8080")).is_equal_to("8080")  # int
    assert_that(_toml_value("-3")).is_equal_to("-3")
    assert_that(_toml_value("1.5")).is_equal_to("1.5")  # float
    assert_that(_toml_value("true")).is_equal_to("true")  # bool-looking default
    assert_that(_toml_value("info")).is_equal_to('"info"')  # plain string, quoted
    assert_that(_toml_value('a"b\\c')).is_equal_to('"a\\"b\\\\c"')  # quotes and backslashes escaped
    assert_that(_toml_value("007")).is_equal_to('"007"')  # leading zeros are not a valid TOML int -> string
    assert_that(_toml_value("00")).is_equal_to('"00"')
    assert_that(_toml_value("-0")).is_equal_to("-0")  # a lone signed zero is a valid TOML int
