import dataclasses
import enum
import itertools
import pathlib
import sys
import types
from typing import Annotated, Literal, Union, get_args, get_origin

from assertpy2 import assert_that
from hypothesis import given, settings
from hypothesis import strategies as st
from typing_extensions import NotRequired, Required, TypedDict

from docopt2 import DocoptExit, DocoptLanguageError, check, docopt
from docopt2._stub import _key_shapes
from docopt2._typed import _typeddict_optional_keys

_REFUSED = ("refused",)


def _outcome(doc, argv, annotation):
    """What binding ``argv`` to one field ``v`` of ``annotation`` comes to: the value, a refusal of the value, a
    refusal of the schema, or the name of whatever else was raised."""
    schema = dataclasses.make_dataclass("Schema", [("v", annotation)])
    try:
        return ("bound", docopt(doc, argv, schema=schema, complete=False, help=False).v)
    except DocoptLanguageError:
        return ("schema",)
    except DocoptExit:
        return _REFUSED
    except Exception as leaked:
        return ("leaked", type(leaked).__name__)


def _same(one, other):
    """Equal and of one type: ``True`` is no ``1`` here."""
    return type(one) is type(other) and one == other


# members of a closed set: texts, small numbers and both bools, which equal 0 and 1 and must not be taken for them
_MEMBERS = st.one_of(st.booleans(), st.integers(-2, 3), st.sampled_from(["a", "b", "True", "False", "1", "0", "x-y"]))
_SETS = st.lists(_MEMBERS, min_size=1, max_size=5).map(
    lambda values: [value for at, value in enumerate(values) if not any(_same(value, seen) for seen in values[:at])]
)
_TEXTS = st.one_of(
    st.sampled_from(["a", "b", "True", "False", "true", "1", "0", "01", "2", "-1", "x-y", "nope", ""]),
    st.text(max_size=3),
)


def _spells(text, member):
    """Whether ``text`` is a way to write ``member``, as this file understands a closed set and not as the binder
    computes it: a text is itself, a bool is its name as Python or a config file writes it, an int is any numeral
    of its value."""
    if isinstance(member, bool):
        return text in (str(member), str(member).lower())
    if isinstance(member, str):
        return text == member
    try:
        return int(text) == member
    except ValueError:
        return False


def _expected(text, members):
    """The member ``text`` selects: the text that is a member itself, else the first member it spells."""
    exact = [member for member in members if isinstance(member, str) and member == text]
    takers = exact or [member for member in members if _spells(text, member)]
    return ("bound", takers[0]) if takers else _REFUSED


@given(members=_SETS, text=_TEXTS)
def test_a_closed_set_takes_a_text_exactly_where_the_text_spells_one_of_its_members(members, text):
    got = _outcome("Usage: p [--] <v>", ["--", text], Literal[tuple(members)])
    want = _expected(text, members)
    assert_that(got[0]).is_equal_to(want[0])
    if want != _REFUSED:
        assert_that(_same(got[1], want[1])).described_as(f"{got[1]!r} for {want[1]!r}").is_true()


@given(members=_SETS)
def test_every_member_of_a_closed_set_is_reached_by_its_own_spelling(members):
    for member in members:
        got = _outcome("Usage: p [--] <v>", ["--", str(member)], Literal[tuple(members)])
        # the spelling of a member may be a text of the set too, and the text itself comes first
        wanted = str(member) if str(member) in [other for other in members if isinstance(other, str)] else member
        assert_that(got[0]).is_equal_to("bound")
        assert_that(_same(got[1], wanted)).described_as(f"{got[1]!r} for {wanted!r}").is_true()


@given(members=_SETS, text=_TEXTS)
def test_an_enum_takes_a_text_exactly_where_the_text_spells_the_value_of_a_member(members, text):
    # an Enum folds equal values into one member, so the values are told apart by `==` here: `1` and `True` are one
    distinct = [value for at, value in enumerate(members) if value not in members[:at]]
    kind = enum.Enum("Kind", {f"M{at}": value for at, value in enumerate(distinct)})
    got = _outcome("Usage: p [--] <v>", ["--", text], kind)
    want = _expected(text, distinct)
    assert_that(got).is_equal_to(want if want == _REFUSED else ("bound", kind(want[1])))


