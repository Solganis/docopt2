import dataclasses

import pytest
from assertpy2 import assert_that

from docopt2 import DocoptLanguageError, docopt
from docopt2._core import _placed_tokens

_NAVAL = (
    "Usage:\n"
    "  prog ship <name> move <x> <y> [--speed=<kn>]\n"
    "  prog [-v] [-p <n>] <a>\n\n"
    "Options:\n"
    "  --speed=<kn>  Speed.\n"
    "  -p <n>  Port.\n"
    "  --verbose  Loud.\n"
    "  --version  Version."
)
_PUSH = "Usage: prog push [--force] [--message=<m>] <remote>\n\nOptions:\n  --force  Force.\n  --message=<m>  Message."
_SPEED = "Usage: prog [--speed=<kn>] <a>\n\nOptions:\n  --speed=<kn>  Speed."
_PORT = "Usage: prog [-p <n>] <a>\n\nOptions:\n  -p <n>  Port."
_COPY = "Usage: prog <name> <count>"
_AMOUNT = "Usage: prog -a <n>\n\nOptions:\n  -a <n>, --amount=<n>  Amount."
_GUTTER = len("   |    ")
_UNEXPECTED = "error: unexpected argument `{}`"
_NEEDS = "error: `{}` requires an argument"


@dataclasses.dataclass
class _Copy:
    name: str
    count: int


@dataclasses.dataclass
class _Amount:
    amount: int


def _refused(doc, argv, **settings):
    """The lines of the refusal, or a one-line account of an argv that was accepted or of an exception that leaked."""
    try:
        return [f"accepted: {docopt(doc, argv, complete=False, **settings)}"]
    except (SystemExit, DocoptLanguageError) as refusal:
        return str(refusal).splitlines()
    except (LookupError, NameError, RuntimeError, StopIteration) as leaked:
        return [f"leaked: {type(leaked).__name__}"]


def _pointed_at(doc, argv, source="in the arguments:", **settings):
    """The summary of the refusal, then the column and the text its caret under ``source`` stands at, if it has one."""
    lines = _refused(doc, argv, **settings)
    if f"   |  {source}" not in lines:
        return lines[0], "no such snippet"
    shown = lines[lines.index(f"   |  {source}") + 1]
    marks = lines[lines.index(f"   |  {source}") + 2]
    if "^" not in marks:
        return lines[0], "no caret"
    column = marks.index("^") - _GUTTER
    return lines[0], column, shown[_GUTTER:][column : column + marks.count("^")]


