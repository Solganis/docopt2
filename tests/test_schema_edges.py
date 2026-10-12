import builtins
import dataclasses
import enum
import pathlib
import sys
from typing import Annotated, Generic, Literal, Protocol, TypeVar, get_type_hints

import pytest
from assertpy2 import assert_that
from typing_extensions import NotRequired, Required, TypedDict

from docopt2 import Dispatch, DocoptExit, DocoptLanguageError, check, complete, docopt, generate_stub
from docopt2._typed import _typeddict_optional_keys


def _bound(doc, argv, schema):
    """What binding ``argv`` to ``schema`` gives: the bound value, or the kind of refusal and its first line."""
    try:
        return docopt(doc, argv, schema=schema, complete=False, help=False)
    except DocoptLanguageError as refused:
        return "the schema is refused: " + str(refused).splitlines()[0]
    except DocoptExit as refused:
        return "the value is refused: " + str(refused).splitlines()[0]
    except Exception as leaked:
        return f"leaked {type(leaked).__name__}: {leaked}"


def _safely(call):
    """What ``call`` gives, or the name of what it raised: a leak is then a failed assertion and not an error."""
    try:
        return call()
    except Exception as leaked:
        return f"leaked {type(leaked).__name__}: {leaked}"


def _one(annotation, name="v"):
    return dataclasses.make_dataclass("Schema", [(name, annotation)])


def _value(doc, argv, annotation):
    bound = _bound(doc, argv, _one(annotation))
    return bound if isinstance(bound, str) else bound.v


class _Truth(enum.Enum):
    YES = True
    NO = False


class _Level(enum.IntEnum):
    LOW = 1
    HIGH = 2


class _Permission(enum.Flag):
    READ = 1
    WRITE = 2


_REFUSED = "the value is refused: error: invalid value for `<v>`"


@pytest.mark.parametrize(
    ("annotation", "text", "bound"),
    [
        (Literal[True], "True", True),
        (Literal[True], "nope", _REFUSED),
        (Literal[True], "False", _REFUSED),
        (Literal[True], "", _REFUSED),
        (Literal[False, True], "False", False),
        (Literal[False, True], "True", True),
        (Literal[False, True], "0", _REFUSED),
        (Literal[False, True], "false", False),
        (Literal[False, True], "true", True),
        (Literal[False, True], "TRUE", _REFUSED),
        (Literal[False, True], "yes", _REFUSED),
        (Literal[False], "False", False),
        (Literal[True, 2, "x"], "2", 2),
        (Literal[True, 2, "x"], "x", "x"),
        (Literal[True, 2, "x"], "1", _REFUSED),
        (_Truth, "True", _Truth.YES),
        (_Truth, "False", _Truth.NO),
        (_Truth, "nope", _REFUSED),
    ],
)
def test_a_bool_of_a_closed_set_is_taken_by_its_spelling_and_by_no_other_text(annotation, text, bound):
    # bool("False") is True, as is the bool of any other text: parsed, a bool choice took every text there is.
    # It is spelled as Python writes it or as a config file does, and a config hands a bool over as that text
    assert_that(_value("Usage: p <v>", [text], annotation)).is_equal_to(bound)


def test_a_flag_still_binds_to_a_bool_of_a_closed_set():
    assert_that(_value("Usage: p [-v]", ["-v"], Literal[True, False])).is_true()
    assert_that(_value("Usage: p [-v]", [], Literal[True, False])).is_false()


@pytest.mark.parametrize(
    ("text", "bound"),
    [
        ("1", _Permission.READ),
        ("3", _Permission.READ | _Permission.WRITE),
        ("4", _REFUSED),
        ("x", _REFUSED),
    ],
)
def test_a_flag_enum_takes_the_number_of_a_combination_as_the_enum_itself_takes_it(text, bound):
    assert_that(_value("Usage: p <v>", [text], _Permission)).is_equal_to(bound)


def test_an_int_enum_takes_the_number_of_a_member_and_no_other():
    assert_that(_value("Usage: p <v>", ["2"], _Level)).is_equal_to(_Level.HIGH)
    assert_that(_value("Usage: p <v>", ["3"], _Level)).is_equal_to(_REFUSED)