_PLAIN = st.sampled_from([int, float, str, pathlib.Path, Literal["a", "b"], Literal[1, 2], Literal[True, False]])
_WRAPPED = st.sampled_from(
    [
        lambda kind: kind | None,
        lambda kind: Annotated[kind, "why"],
        lambda kind: Annotated[kind | None, "why"],
        lambda kind: Annotated[kind, "why"] | None,
        lambda kind: Annotated[Annotated[kind, "one"], "two"],
    ]
)


@given(kind=_PLAIN, wrap=_WRAPPED, text=_TEXTS)
def test_none_and_annotated_around_a_type_change_nothing_of_what_a_text_binds_to(kind, wrap, text):
    plain = _outcome("Usage: p [--] <v>", ["--", text], kind)
    # compared as written: the float of `nan` is a float that equals nothing, itself included
    assert_that(repr(_outcome("Usage: p [--] <v>", ["--", text], wrap(kind)))).is_equal_to(repr(plain))
    # and a repeated element binds each text as the one alone binds
    listed = _outcome("Usage: p [--] <v>...", ["--", text, text], list[wrap(kind)])
    assert_that(repr(listed)).is_equal_to(repr(plain if plain[0] != "bound" else ("bound", [plain[1], plain[1]])))


_MARKS = st.sampled_from(
    [
        lambda kind: kind,
        lambda kind: Required[kind],
        lambda kind: NotRequired[kind],
        lambda kind: Annotated[kind, "why"],
        lambda kind: Annotated[Required[kind], "why"],
        lambda kind: Annotated[NotRequired[kind], "why"],
        lambda kind: Required[Annotated[kind, "why"]],
        lambda kind: NotRequired[Annotated[kind, "why"]],
        lambda kind: Annotated[Annotated[NotRequired[kind], "one"], "two"],
    ]
)


def _typed_dict(name, bases, total, annotations):
    return types.new_class(name, bases, {"total": total}, lambda space: space.update({"__annotations__": annotations}))


@given(st.booleans(), st.booleans(), _MARKS, _MARKS, st.sampled_from([[], ["1"], ["1", "2"]]))
def test_a_typed_dict_leaves_out_exactly_the_keys_python_calls_optional(base_total, child_total, mark_a, mark_b, argv):
    base = _typed_dict("Base", (TypedDict,), base_total, {"a": mark_a(int)})
    child = _typed_dict("Child", (base,), child_total, {"b": mark_b(int)})
    optional = set(child.__optional_keys__)
    assert_that(_typeddict_optional_keys(child)).is_equal_to(optional)
    given_keys = dict(zip("ab", argv, strict=False))
    try:
        bound = docopt("Usage: p [<a>] [<b>]", argv, schema=child, complete=False, help=False)
    except DocoptLanguageError as refused:
        bound = str(refused).partition(" may be absent")[0]
    missing = [key for key in "ab" if key not in given_keys and key not in optional]
    want = f"usage element '<{missing[0]}>'" if missing else {key: int(text) for key, text in given_keys.items()}
    assert_that(bound).is_equal_to(want)


def _is(value, annotation):
    """Whether ``value`` is what ``annotation`` promises, read here and not by the binder. A bool is no int."""
    if hasattr(annotation, "__metadata__"):
        return _is(value, get_args(annotation)[0])
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (types.UnionType, Union):
        return any(_is(value, member) for member in args)
    if origin is Literal:
        return any(_same(value, literal) for literal in args)
    if origin is list:
        return isinstance(value, list) and all(_is(item, args[0]) for item in value)
    return isinstance(value, annotation) and (type(value) is bool) == (annotation is bool)


_ELEMENTS = st.sampled_from(
    [
        ("Usage: p <v>", [["x"], ["1"], ["True"]]),
        ("Usage: p [<v>]", [[], ["x"], ["2"]]),
        ("Usage: p <v>...", [["x"], ["1", "2"]]),
        ("Usage: p [--v=<n>]", [[], ["--v=1"], ["--v=a"]]),
        ("Usage: p [-v]", [[], ["-v"]]),
        ("Usage: p [-v]...", [[], ["-v"], ["-vv"]]),
        ("Usage: p (v | w)", [["v"], ["w"]]),
    ]
)


