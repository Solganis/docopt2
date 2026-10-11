import dataclasses
from dataclasses import InitVar
from typing import Annotated, ClassVar

from assertpy2 import assert_that

from docopt2 import DocoptLanguageError, docopt

_USAGE = "Usage: prog <host> <port> [--scale=<n>] [--retries=<n>]"


@dataclasses.dataclass
class _Server:
    host: str
    port: InitVar[int]
    scale: InitVar[int | None] = None
    retries: InitVar[int] = 3
    address: str = dataclasses.field(init=False)

    def __post_init__(self, port, scale, retries):
        self.address = f"{self.host}:{port + 1} scale={scale!r} retries={retries + 1}"


@dataclasses.dataclass
class _Annotated:
    port: InitVar[Annotated[int, "a port"]]
    doubled: int = dataclasses.field(init=False)

    def __post_init__(self, port):
        self.doubled = port * 2


@dataclasses.dataclass
class _Required:
    host: str
    scale: InitVar[int]


@dataclasses.dataclass
class _NotInInit:
    host: str
    kind: ClassVar[str] = "server"
    port: InitVar[int] = dataclasses.field(init=False, default=80)


def test_only_what_the_constructor_takes_is_bound():
    # an init-only field the constructor does not take, and a class variable: neither needs a usage element
    assert_that(_stored("Usage: prog <host>", ["h"], _NotInInit)).is_equal_to({"host": "h"})
    assert_that(_stored("Usage: prog <host> <port> <kind>", ["h", "81", "x"], _NotInInit)).is_equal_to({"host": "h"})
    assert_that(_NotInInit.kind).is_equal_to("server")


def _bound(doc, argv, schema):
    try:
        return docopt(doc, argv, schema=schema, complete=False)
    except SystemExit as refusal:
        return [line for line in str(refusal).splitlines() if line.startswith(("error:", "   = note:"))]
    except (TypeError, DocoptLanguageError) as raised:
        return f"{type(raised).__name__}: {raised}"


def _stored(doc, argv, schema):
    """The stored fields of the instance bound, or the account of why none was bound."""
    bound = _bound(doc, argv, schema)
    return dataclasses.asdict(bound) if dataclasses.is_dataclass(bound) else bound


def test_an_init_only_field_is_bound_coerced_and_handed_to_post_init_and_is_not_stored():
    assert_that(_stored(_USAGE, ["h", "80"], _Server)).is_equal_to(
        {"host": "h", "address": "h:81 scale=None retries=4"}
    )
    assert_that(_stored(_USAGE, ["h", "80", "--scale=2", "--retries=5"], _Server)).is_equal_to(
        {"host": "h", "address": "h:81 scale=2 retries=6"}
    )


def test_a_bad_value_for_an_init_only_field_is_refused_by_its_inner_type():
    assert_that(_bound(_USAGE, ["h", "eighty"], _Server)).is_equal_to(
        ["error: invalid value for `<port>`", "   = note: `eighty` is not a valid int"]
    )


def test_an_init_only_field_takes_an_annotated_inner_type():
    assert_that(_stored("Usage: prog <port>", ["21"], _Annotated)).is_equal_to({"doubled": 42})


def test_an_init_only_field_with_no_default_and_no_none_cannot_bind_an_element_that_may_be_absent():
    said = _bound("Usage: prog <host> [--scale=<n>]", ["h"], _Required)
    assert_that(said).is_equal_to(
        "DocoptLanguageError: usage element '--scale' may be absent but field 'scale' is not optional; "
        "annotate it as `scale: ... | None` or give it a default"
    )


def test_an_init_only_field_needs_its_usage_element_like_any_other():
    assert_that(_bound("Usage: prog <host>", ["h"], _Required)).is_equal_to(
        "DocoptLanguageError: schema field 'scale' has no matching usage element"
    )
