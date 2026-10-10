import dataclasses
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
import typing_extensions
from assertpy2 import assert_that

from docopt2 import DocoptLanguageError, docopt
from docopt2 import _typed as typed


def test_the_scalar_table_reaches_only_the_homes_that_are_imported():
    assert_that(typed._homed_coercers(frozenset())).is_empty()
    assert_that(list(typed._homed_coercers(frozenset({"pathlib", "uuid"})))).is_equal_to([Path, UUID])
    whole = typed._scalar_coercers()
    assert_that(list(whole)).is_equal_to([int, float, Path, Decimal, UUID, datetime, date, time])
    try:
        parsed = whole[date]("2026-10-10")  # by the classmethod: called with a text, the class itself refuses
    except TypeError as refused:
        parsed = refused
    assert_that(parsed).is_equal_to(date(2026, 10, 10))


def test_the_markers_of_typing_extensions_are_added_only_where_it_is_imported():
    own_required, own_optional = typed._markers(False)
    with_required, with_optional = typed._markers(True)
    assert_that(with_required[len(own_required) :]).is_equal_to((typing_extensions.Required,))
    assert_that(with_optional[len(own_optional) :]).is_equal_to((typing_extensions.NotRequired,))
    # `typing` has the pair from 3.11 and neither on the floor
    assert_that(len(own_required)).is_equal_to(1 if sys.version_info >= (3, 11) else 0)
    assert_that(len(own_optional)).is_equal_to(len(own_required))


def test_a_scalar_home_blocked_in_sys_modules_is_not_reached(monkeypatch):
    # `sys.modules[name] = None` is how an import is blocked, and a None there is not a module to read a class off
    monkeypatch.setitem(sys.modules, "uuid", None)
    reached = typed._coercers_in_reach()
    assert_that(reached).does_not_contain_key(UUID)
    assert_that(reached).contains_key(Path, Decimal, date)


@dataclasses.dataclass
class EveryScalar:
    count: int
    ratio: float
    path: Path
    amount: Decimal
    ident: UUID
    at: datetime
    day: date
    hour: time


def test_every_scalar_of_the_table_is_coerced_from_its_text():
    doc = "Usage: prog <count> <ratio> <path> <amount> <ident> <at> <day> <hour>"
    argv = [
        "3",
        "1.5",
        "x/y",
        "2.50",
        "12345678-1234-5678-1234-567812345678",
        "2026-10-10T08:30:00",
        "2026-10-10",
        "08:30",
    ]
    try:
        bound = docopt(doc, argv, schema=EveryScalar)
    except DocoptLanguageError as refusal:
        bound = refusal
    assert_that(bound).is_equal_to(
        EveryScalar(
            count=3,
            ratio=1.5,
            path=Path("x/y"),
            amount=Decimal("2.50"),
            ident=UUID("12345678-1234-5678-1234-567812345678"),
            at=datetime(2026, 10, 10, 8, 30),
            day=date(2026, 10, 10),
            hour=time(8, 30),
        )
    )


@pytest.mark.parametrize("home", ["uuid", "datetime", "pathlib", "decimal"])
def test_a_scalar_class_is_still_coerced_after_its_home_left_sys_modules(monkeypatch, home):
    # a class outlives its entry there, and `date` is the same class when it comes from `_datetime`
    typed._scalar_coercers()
    # with its submodules: from 3.13 `pathlib` is a package, and one left half in place cannot be imported again
    for name in [name for name in sys.modules if name == home or name.startswith(f"{home}.")]:
        monkeypatch.delitem(sys.modules, name)
    doc = "Usage: prog <count> <ratio> <path> <amount> <ident> <at> <day> <hour>"
    argv = [
        "3",
        "1.5",
        "x",
        "2.50",
        "12345678-1234-5678-1234-567812345678",
        "2026-10-10T08:30:00",
        "2026-10-10",
        "08:30",
    ]
    try:
        bound = docopt(doc, argv, schema=EveryScalar)
    except DocoptLanguageError as refusal:
        bound = refusal
    assert_that(bound).is_instance_of(EveryScalar)
    assert_that(bound.ident).is_equal_to(UUID("12345678-1234-5678-1234-567812345678"))
    assert_that(bound.day).is_equal_to(date(2026, 10, 10))