class _Word(enum.Enum):
    A = "a"
    B = "b"


class _Rank(enum.IntEnum):
    LOW = 1
    HIGH = 2


class _Switch(enum.Enum):
    ON = True
    OFF = False


class _Bits(enum.Flag):
    R = 1
    W = 2


class _Composite(enum.Flag):
    AB = 3
    BC = 6


_ENUM_TYPES = [_Word, _Rank, _Switch, _Bits, _Composite, _Word | _Rank, _Bits | Literal["x"]]
if sys.version_info >= (3, 11):  # a Flag has a boundary from 3.11

    class _Ejecting(enum.Flag, boundary=enum.EJECT):
        A = 2

    _ENUM_TYPES.append(_Ejecting)
_ENUMS = st.sampled_from(_ENUM_TYPES)
_ANY_TYPE = st.one_of(
    _PLAIN, _ENUMS, st.sampled_from([bool, list[int], list[str], list, object, pathlib.PurePath, dict, complex])
)
_SHAPED = st.one_of(
    _ANY_TYPE, st.tuples(_ANY_TYPE, _WRAPPED).map(lambda pair: pair[1](pair[0])), _ANY_TYPE.map(lambda k: list[k])
)


@given(element=_ELEMENTS, annotation=_SHAPED)
def test_a_schema_binds_a_value_of_its_type_or_raises_one_of_its_two_errors_and_the_check_foretells_the_schema_s(
    element, annotation
):
    doc, argvs = element
    outcomes = [_outcome(doc, argv, annotation) for argv in argvs]
    assert_that([outcome for outcome in outcomes if outcome[0] == "leaked"]).is_empty()
    for outcome in outcomes:
        if outcome[0] == "bound":
            assert_that(_is(outcome[1], annotation)).described_as(f"{outcome[1]!r} as {annotation}").is_true()
    schema = dataclasses.make_dataclass("Schema", [("v", annotation)])
    foretold = any(found.level == "error" for found in check(doc, schema=schema))
    broken = [outcome for outcome in outcomes if outcome[0] == "schema"]
    # silence of the check is its promise that no argv breaks on the schema, and an error that one does: the
    # schema is refused for it, or the element takes no text and every value it yields is refused
    if not foretold:
        assert_that(broken).is_empty()
    else:
        never_bound = "<" not in doc and all(outcome == _REFUSED for outcome in outcomes)
        assert_that(bool(broken) or never_bound).described_as(f"an error of {doc!r} as {annotation}").is_true()


_ATOMS = st.sampled_from(["a", "b", "<x>", "<y>", "-f", "--o=<v>"])
_USAGES = st.recursive(
    _ATOMS,
    lambda inner: st.one_of(
        st.tuples(inner, inner).map(" ".join),
        inner.map("[{}]".format),
        st.tuples(inner, inner).map(lambda pair: f"({pair[0]} | {pair[1]})"),
        inner.map("({})...".format),
    ),
    max_leaves=3,
)
_ARGVS = [list(argv) for size in range(4) for argv in itertools.product(["a", "b", "z", "-f", "--o=1"], repeat=size)]


@settings(
    max_examples=60
)  # 10 ms an example, 156 argv parsed for each: the 300 of the profile would cost the suite 3 s
@given(_USAGES)
def test_an_element_the_usage_is_said_to_always_require_is_given_by_every_argv_the_usage_accepts(usage):
    doc = f"Usage: p {usage}"
    required = [key for key, (_yielded, always, _span) in _key_shapes(doc).items() if always]
    for argv in _ARGVS:
        try:
            parsed = docopt(doc, argv, complete=False, help=False)
        except DocoptExit:
            continue
        absent = [key for key in required if parsed[key] in (None, False, 0, [])]
        assert_that(absent).described_as(f"{doc!r} with {argv}").is_empty()