class _Loud(enum.Enum):
    A = "a"

    @classmethod
    def _missing_(cls, value):
        raise KeyError(value)


def test_an_enum_that_refuses_a_value_in_its_own_way_refuses_it_as_the_user_s():
    assert_that(_value("Usage: p <v>", ["a"], _Loud)).is_equal_to(_Loud.A)
    assert_that(_value("Usage: p <v>", ["zzz"], _Loud)).is_equal_to(_REFUSED)


class _Base(TypedDict):
    a: int


class _LooseChild(_Base, total=False):
    b: int


class _LooseBase(TypedDict, total=False):
    b: int


class _StrictChild(_LooseBase):
    a: int


class _Wrapped(TypedDict):
    a: int
    b: Annotated[NotRequired[int], "why"]


class _WrappedLoose(TypedDict, total=False):
    a: Annotated[Required[int], "why"]
    b: int


class _Twice(TypedDict):
    a: NotRequired[Annotated[int, "why"]]
    b: Annotated[Annotated[NotRequired[int], "one"], "two"]
    c: int


class _Written(TypedDict):
    a: "int"
    b: "Annotated[NotRequired[int], 'why']"


class _WrittenLoose(TypedDict, total=False):
    a: "Annotated[Required[int], 'why']"
    b: "int"


@pytest.mark.parametrize("schema", [_Written, _WrittenLoose])
def test_a_marker_written_as_a_string_inside_annotated_is_read_where_python_itself_misses_it(schema):
    assert_that(set(schema.__optional_keys__)).is_not_equal_to({"b"})
    assert_that(_typeddict_optional_keys(schema)).is_equal_to({"b"})
    assert_that(_bound("Usage: p <a> [<b>]", ["1"], schema)).is_equal_to({"a": 1})
    assert_that(_bound("Usage: p [<a>] [<b>]", [], schema)).starts_with("the schema is refused: usage element '<a>'")


@pytest.mark.parametrize("schema", [_Base, _LooseChild, _LooseBase, _StrictChild, _Wrapped, _WrappedLoose, _Twice])
def test_a_key_of_a_typed_dict_may_be_left_out_exactly_where_python_says_it_may(schema):
    assert_that(_typeddict_optional_keys(schema)).is_equal_to(set(schema.__optional_keys__))


@pytest.mark.parametrize(
    ("schema", "argv", "bound"),
    [
        # the totality of the class that declares a key decides, not that of the class the key is read from
        (_LooseChild, ["1"], {"a": 1}),
        (
            _LooseChild,
            [],
            "the schema is refused: usage element '<a>' may be absent but field 'a' is not optional",
        ),
        (_StrictChild, ["1"], {"a": 1}),
        (_StrictChild, ["1", "2"], {"a": 1, "b": 2}),
        (_Wrapped, ["1"], {"a": 1}),
        (_Wrapped, ["1", "2"], {"a": 1, "b": 2}),
        (_WrappedLoose, ["1"], {"a": 1}),
        (_Twice, [], "the schema is refused: schema field 'c' has no matching usage element"),
    ],
)
def test_a_typed_dict_binds_by_the_keys_it_requires(schema, argv, bound):
    said = _bound("Usage: p [<a>] [<b>]", argv, schema)
    assert_that(said if not isinstance(said, str) else said.partition(";")[0]).is_equal_to(bound)


@pytest.mark.parametrize(
    "doc",
    ["Usage: p a <x>\n       p b <x>", "Usage: p a <x> | b <x>", "Usage: p (a <x> | b <x>)", "Usage: p (a | b) <x>"],
)
def test_an_element_every_alternative_requires_is_always_given_however_the_alternatives_are_written(doc):
    schema = dataclasses.make_dataclass("Schema", [("a", bool), ("b", bool), ("x", str)])
    assert_that([found.summary for found in check(doc, schema=schema)]).is_empty()
    assert_that(generate_stub(doc)).contains("x: str\n").does_not_contain("x: str | None")
    assert_that(_bound(doc, ["a", "q"], schema)).is_equal_to(schema(a=True, b=False, x="q"))


