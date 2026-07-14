from __future__ import annotations

import dataclasses
import enum
import inspect
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Annotated, ClassVar
from uuid import UUID

from assertpy2 import assert_that
from pytest import raises

from docopt2 import Cli, DocoptExit, DocoptLanguageError, docopt
from docopt2 import _core as core

if sys.version_info >= (3, 11):
    from typing import NotRequired, Required, TypedDict
else:
    from typing_extensions import NotRequired, Required, TypedDict


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


@dataclasses.dataclass
class Conn:
    host: str
    port: int
    ratio: float
    verbose: bool
    out: Path
    color: Color
    note: str | None
    tags: list[str]


CONN_DOC = "Usage: prog <host> <port> <ratio> [--verbose] --out=<out> --color=<color> [--note=<note>] <tags>..."


def test_dataclass_full_coercion_with_absent_optional():
    result = docopt(CONN_DOC, "h 80 1.5 --verbose --out /tmp --color red a b", schema=Conn)
    assert_that(result.host).is_equal_to("h")
    assert_that(result.port).is_equal_to(80)
    assert_that(result.ratio).is_equal_to(1.5)
    assert_that(result.verbose).is_true()
    assert_that(result.out).is_equal_to(Path("/tmp"))
    assert_that(result.color).is_equal_to(Color.RED)
    assert_that(result.note).is_none()
    assert_that(result.tags).is_equal_to(["a", "b"])


def test_optional_present_coerces_union_inner():
    result = docopt(CONN_DOC, "h 80 1.5 --out /tmp --color blue --note hey a", schema=Conn)
    assert_that(result.note).is_equal_to("hey")
    assert_that(result.verbose).is_false()
    assert_that(result.color).is_equal_to(Color.BLUE)


@dataclasses.dataclass
class Names:
    foo_bar: bool
    x: bool
    input_file: str
    name: str
    run: bool


def test_name_mapping_covers_every_key_shape():
    doc = "Usage: prog [--foo-bar] [-x] <input file> NAME run"
    result = docopt(doc, "--foo-bar -x file.txt VAL run", schema=Names)
    assert_that(result.foo_bar).is_true()
    assert_that(result.x).is_true()
    assert_that(result.input_file).is_equal_to("file.txt")
    assert_that(result.name).is_equal_to("VAL")
    assert_that(result.run).is_true()


@dataclasses.dataclass
class Nums:
    values: list[int]


def test_list_inner_coercion():
    result = docopt("Usage: prog <values>...", "1 2 3", schema=Nums)
    assert_that(result.values).is_equal_to([1, 2, 3])


@dataclasses.dataclass
class BareList:
    values: list


def test_bare_list_defaults_to_str_elements():
    result = docopt("Usage: prog <values>...", "1 2", schema=BareList)
    assert_that(result.values).is_equal_to(["1", "2"])


@dataclasses.dataclass
class AnnotatedFields:
    port: Annotated[int, "the port number"]


def test_annotated_field_coerced_to_inner_type():
    assert_that(docopt("Usage: prog <port>", "80", schema=AnnotatedFields).port).is_equal_to(80)


@dataclasses.dataclass
class ListForScalar:
    x: list[str]


def test_non_repeating_element_into_list_field_raises_language_error():
    # Symmetric to test_repeated_element_into_scalar_field: a list-typed field needs a repeating
    # element; a scalar must raise, not silently char-split the string into single characters.
    doc = "Usage: prog <x>"
    assert_that(docopt).raises(DocoptLanguageError).when_called_with(doc, "hello", schema=ListForScalar)


@dataclasses.dataclass
class NestedAnnotated:
    port: Annotated[int, "meta"] | None
    vals: list[Annotated[int, "meta"]]


def test_annotated_nested_in_union_and_list_coerces_to_inner_type():
    # Annotated must be unwrapped even when nested inside a Union member or a list element type,
    # not only at the top level - a common pattern in typed codebases.
    result = docopt("Usage: prog [--port=<p>] <vals>...", "--port 80 1 2", schema=NestedAnnotated)
    assert_that(result.port).is_equal_to(80)
    assert_that(result.vals).is_equal_to([1, 2])


@dataclasses.dataclass
class ScalarForRepeated:
    x: str


def test_repeated_element_into_scalar_field_raises_language_error():
    doc = "usage: prog <x>..."
    assert_that(docopt).raises(DocoptLanguageError).when_called_with(doc, "a b", schema=ScalarForRepeated)


@dataclasses.dataclass
class BoolFromArg:
    flag: bool


def test_bool_field_from_option_argument_raises_language_error():
    doc = "usage: prog --flag=<v>"
    assert_that(docopt).raises(DocoptLanguageError).when_called_with(doc, "--flag false", schema=BoolFromArg)


@dataclasses.dataclass
class RichTypes:
    amount: Decimal
    ident: UUID
    when: datetime
    day: date
    at: time