@pytest.mark.parametrize(
    ("doc", "argv", "settings", "expected"),
    [
        # the same text stands earlier in the line, as a token the usage took or inside one
        ("Usage: prog <a> <b>", ["x", "y", "x"], {}, (_UNEXPECTED.format("x"), 4, "x")),
        ("Usage: prog <a> <b>", ["x", "y", "x", "x"], {}, (_UNEXPECTED.format("x"), 4, "x")),
        ("Usage: prog <a>", ["xy", "y"], {}, (_UNEXPECTED.format("y"), 3, "y")),
        ("Usage: prog [--force] <a>", ["--force", "x", "--force"], {}, (_UNEXPECTED.format("--force"), 10, "--force")),
        ("Usage: prog <a>", ["--", "x", "x"], {}, (_UNEXPECTED.format("x"), 5, "x")),
        # an option is pointed at by its name as typed, whatever value its token goes on into
        ("Usage: prog <a>", ["x", "--speed=3"], {}, (_UNEXPECTED.format("--speed"), 2, "--speed")),
        (_SPEED, ["--spe=1", "x", "--spe=2"], {}, (_UNEXPECTED.format("--speed"), 10, "--spe")),
        (_PORT, ["-p5", "x", "-p6"], {}, (_UNEXPECTED.format("-p"), 6, "-p")),
        # each flag of a short token by its own letter, the first one with the dash
        ("Usage: prog [-v] <a>", ["-vq", "x"], {}, (_UNEXPECTED.format("-q"), 2, "q")),
        ("Usage: prog [-v] [-q] <a>", ["-vqz", "x"], {}, (_UNEXPECTED.format("-z"), 3, "z")),
        ("Usage: prog [-v] <a>", ["-qv", "x"], {}, (_UNEXPECTED.format("-q"), 0, "-q")),
        ("Usage: prog [-v] <a>", ["-q", "x"], {}, (_UNEXPECTED.format("-q"), 0, "-q")),
        # a refusal raised while the argv is being read points at the token it is about
        (_NAVAL, ["ship", "t", "move", "1", "2", "--speed"], {}, (_NEEDS.format("--speed"), 16, "--speed")),
        (_NAVAL, ["ship", "t", "move", "1", "2", "--speed", "--"], {}, (_NEEDS.format("--speed"), 16, "--speed")),
        (_NAVAL, ["--ver", "x"], {}, ("error: `--ver` is not a unique prefix of: --verbose, --version", 0, "--ver")),
        ("Usage: prog [--force]", ["--force=1"], {}, ("error: `--force` takes no argument", 0, "--force=1")),
        (_NAVAL, ["x", "-p"], {}, (_NEEDS.format("-p"), 2, "-p")),
        (_NAVAL, ["x", "-p", "--"], {}, (_NEEDS.format("-p"), 2, "-p")),
        # the places hold for an argv given as one string, whatever stands between its tokens
        ("Usage: prog <a> <b>", "x   y    x", {}, (_UNEXPECTED.format("x"), 9, "x")),
        ("Usage: prog <a> <b>", "x\ty x", {}, (_UNEXPECTED.format("x"), 10, "x")),
        (_NAVAL, "x   -p", {}, (_NEEDS.format("-p"), 4, "-p")),
        # a token is one place, with a space inside it or with nothing in it
        ("Usage: prog <a>", ["one", "two words"], {}, (_UNEXPECTED.format("two words"), 4, "two words")),
        ("Usage: prog <a>", ["x", "", "x"], {}, (_UNEXPECTED.format(""), 2, " ")),
        ("Usage: prog", [""], {}, (_UNEXPECTED.format(""), 0, "")),
        # under a setting that changes how many leaves a token is read as
        ("Usage: prog [-v] <a>", ["x", "-v"], {"options_first": True}, (_UNEXPECTED.format("-v"), 2, "-v")),
        ("Usage: prog <a>", ["x", "-ab"], {"options_first": True}, (_UNEXPECTED.format("-ab"), 2, "-ab")),
        ("Usage: prog <a>", ["x", "y", "--", "y"], {"options_first": True}, (_UNEXPECTED.format("y"), 2, "y")),
        ("Usage: prog <a>", ["-6.28", "-6.28"], {"negative_numbers": True}, (_UNEXPECTED.format("-6.28"), 6, "-6.28")),
        (_NAVAL, ["--ver", "x", "y"], {"allow_abbrev": False}, (_UNEXPECTED.format("--ver"), 0, "--ver")),
    ],
)
def test_the_caret_stands_under_the_token_at_fault_by_where_it_is_in_the_argv(doc, argv, settings, expected):
    assert_that(_pointed_at(doc, argv, **settings)).is_equal_to(expected)


@pytest.mark.parametrize(
    ("argv", "mistyped", "column", "meant", "declared"),
    [
        (["push", "--forcce", "origin"], "--forcce", 5, "--force", (18, "--force")),
        ("push   --forcce origin", "--forcce", 7, "--force", (18, "--force")),
        (["push", "--mesage=hi", "origin"], "--mesage", 5, "--message", (28, "--message=<m>")),
        (["push", "--forcce", "--forcce", "origin"], "--forcce", 5, "--force", (18, "--force")),
        # the same text stands earlier, inside a token or as the value an option took
        (["push", "--message=--forcce", "--forcce"], "--forcce", 24, "--force", (18, "--force")),
        (["push", "--message", "--forcce", "--forcce", "origin"], "--forcce", 24, "--force", (18, "--force")),
    ],
)
def test_a_mistyped_option_is_pointed_at_where_the_parser_read_it_as_an_option(argv, mistyped, column, meant, declared):
    summary = f"error: unknown option `{mistyped}`"
    assert_that(_pointed_at(_PUSH, argv, suggest=True)).is_equal_to((summary, column, mistyped))
    assert_that(_pointed_at(_PUSH, argv, source="in the usage:", suggest=True)).is_equal_to((summary, *declared))
    hints = [line for line in _refused(_PUSH, argv, suggest=True) if "did you mean" in line]
    assert_that(hints).is_equal_to([f"   = help: did you mean `{meant}`?"])


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        # read as the value of `--message`: the surplus token is what is refused
        (["push", "--message", "--forcce", "origin", "extra"], (_UNEXPECTED.format("extra"), 31, "extra")),
        # read as a positional behind `--`
        (["push", "origin", "--", "--forcce"], (_UNEXPECTED.format("--forcce"), 15, "--forcce")),
    ],
)
def test_a_token_the_parser_did_not_read_as_an_option_is_never_reported_as_a_mistyped_one(argv, expected):
    assert_that(_pointed_at(_PUSH, argv, suggest=True)).is_equal_to(expected)