@pytest.mark.parametrize(
    "doc", ["Usage: p (a <x> | b)", "Usage: p a <x> | b", "Usage: p [a <x> | b <x>]", "Usage: p (a [<x>] | b <x>)"]
)
def test_an_element_one_alternative_leaves_out_may_be_absent(doc):
    schema = dataclasses.make_dataclass("Schema", [("a", bool), ("b", bool), ("x", str)])
    assert_that([found.summary for found in check(doc, schema=schema)]).is_equal_to(
        ["usage element `<x>` may be absent, but field `x` is not optional"]
    )
    assert_that(generate_stub(doc)).contains("x: str | None")


@pytest.mark.parametrize(
    ("doc", "argv", "said"),
    [
        ("Usage: p [-v]", ["-v"], "the flag True"),
        ("Usage: p [-v]", [], "the flag False"),
        ("Usage: p [-v]...", ["-vv"], "the count 2"),
    ],
)
def test_a_flag_or_a_count_is_no_text_for_a_str_field(doc, argv, said):
    # it used to land in the field as it was: a bool or an int where the schema promises a str
    assert_that(_value(doc, argv, str)).is_equal_to(
        f"the schema is refused: a str field maps to a text, but the usage element yields {said}; use bool or int"
    )
    assert_that([found.summary for found in check(doc, schema=_one(str))]).is_equal_to(
        ["field `v` does not fit usage element `-v`"]
    )


def test_a_flag_and_a_count_still_bind_to_int_and_bool_and_float():
    assert_that([_value("Usage: p [-v]", ["-v"], kind) for kind in (bool, int, float)]).is_equal_to([True, 1, 1.0])
    assert_that([_value("Usage: p [-v]...", ["-vv"], kind) for kind in (int, float)]).is_equal_to([2, 2.0])


def _unresolved():
    @dataclasses.dataclass
    class Unresolved:
        v: "NoSuchName"  # noqa: F821 - the name is to stay unresolved

    return Unresolved


class _Shape(Protocol):
    v: int


_T = TypeVar("_T")


@dataclasses.dataclass
class _Box(Generic[_T]):
    v: _T


@pytest.mark.parametrize(
    ("schema", "said"),
    [
        (
            _unresolved(),
            "the annotations of schema `Unresolved` do not resolve: name 'NoSuchName' is not defined",
        ),
        (_Shape, "schema `_Shape` is a Protocol, which describes a class and cannot be one"),
        (_Box[int], "a schema is a class, and `_Box[int]` is a class with its type arguments given"),
        (int, "a schema is a class that declares fields, and `int` is a builtin"),
        (str, "a schema is a class that declares fields, and `str` is a builtin"),
        (dict, "a schema is a class that declares fields, and `dict` is a builtin"),
        (object, "a schema is a class that declares fields, and `object` is a builtin"),
        (_Box(v=1), "a schema is a class, and `_Box(v=1)` is not one"),
        ("_Box", "a schema is a class, and `'_Box'` is not one"),
        (len, "a schema is a class, and `<built-in function len>` is not one"),
    ],
)
def test_a_schema_that_cannot_be_one_is_refused_in_words_and_nothing_else_is_raised(schema, said):
    assert_that(_bound("Usage: p <v>", ["1"], schema)).is_equal_to(f"the schema is refused: {said}")
    # the linter says the same of it, and of annotations that do not resolve it keeps the name for its note
    assert_that([found.summary for found in check("Usage: p <v>", schema=schema)]).is_equal_to([said.partition(":")[0]])


def test_a_generic_dataclass_with_no_arguments_says_which_annotation_it_cannot_bind():
    assert_that(_bound("Usage: p <v>", ["1"], _Box)).starts_with(
        "the schema is refused: typed docopt cannot coerce to unsupported annotation"
    )