def test_decimal_uuid_date_datetime_time_coercion():
    result = docopt(
        "usage: prog <amount> <ident> <when> <day> <at>",
        "3.14 12345678-1234-5678-1234-567812345678 2024-01-15T10:30 2024-01-15 10:30:00",
        schema=RichTypes,
    )
    assert_that(result.amount).is_equal_to(Decimal("3.14"))
    assert_that(result.ident).is_equal_to(UUID("12345678-1234-5678-1234-567812345678"))
    assert_that(result.when).is_equal_to(datetime(2024, 1, 15, 10, 30))
    assert_that(result.day).is_equal_to(date(2024, 1, 15))
    assert_that(result.at).is_equal_to(time(10, 30))


@dataclasses.dataclass
class DecimalField:
    amount: Decimal


def test_bad_decimal_raises_docopt_exit():
    doc = "usage: prog <amount>"
    assert_that(docopt).raises(DocoptExit).when_called_with(doc, "notanumber", schema=DecimalField)


@dataclasses.dataclass
class Count:
    v: int


def test_int_field_from_repeated_flag_count():
    result = docopt("Usage: prog [-v -v]", "-v -v", schema=Count)
    assert_that(result.v).is_equal_to(2)


@dataclasses.dataclass
class OnlyHost:
    host: str


def test_extra_usage_keys_are_ignored():
    result = docopt("Usage: prog [--verbose] <host>", "--verbose h", schema=OnlyHost)
    assert_that(result.host).is_equal_to("h")


@dataclasses.dataclass
class Missing:
    host: str
    ghost: str


def test_schema_field_without_usage_element_raises_language_error():
    assert_that(docopt).raises(DocoptLanguageError).when_called_with("Usage: prog <host>", "h", schema=Missing)


@dataclasses.dataclass
class Portish:
    port: str


def test_colliding_usage_elements_raise_language_error():
    doc = "Usage: prog port <port>"
    assert_that(docopt).raises(DocoptLanguageError).when_called_with(doc, "port 5", schema=Portish)


@dataclasses.dataclass
class Weird:
    host: dict


def test_unsupported_annotation_raises_language_error():
    assert_that(docopt).raises(DocoptLanguageError).when_called_with("Usage: prog <host>", "h", schema=Weird)


@dataclasses.dataclass
class IntPort:
    port: int


def test_bad_user_value_raises_docopt_exit():
    assert_that(docopt).raises(DocoptExit).when_called_with("Usage: prog <port>", "notanumber", schema=IntPort)


class HostPort(TypedDict):
    host: str
    port: int


def test_typeddict_schema_returns_dict():
    result = docopt("Usage: prog <host> <port>", "h 80", schema=HostPort)
    assert_that(result).is_equal_to({"host": "h", "port": 80})


class PartialTD(TypedDict, total=False):
    host: str
    note: str


class MixedTD(TypedDict):
    host: str
    note: NotRequired[str]


class StrictTD(TypedDict):
    host: str
    note: str


def test_typeddict_total_false_omits_absent_optional():
    assert_that(docopt("Usage: prog <host> [<note>]", "h", schema=PartialTD)).is_equal_to({"host": "h"})


def test_typeddict_notrequired_key_omitted_when_absent_kept_when_present():
    assert_that(docopt("Usage: prog <host> [<note>]", "h", schema=MixedTD)).is_equal_to({"host": "h"})
    assert_that(docopt("Usage: prog <host> [<note>]", "h N", schema=MixedTD)).is_equal_to({"host": "h", "note": "N"})


def test_typeddict_required_key_absent_raises_language_error():
    doc = "Usage: prog <host> [<note>]"
    assert_that(docopt).raises(DocoptLanguageError).when_called_with(doc, "h", schema=StrictTD)


class RequiredInPartialTD(TypedDict, total=False):
    host: Required[str]
    note: str


def test_typeddict_required_wrapper_in_total_false():
    # host is Required despite total=False; note stays optional and is omitted when absent.
    result = docopt("Usage: prog <host> [<note>]", "h", schema=RequiredInPartialTD)
    assert_that(result).is_equal_to({"host": "h"})


class Server(Cli):
    __cli_doc__ = "Usage: prog <host> <port>"
    host: str
    port: int


def test_cli_base_class_parses_and_types():
    result = Server.parse("h 80")
    assert_that(result).is_instance_of(Server)
    assert_that(result.host).is_equal_to("h")
    assert_that(result.port).is_equal_to(80)


class HelpDefaultCli(Cli):
    __cli_doc__ = "usage: prog [-h]\n\noptions:\n  -h  Show help."
    h: bool


def test_cli_parse_defaults_help_on_and_forwards_it():
    # Cli.parse mirrors docopt's help=True default and must pass it through: "-h" exits
    # via the help branch instead of binding a result.
    with raises(SystemExit):
        HelpDefaultCli.parse(["-h"])


