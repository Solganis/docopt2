import dataclasses
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from hypothesis import given
from hypothesis import strategies as st

from docopt2._typed import bind_schema

_FINITE_DEC = st.decimals(allow_nan=False, allow_infinity=False)


@dataclasses.dataclass
class IntField:
    value: int


@dataclasses.dataclass
class FloatField:
    value: float


@dataclasses.dataclass
class DecField:
    value: Decimal


@dataclasses.dataclass
class DateField:
    value: date


@dataclasses.dataclass
class DateTimeField:
    value: datetime


@dataclasses.dataclass
class OptDate:
    value: date | None


@dataclasses.dataclass
class AnnInt:
    value: Annotated[int, "meta"]


@dataclasses.dataclass
class ListDec:
    values: list[Decimal]


@dataclasses.dataclass
class UuidField:
    value: UUID


@given(number=st.integers())
def test_int_roundtrip(number):
    assert bind_schema({"<value>": str(number)}, IntField).value == number


@given(number=st.floats(allow_nan=False, allow_infinity=False))
def test_float_roundtrip(number):
    assert bind_schema({"<value>": repr(number)}, FloatField).value == number


@given(amount=_FINITE_DEC)
def test_decimal_roundtrip(amount):
    assert bind_schema({"<value>": str(amount)}, DecField).value == amount


@given(day=st.dates())
def test_date_isoformat_roundtrip(day):
    assert bind_schema({"<value>": day.isoformat()}, DateField).value == day


@given(moment=st.datetimes())
def test_datetime_isoformat_roundtrip(moment):
    assert bind_schema({"<value>": moment.isoformat()}, DateTimeField).value == moment


@given(day=st.one_of(st.none(), st.dates()))
def test_optional_date(day):
    raw = None if day is None else day.isoformat()
    assert bind_schema({"<value>": raw}, OptDate).value == day


@given(number=st.integers())
def test_annotated_int(number):
    assert bind_schema({"<value>": str(number)}, AnnInt).value == number


@given(amounts=st.lists(_FINITE_DEC, max_size=5))
def test_list_decimal(amounts):
    assert bind_schema({"<values>": [str(amount) for amount in amounts]}, ListDec).values == amounts


@given(identifier=st.builds(uuid4))
def test_uuid_roundtrip(identifier):
    assert bind_schema({"<value>": str(identifier)}, UuidField).value == identifier