@pytest.mark.parametrize(
    ("annotation", "offered"),
    [
        (Literal["a"] | Literal["b"], ["a", "b"]),
        (Literal["a", "b"] | None, ["a", "b"]),
        (Literal["a"] | Literal["b"] | None, ["a", "b"]),
        (Literal["a"] | _Level, ["1", "2", "a"]),
        (Literal["a"] | Literal["a", "c"], ["a", "c"]),
        (list[Literal["a"] | Literal["b"]], ["a", "b"]),
        (Annotated[Literal["a"] | Literal["b"], "why"], ["a", "b"]),
    ],
)
def test_a_union_of_closed_sets_completes_the_values_of_each(annotation, offered):
    doc = "Usage: p <v>..." if annotation == list[Literal["a"] | Literal["b"]] else "Usage: p <v>"
    assert_that(complete(doc, [""], schema=_one(annotation))).is_equal_to(offered)


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (int | None, "int"),
        (int | str | None, "int | str"),
        (Annotated[int, "why"] | None, "int"),
        (pathlib.Path | None, "Path"),
        (list[int] | None, "int"),  # of a repeated element the one value refused is named, by its own type
    ],
)
def test_a_refusal_names_the_type_a_value_can_be_and_not_the_none_it_cannot(annotation, expected):
    doc = "Usage: p [<v>]..." if "list" in str(annotation) else "Usage: p [<v>]"
    try:
        docopt(doc, ["x"], schema=_one(annotation), complete=False, help=False)
        note = "bound"
    except DocoptExit as refused:
        note = next((line for line in str(refused).splitlines() if "expected" in line), str(refused))
    if annotation in (int | str | None, pathlib.Path | None):
        assert_that(note).is_equal_to("bound")  # a text is a str, and any text is a path
    else:
        assert_that(note.strip()).ends_with(f"expected {expected}")


def test_help_style_is_typed_as_the_two_styles_there_are():
    assert_that(get_type_hints(docopt)["help_style"]).is_equal_to(Literal["raw", "rich"])
    assert_that(docopt).raises(ValueError).when_called_with("Usage: p", [], help_style="plain")


def test_a_handler_registered_for_a_command_is_handed_back_as_it_is():
    app = Dispatch("Usage: p go <v>")

    def go(arguments):
        return arguments["<v>"]

    assert_that(app.on("go")(go)).is_same_as(go)
    assert_that(app.run(["go", "x"])).is_equal_to("x")


def test_a_bool_of_a_config_reaches_a_closed_set_of_bools_as_the_text_the_config_layer_writes():
    doc = "Usage: p [--v=<x>]\n\nOptions:\n  --v=<x>  Value [config: v].\n"
    schema = _one(Literal[True, False] | None)
    for config, bound in (({"v": True}, True), ({"v": False}, False), ({"v": "False"}, False)):
        assert_that(docopt(doc, [], schema=schema, config=config, complete=False).v).is_equal_to(bound)


def _mistyped(annotation):
    namespace = {"__annotations__": {"v": annotation}}
    return dataclasses.dataclass(type("Mistyped", (), namespace))


@pytest.mark.parametrize("annotation", ["int |", "NoSuchName", "list[NoSuchName]"])
def test_an_annotation_that_cannot_be_read_is_the_schema_s_fault_whatever_reading_it_raises(annotation):
    assert_that(_bound("Usage: p <v>", ["1"], _mistyped(annotation))).starts_with(
        "the schema is refused: the annotations of schema `Mistyped` do not resolve: "
    )


def test_a_union_of_closed_sets_is_named_as_the_one_set_it_is():
    try:
        docopt("Usage: p <v>", ["x"], schema=_one(Literal["a"] | Literal["b"] | _Level | None), complete=False)
        said = "bound"
    except DocoptExit as refused:
        said = str(refused)
    assert_that(said).contains("expected one of `a`, `b`, `1`, `2`").does_not_contain("None", " | ")


def test_a_flag_enum_is_named_as_the_combinations_it_takes_and_not_as_its_members_alone():
    try:
        docopt("Usage: p <v>", ["4"], schema=_one(_Permission), complete=False)
        said = "bound"
    except DocoptExit as refused:
        said = str(refused)
    assert_that(said).contains("expected a combination of `1`, `2`", "note: `4` is not a combination of `1`, `2`")