def test_a_dataclass_field_with_a_default_factory_may_be_absent():
    # `default_factory` is the one thing a dataclass carries that a plain class does not: it leaves NO
    # class attribute behind, so the plain-class fallback ("does the class have this name?") cannot see
    # it and would refuse the absent element. Nothing tested it - which meant `_is_dataclass` could have
    # answered False for every schema and the whole dataclass path would have gone unexercised.
    @dataclasses.dataclass
    class WithFactory:
        host: str
        tag: str = dataclasses.field(default_factory=lambda: "none")

    absent = docopt("Usage: prog <host> [<tag>]", "h", schema=WithFactory)
    assert_that(absent.host).is_equal_to("h")
    assert_that(absent.tag).is_equal_to("none")  # the factory supplied it; the usage did not
    given = docopt("Usage: prog <host> [<tag>]", "h t", schema=WithFactory)
    assert_that(given.tag).is_equal_to("t")


def test_cli_parse_defaults_are_the_same_as_docopts():
    # Cli.parse restates docopt()'s keywords, so its defaults are a second copy that can drift from
    # the first. Read them off both signatures rather than writing the values down a third time.
    docopt_defaults = inspect.signature(docopt).parameters
    for name, parameter in inspect.signature(Cli.parse).parameters.items():
        if name in ("cls", "argv"):
            continue
        assert_that(parameter.default).described_as(name).is_equal_to(docopt_defaults[name].default)


def test_cli_parse_forwards_every_option_to_docopt(monkeypatch):
    # Cli.parse is a pure forwarder, and nothing checked that each keyword actually arrives: dropping
    # `suggest=suggest` from the call left every test passing while the caller's argument vanished.
    seen: dict[str, object] = {}

    def spy(doc, argv=None, *positional, **keywords):
        seen.update(keywords, doc=doc, argv=argv, positional=positional)
        return Server(host="h", port=1)

    monkeypatch.setattr(core, "docopt", spy)
    Server.parse(
        ["h", "80"],
        help=False,
        version="2.0",
        options_first=True,
        suggest=True,
        negative_numbers=True,
        allow_abbrev=False,
        allow_extra=True,
        exit_code=7,
        complete=False,
        config={"a": 1},
        help_style="rich",
    )
    assert_that(seen).is_equal_to(
        {
            "doc": Server.__cli_doc__,
            "argv": ["h", "80"],
            "positional": (False, "2.0", True),  # help, version and options_first go by position
            "suggest": True,
            "negative_numbers": True,
            "allow_abbrev": False,
            "allow_extra": True,
            "exit_code": 7,
            "complete": False,
            "schema": Server,
            "config": {"a": 1},
            "help_style": "rich",
        }
    )


class WithClassVarConst(Cli):
    __cli_doc__ = "usage: prog <host>"
    host: str
    LIMIT: ClassVar[int] = 100


def test_cli_public_classvar_is_a_constant_not_a_bound_field():
    # A non-underscore ClassVar is a class constant, not a CLI field: it must be excluded
    # from binding, or it would be demanded as a missing usage element.
    result = WithClassVarConst.parse("h")
    assert_that(result.host).is_equal_to("h")
    assert_that(result.LIMIT).is_equal_to(100)


@dataclasses.dataclass
class WithDefault:
    name: str = "fallback"


def test_dataclass_default_used_when_optional_element_absent():
    assert_that(docopt("Usage: prog [<name>]", "", schema=WithDefault).name).is_equal_to("fallback")
    assert_that(docopt("Usage: prog [<name>]", "x", schema=WithDefault).name).is_equal_to("x")


@dataclasses.dataclass
class RequiredName:
    name: str


def test_absent_optional_on_required_field_raises_language_error():
    doc = "Usage: prog [<name>]"
    assert_that(docopt).raises(DocoptLanguageError).when_called_with(doc, "", schema=RequiredName)


class ServerWithDefault(Cli):
    __cli_doc__ = "Usage: prog [<host>]"
    host: str = "localhost"


def test_cli_class_attribute_default_used_when_optional_absent():
    assert_that(ServerWithDefault.parse("").host).is_equal_to("localhost")


class FakeField:
    def __init__(self, alias: str | None = None) -> None:
        self.alias = alias


class FakeModel:
    """Duck-typed pydantic stand-in: proves the reflective path without importing pydantic."""

    # "port" carries an alias to exercise the alias branch; "host" has none.
    model_fields: ClassVar[dict[str, FakeField]] = {"host": FakeField(), "port": FakeField(alias="port")}

    def __init__(self, host: str, port: str) -> None:
        self.host = host
        self.port = port

    @classmethod
    def model_validate(cls, data: dict[str, object]) -> FakeModel:
        return cls(**data)


def test_pydantic_style_model_validate_is_delegated():
    result = docopt("Usage: prog <host> <port>", "h 80", schema=FakeModel)
    assert_that(result.host).is_equal_to("h")
    # Delegated to model_validate; docopt2's own coercion is not applied, so port stays a str.
    assert_that(result.port).is_equal_to("80")


def test_no_schema_returns_plain_mapping():
    with raises(DocoptExit):
        docopt("Usage: prog <host>", "a b")
    assert_that(docopt("Usage: prog <host>", "a")).is_equal_to({"<host>": "a"})
