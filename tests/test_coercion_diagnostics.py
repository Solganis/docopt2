import dataclasses
import sys

from assertpy2 import assert_that
from pytest import raises

from docopt2 import Dispatch, DocoptExit, DocoptLanguageError, docopt
from docopt2._typed import _CoercionError, bind_schema


@dataclasses.dataclass
class _Port:
    port: int


@dataclasses.dataclass
class _Level:
    level: int


_DOC = "Usage: prog --port=<n>\n\nOptions:\n  --port=<n>  Port [default: 80]."


def _caret_aligns_under(message: str, source_substring: str, token: str) -> bool:
    """True if the caret line under the snippet line containing ``source_substring`` underlines ``token``."""
    lines = message.splitlines()
    source = next(line for line in lines if source_substring in line)
    caret = lines[lines.index(source) + 1]
    at = source.index(token)
    return caret[at : at + len(token)] == "^" * len(token)


def test_bad_cli_value_renders_a_two_span_diagnostic():
    # value found in argv AND the option has a usage span -> both carets, each aligned under its token.
    with raises(DocoptExit) as info:
        docopt(_DOC, "--port=abc", complete=False, schema=_Port)
    message = str(info.value)
    assert_that(message).contains("invalid value for `--port`")
    assert_that(message).contains("in the arguments:").contains("expected int")
    assert_that(message).contains("in the usage:").contains("typed as int")
    assert_that(message).contains("`abc` is not a valid int")
    assert_that(_caret_aligns_under(message, "--port=abc", "abc")).is_true()  # argv caret under the value
    assert_that(_caret_aligns_under(message, "Usage: prog", "--port=<n>")).is_true()  # usage caret under element


def test_bad_env_value_carets_the_usage_but_not_the_argv(monkeypatch):
    # value came from env (not argv) but the option is written in the usage -> usage caret only.
    monkeypatch.setenv("APP_PORT", "abc")
    doc = "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [env: APP_PORT]."
    with raises(DocoptExit) as info:
        docopt(doc, "", complete=False, schema=_Port)
    message = str(info.value)
    assert_that(message).contains("invalid value for `--port`").contains("in the usage:")
    assert_that(message).does_not_contain("in the arguments:")


def test_bad_default_via_options_shortcut_has_no_carets():
    # value from a default AND the option only lives in [options] (no usage span) -> summary + help only.
    doc = "Usage: prog [options]\n\nOptions:\n  --level=<n>  Level [default: high]."
    with raises(DocoptExit) as info:
        docopt(doc, "", complete=False, schema=_Level)
    message = str(info.value)
    assert_that(message).contains("invalid value for `--level`").contains("is not a valid int")
    assert_that(message).does_not_contain("in the arguments:").does_not_contain("in the usage:")


def test_bad_cli_value_via_options_shortcut_carets_the_argv_only():
    # value found in argv but the option only lives in [options] (no usage span) -> argv caret only.
    doc = "Usage: prog [options]\n\nOptions:\n  --level=<n>  Level."
    with raises(DocoptExit) as info:
        docopt(doc, "--level=nope", complete=False, schema=_Level)
    message = str(info.value)
    assert_that(message).contains("in the arguments:")
    assert_that(message).does_not_contain("in the usage:")


def test_dispatch_coercion_error_is_rendered_with_an_explicit_argv():
    app = Dispatch("Usage: prog set --port=<n>\n\nOptions:\n  --port=<n>  Port.")

    @app.on("set", schema=_Port)
    def _set(args):
        return args

    with raises(DocoptExit) as info:
        app.run("set --port=notint")
    assert_that(str(info.value)).contains("invalid value for `--port`").contains("in the arguments:")


def test_dispatch_coercion_error_falls_back_to_sys_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "set", "--port=notint"])
    app = Dispatch("Usage: prog set --port=<n>\n\nOptions:\n  --port=<n>  Port.")

    @app.on("set", schema=_Port)
    def _set(args):
        return args

    with raises(DocoptExit) as info:
        app.run()  # argv=None -> the diagnostic reconstructs it from sys.argv[1:]
    assert_that(str(info.value)).contains("invalid value for `--port`")


def test_bind_schema_raises_a_structured_coercion_error():
    with raises(_CoercionError) as info:
        bind_schema({"--port": "abc"}, _Port)
    err = info.value
    assert_that(err.key).is_equal_to("--port")
    assert_that(err.raw).is_equal_to("abc")
    assert_that(err.expected).is_equal_to("int")
    assert_that(str(err)).contains("invalid value for --port").contains("expected int")


def test_list_coercion_failure_names_the_parameterized_type():
    # A generic keeps its argument in the message: `list[int]`, not a bare `list`.
    @dataclasses.dataclass
    class Nums:
        nums: list[int]

    with raises(DocoptExit) as info:
        docopt("Usage: prog <nums>...", "1 2 x", complete=False, schema=Nums)
    assert_that(str(info.value)).contains("invalid value for `<nums>`").contains("is not a valid list[int]")


def test_structural_schema_error_stays_a_language_error():
    # A schema/usage disagreement is the developer's bug, not the user's input: no two-span argv caret.
    @dataclasses.dataclass
    class _Mismatch:
        nonexistent: int

    with raises(DocoptLanguageError) as info:
        docopt(_DOC, "--port=80", complete=False, schema=_Mismatch)
    assert_that(str(info.value)).contains("no matching usage element")
