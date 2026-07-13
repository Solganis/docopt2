from __future__ import annotations

import dataclasses
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from docopt2 import docopt

_DOC = "Usage: prog [--x=<v>]\n\nOptions:\n  --x=<v>  X [config: a.b]."

# A config value is normalized with str() before anything else sees it, so the whole design rests on one
# claim: for every type the config layer accepts, str() is reversible. Enumerating the types (as the unit
# tests do) only shows the claim holds for the values someone thought to write down. This fuzzes the
# values themselves - a Decimal with an exponent, a datetime at year 1, a time with microseconds - and
# fails if any of them cannot be read back. A property asserting that non-values are rejected would
# instead just restate the whitelist, and would pass even if the whitelist were wrong.
_REVERSIBLE = [
    (st.text(min_size=1), str),
    (st.integers(), int),
    (st.floats(allow_nan=False), float),  # NaN is excluded because NaN != NaN, not because str() loses it
    (st.decimals(allow_nan=False), Decimal),
    (st.dates(), date),
    (st.datetimes(), datetime),
    (st.times(), time),
    (st.uuids(), UUID),
    (st.builds(Path, st.text(alphabet="abcXYZ019._-", min_size=1)), Path),
]


@pytest.mark.parametrize(("strategy", "annotation"), _REVERSIBLE, ids=[t.__name__ for _, t in _REVERSIBLE])
@given(data=st.data())
def test_a_config_value_survives_the_round_trip_through_str(strategy, annotation, data):
    value = data.draw(strategy)
    schema = dataclasses.make_dataclass("Args", [("x", annotation)])
    assert docopt(_DOC, "", complete=False, config={"a": {"b": value}}, schema=schema).x == value