@pytest.mark.parametrize(
    ("doc", "argv", "schema", "key", "in_argv", "in_usage"),
    [
        (_COPY, ["abc", "x1"], _Copy, "<count>", (4, "x1"), (19, "<count>")),
        # the text of the bad value stands at more than one place: the caret is under the token that held it
        (_COPY, ["abc", "abc"], _Copy, "<count>", (4, "abc"), (19, "<count>")),
        (_COPY, ["x1y", "x1"], _Copy, "<count>", (4, "x1"), (19, "<count>")),
        (_AMOUNT, ["-aaa"], _Amount, "--amount", (2, "aa"), (12, "-a")),
        # an empty argument has no text of its own: the token it is attached to
        (_AMOUNT, ["--amount="], _Amount, "--amount", (0, "--amount="), (12, "-a")),
    ],
)
def test_a_value_the_schema_refuses_is_pointed_at_by_its_place_in_the_line(doc, argv, schema, key, in_argv, in_usage):
    summary = f"error: invalid value for `{key}`"
    assert_that(_pointed_at(doc, argv, schema=schema)).is_equal_to((summary, *in_argv))
    assert_that(_pointed_at(doc, argv, source="in the usage:", schema=schema)).is_equal_to((summary, *in_usage))


@pytest.mark.parametrize(
    ("argv", "text", "places"),
    [
        (["a", "bb", "a"], "a bb a", [(0, 1), (2, 4), (5, 6)]),
        (["a", "", "b"], "a  b", [(0, 1), (2, 2), (3, 4)]),
        (("two words", "x"), "two words x", [(0, 9), (10, 11)]),
        ("a  bb\ta", "a  bb\ta", [(0, 1), (3, 5), (6, 7)]),
        ([""], "", [(0, 0)]),
        ([], "", []),
    ],
)
def test_an_argv_read_for_a_refusal_knows_the_line_it_prints_and_where_each_token_stands(argv, text, places):
    placed = _placed_tokens(argv, "Usage: prog", 1)
    assert_that(placed.text).is_equal_to(text)
    assert_that(placed.spans).is_equal_to(places)
    assert_that(list(placed)).is_equal_to(argv.split() if isinstance(argv, str) else list(argv))


def test_only_a_refused_parse_asks_where_a_token_stood(monkeypatch):
    asked = []

    def recorded(argv, usage, exit_code):
        asked.append(argv)
        return _placed_tokens(argv, usage, exit_code)

    monkeypatch.setattr("docopt2._core._placed_tokens", recorded)
    result = docopt(_NAVAL, ["ship", "t", "move", "1", "2", "--speed=3"], complete=False)
    assert_that(result["--speed"]).is_equal_to("3")
    assert_that(asked).is_empty()
    assert_that(_pointed_at("Usage: prog <a>", ["x", "y"])).is_equal_to((_UNEXPECTED.format("y"), 2, "y"))
    assert_that(asked).is_equal_to([["x", "y"]])


@pytest.mark.parametrize("once", [iter, lambda argv: (token for token in argv)], ids=["iterator", "generator"])
@pytest.mark.parametrize(
    ("doc", "argv", "settings", "expected"),
    [
        (_SPEED, ["x", "--speed"], {}, (_NEEDS.format("--speed"), "no such snippet")),
        ("Usage: prog <a>", ["x", "y"], {}, (_UNEXPECTED.format("y"), "no caret")),
        (_PUSH, ["push", "--forcce", "x"], {"suggest": True}, ("error: unknown option `--forcce`", "no caret")),
    ],
)
def test_an_argv_that_can_be_read_only_once_is_still_refused_and_gets_no_caret(once, doc, argv, settings, expected):
    assert_that(_pointed_at(doc, once(argv), **settings)).is_equal_to(expected)


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        # about the option itself: the caret is under it, whatever follows it in the usage
        (
            "Usage: prog --flag=<x> <y>\n\nOptions:\n  --flag  A flag.",
            ("error: `--flag` takes no argument", 12, "--flag=<x>"),
        ),
        ("Usage: prog -p <y>\n\nOptions:\n  -p  One.\n  -p  Two.", ("error: `-p` is specified 2 times", 12, "-p")),
        # about an argument that is missing: where it was expected, or the option when the usage ends there
        ("Usage: prog (--speed) <y>\n\nOptions:\n  --speed=<kn>  Speed.", (_NEEDS.format("--speed"), 20, ")")),
        ("Usage: prog [-p] <y>\n\nOptions:\n  -p <n>  Port.", (_NEEDS.format("-p"), 15, "]")),
        ("Usage: prog --speed\n\nOptions:\n  --speed=<kn>  Speed.", (_NEEDS.format("--speed"), 12, "--speed")),
    ],
)
def test_a_usage_refusal_points_at_the_option_it_is_about_or_at_where_its_argument_was_expected(doc, expected):
    assert_that(_pointed_at(doc, [], source="in the usage:")).is_equal_to(expected)