class _Wide(enum.Enum):
    ZERO = 0
    ROUND = float(2**53)
    EXACT = 2**53 + 1


@pytest.mark.parametrize(
    "wrap",
    [
        lambda kind: kind,
        lambda kind: kind | None,
        lambda kind: Annotated[kind, "why"],
        lambda kind: Annotated[kind, "why"] | Literal["x"],
    ],
)
def test_the_members_of_an_enum_are_tried_in_the_order_it_declares_them(wrap):
    # read as a float the text rounds to the second member, read as an int it is the third: the second comes first
    text = str(2**53 + 1)
    assert_that(_value("Usage: p <v>", [text], wrap(_Wide))).is_equal_to(_Wide.ROUND)
    assert_that(_value("Usage: p <v>...", [text, "0"], list[wrap(_Wide)])).is_equal_to([_Wide.ROUND, _Wide.ZERO])


class _Angry(enum.Enum):
    A = "a"

    @classmethod
    def _missing_(cls, value):
        raise RuntimeError(f"boom {value!r}")


def test_what_an_enum_of_the_author_raises_of_its_own_passes_through_binding_and_stops_neither_check_nor_tab():
    assert_that(_value("Usage: p <v>", ["a"], _Angry)).is_equal_to(_Angry.A)
    # no refusal of a value, so it is not turned into one: the author's exception is the author's to see
    assert_that(_value("Usage: p <v>", ["x"], _Angry)).is_equal_to("leaked RuntimeError: boom 'x'")
    assert_that(_safely(lambda: check("Usage: p <v>", schema=_one(_Angry)))).is_equal_to([])
    flagged = _safely(lambda: [found.summary for found in check("Usage: p [-v]", schema=_one(_Angry))])
    assert_that(flagged).is_equal_to(["field `v` does not fit usage element `-v`"])
    assert_that(_safely(lambda: complete("Usage: p <v> <w>", [""], schema=_one(_Angry)))).is_equal_to(["a"])
    assert_that(_safely(lambda: complete("Usage: p <v> <w>", ["x", ""], schema=_one(_Angry)))).is_equal_to([])


class _Composite(enum.Flag):
    AB = 3
    BC = 6


class _Nought(enum.Flag):
    NONE = 0


@pytest.mark.parametrize(
    ("kind", "text", "bound"),
    [
        (_Composite, "3", _Composite.AB),
        (_Composite, "7", _Composite.AB | _Composite.BC),
        (_Composite, "8", _REFUSED),
        (_Nought, "0", _Nought.NONE),
        (_Nought, "1", _REFUSED),
        (Annotated[_Composite, "why"] | None, "7", _Composite.AB | _Composite.BC),
    ],
)
def test_a_flag_enum_with_no_member_of_one_bit_takes_the_number_of_a_combination_too(kind, text, bound):
    # iterating such a Flag gives nothing: its members are read from `__members__`
    assert_that(_value("Usage: p <v>", [text], kind)).is_equal_to(bound)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="a Flag has a boundary from 3.11")
def test_what_an_enum_hands_back_that_is_no_member_of_it_is_not_bound():
    class Ejecting(enum.Flag, boundary=enum.EJECT):
        A = 2

    # `Ejecting(True)` is the bare `True`: the boundary hands a number it cannot place back as it came
    assert_that(Ejecting(True)).is_same_as(True)
    assert_that(_value("Usage: p [-v]", ["-v"], Ejecting)).is_equal_to(
        "the value is refused: error: invalid value for `-v`"
    )
    assert_that(_value("Usage: p <v>", ["1"], Ejecting)).is_equal_to(_REFUSED)
    assert_that(_value("Usage: p <v>", ["2"], Ejecting)).is_equal_to(Ejecting.A)


@pytest.mark.parametrize(
    ("annotation", "named"),
    [
        (_Composite, "a combination of `3`, `6`"),
        (_Permission | Literal["x"], "a combination of `1`, `2` | one of `x`"),
        (Annotated[_Permission, "why"] | Literal["x"] | None, "a combination of `1`, `2` | one of `x`"),
        (Literal["a"] | Annotated[_Level, "why"], "one of `a`, `1`, `2`"),
        (Literal["a"] | int, "one of `a` | int"),
    ],
)
def test_a_union_is_named_as_one_set_only_where_each_member_is_a_closed_set(annotation, named):
    # a Flag takes more than its members, so its values are not listed as all there is
    try:
        docopt("Usage: p <v>", ["?"], schema=_one(annotation), complete=False)
        said = "bound"
    except DocoptExit as refused:
        said = str(refused)
    assert_that(said.splitlines()).contains(f"   |    ^ expected {named}", f"   = note: `?` is not {named}")


def test_a_class_of_the_author_is_no_builtin_for_being_published_as_one(monkeypatch):
    @dataclasses.dataclass
    class Args:
        v: str

    monkeypatch.setattr(builtins, "Args", Args, raising=False)
    assert_that(_bound("Usage: p <v>", ["1"], Args)).is_equal_to(Args(v="1"))
    assert_that(check("Usage: p <v>", schema=Args)).is_empty()


def test_a_class_made_by_code_that_names_no_module_is_no_builtin_though_published_as_one(monkeypatch):
    made = {}
    exec("import dataclasses\n\n@dataclasses.dataclass\nclass Args:\n    v: int\n", made)
    assert_that(made["Args"].__module__).is_equal_to("builtins")
    assert_that(_bound("Usage: p <v>", ["1"], made["Args"])).is_equal_to(made["Args"](v=1))
    # its module says builtins and builtins holds it under its name: what tells it from `int` is how it was made
    monkeypatch.setattr(builtins, "Args", made["Args"], raising=False)
    assert_that(_bound("Usage: p <v>", ["1"], made["Args"])).is_equal_to(made["Args"](v=1))


class _Unhashable(enum.Enum):
    A = 1

    def __eq__(self, other):
        return self is other


def test_an_enum_whose_members_cannot_be_hashed_is_named_all_the_same():
    # a class that defines `__eq__` alone has no hash, and naming the members must not need one
    assert_that(_safely(lambda: hash(_Unhashable.A))).starts_with("leaked TypeError")
    assert_that(_safely(lambda: check("Usage: p [-v]", schema=_one(_Unhashable)))).is_equal_to([])
    assert_that(_value("Usage: p <v>", ["x"], _Unhashable)).is_equal_to(_REFUSED)
    assert_that(_value("Usage: p <v>", ["1"], _Unhashable)).is_same_as(_Unhashable.A)


class _Bomb:
    def __init__(self, text):
        if isinstance(text, str):
            raise RuntimeError(f"read from {text!r}")
        self.number = text

    def __eq__(self, other):
        return isinstance(other, _Bomb) and other.number == self.number

    def __hash__(self):
        return hash(self.number)


class _Late(enum.Enum):
    A = 1
    B = _Bomb(0)


def test_a_text_is_not_read_as_the_type_of_a_member_that_stands_after_the_one_it_spells():
    assert_that(_value("Usage: p <v>", ["1"], _Late)).is_equal_to(_Late.A)
    assert_that(_value("Usage: p <v>", ["2"], _Late)).is_equal_to("leaked RuntimeError: read from '2'")


@pytest.mark.parametrize("annotation", [_Angry | str, int | _Angry, Annotated[_Angry, "why"] | str | None])
def test_a_union_does_not_go_on_past_what_an_enum_of_the_author_raises_of_its_own(annotation):
    # a refusal of the value hands it to the next member, an exception of the author's code is no refusal
    assert_that(_value("Usage: p <v>", ["x"], annotation)).is_equal_to("leaked RuntimeError: boom 'x'")
    assert_that(_safely(lambda: check("Usage: p <v>", schema=_one(annotation)))).is_equal_to([])
    assert_that(_safely(lambda: complete("Usage: p <v> <w>", ["x", ""], schema=_one(annotation)))).is_instance_of(list)
