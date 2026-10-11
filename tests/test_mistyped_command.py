import pytest
from assertpy2 import assert_that

from docopt2 import Cli, Dispatch, DocoptLanguageError, Tokens, docopt
from docopt2._core import _argv_leaves, _mistyped_command
from docopt2._parser import (
    MatchBudget,
    _match_budget,
    formal_tokens,
    parse_defaults,
    parse_pattern,
    single_usage_section,
)

_GIT = (
    "Usage:\n"
    "  git commit [--amend] [-m <msg>]\n"
    "  git checkout <branch>\n"
    "  git push [--force] <remote>\n"
    "  git remote add <name> <url>\n\n"
    "Options:\n"
    "  --amend  Amend.\n"
    "  -m <msg>  Message.\n"
    "  --force  Force."
)
_NAVAL = "Usage:\n  naval ship <name> move <x> <y>\n  naval ship shoot <x> <y>\n  naval mine (set|remove) <x> <y>"
_APP = (
    "Usage:\n"
    "  app add <path> [--verbose]\n"
    "  app commit [--verbose] [--amend]\n"
    "  app push [--force] [--verbose]\n\n"
    "Options:\n"
    "  --verbose  Chatty.\n"
    "  --amend  Amend.\n"
    "  --force  Force."
)
_FILE_OR_ADD = "Usage:\n  prog add <x>\n  prog <file>"
_START_ALONE = "Usage:\n  prog start\n  prog stat <file>"
_ONLY_START_IS_CLOSE = "Usage:\n  prog start\n  prog zzzzz <file>"
_ONLY_STAT_IS_CLOSE = "Usage:\n  prog zzzzz\n  prog stat <file>"
_START_OR_STAT = "Usage:\n  prog start <file>\n  prog stat <file>"
_AD_IS_A_COMMAND = "Usage:\n  prog add <x>\n  prog ad"
_COMMIT_TWICE = "Usage:\n  prog commit\n  prog commit <file>"
_ANY_COMMAND = "Usage:\n  git commit\n  git <command> [<args>...]"
_GUIDE = "Usage:\n  git commit [--amend]\n  git push [--force] <remote>"
_GUTTER = len("   |    ")
_NO_MATCH = "error: the arguments do not match the usage"


def _refused(doc, argv, **settings):
    """The lines of the refusal, or a one-line account of an argv that was accepted or of an exception that leaked."""
    try:
        return [f"accepted: {docopt(doc, argv, complete=False, **settings)}"]
    except (SystemExit, DocoptLanguageError) as refusal:
        return str(refusal).splitlines()
    except Exception as leaked:
        return [f"leaked: {type(leaked).__name__}"]


def _caret(lines, source):
    """The source line shown under ``source``, then the column and the text its caret stands at. None where absent."""
    if f"   |  {source}" not in lines:
        return None
    shown = lines[lines.index(f"   |  {source}") + 1][_GUTTER:]
    marks = lines[lines.index(f"   |  {source}") + 2]
    if "^" not in marks:
        return None
    column = marks.index("^") - _GUTTER
    return shown.strip(), column, shown[column : column + marks.count("^")]


def _hinted(doc, argv, **settings):
    """The summary, the argv caret, the usage caret and the help line of the refusal, each None where absent."""
    lines = _refused(doc, argv, **settings)
    helps = [line for line in lines if line.startswith("   = help: ")]
    return lines[0], _caret(lines, "in the arguments:"), _caret(lines, "in the usage:"), helps[0] if helps else None


def _unknown(kind, typed, meant, in_argv, in_usage):
    return f"error: unknown {kind} `{typed}`", in_argv, in_usage, f"   = help: did you mean `{meant}`?"


@pytest.mark.parametrize(
    ("doc", "argv", "typed", "meant", "at", "declared"),
    [
        (_GIT, ["comit", "--amend"], "comit", "commit", 0, ("git commit [--amend] [-m <msg>]", 6, "commit")),
        (_GIT, ["remote", "ad", "origin", "url"], "ad", "add", 7, ("git remote add <name> <url>", 13, "add")),
        (_GIT, "remote   ad origin url", "ad", "add", 9, ("git remote add <name> <url>", 13, "add")),
        (
            _NAVAL,
            ["ship", "Guardian", "mvoe", "1", "2"],
            "mvoe",
            "move",
            14,
            ("naval ship <name> move <x> <y>", 20, "move"),
        ),
        (_NAVAL, ["mine", "sett", "1", "2"], "sett", "set", 5, ("naval mine (set|remove) <x> <y>", 14, "set")),
        # another usage line would take the token as a value and leave a surplus: the proven typo is the better account
        (_FILE_OR_ADD, ["ad", "foo"], "ad", "add", 0, ("prog add <x>", 7, "add")),
        # the closest command is the one hinted where it fits, and the next closest where the closest does not
        (_START_OR_STAT, ["star", "f"], "star", "start", 0, ("prog start <file>", 7, "start")),
        (_START_ALONE, ["star", "f"], "star", "stat", 0, ("prog stat <file>", 7, "stat")),
        # the command is cross-referenced in the usage line that takes the corrected argv, not in the first or the last
        (_COMMIT_TWICE, ["comit"], "comit", "commit", 0, ("prog commit", 7, "commit")),
        (_COMMIT_TWICE, ["comit", "f"], "comit", "commit", 0, ("prog commit <file>", 7, "commit")),
        (_NAVAL, ["shp", "shoot", "1", "2"], "shp", "ship", 0, ("naval ship shoot <x> <y>", 8, "ship")),
        # the line is the one the corrected argv comes closest to, which the refused argv need not
        ("Usage:\n  prog <y> add\n  prog add <x>", ["ad", "v"], "ad", "add", 0, ("prog add <x>", 7, "add")),
        # and where that line does not write the command, the first place the usage does
        ("Usage:\n  prog (add <x>)\n  prog <a> tail <b>", ["ad", "tail"], "ad", "add", 0, ("prog (add <x>)", 8, "add")),
        # where a line writes the command more than once, at the first place it does, whichever the token fills
        ("Usage: prog add add", ["add", "ad"], "ad", "add", 4, ("Usage: prog add add", 12, "add")),
        ("Usage: prog add add", ["ad", "add"], "ad", "add", 0, ("Usage: prog add add", 12, "add")),
    ],
)
def test_a_mistyped_command_is_named_with_the_command_meant_and_the_usage_line_that_takes_it(
    doc, argv, typed, meant, at, declared
):
    shown = argv if isinstance(argv, str) else " ".join(argv)
    expected = _unknown("command", typed, meant, (shown, at, typed), declared)
    assert_that(_hinted(doc, argv)).is_equal_to(expected)
    followed = shown[:at] + meant + shown[at + len(typed) :]
    assert_that(_refused(doc, followed)[0]).described_as("the argv with the hint followed").starts_with("accepted: ")


@pytest.mark.parametrize(
    ("doc", "argv", "settings", "expected"),
    [
        # with `commit` in its place the argv still does not parse: `comit` may be a branch name
        (_GIT, ["checkout", "comit", "extra"], {}, ("error: unexpected argument `extra`", 15, "extra")),
        (_GUIDE, ["push", "comit", "extra"], {}, ("error: unexpected argument `extra`", 11, "extra")),
        (_GIT, ["comit", "--force"], {}, (_NO_MATCH, None, None)),
        (_GIT, ["zzz"], {}, (_NO_MATCH, None, None)),
        # a short flag gets no hint
        (_GIT, ["commit", "-n"], {}, ("error: unexpected argument `-n`", 7, "-n")),
        # a token that is a command of the usage is not a mistyped one, however close it is to another
        (_AD_IS_A_COMMAND, ["ad", "y"], {}, ("error: unexpected argument `y`", 3, "y")),
        (_GIT, ["comit", "--amend"], {"suggest": False}, (_NO_MATCH, None, None)),
    ],
)
def test_no_command_is_hinted_where_the_correction_is_not_proven_or_hints_are_off(doc, argv, settings, expected):
    summary, column, text = expected
    in_argv = None if column is None else (" ".join(argv), column, text)
    assert_that(_hinted(doc, argv, **settings)).is_equal_to((summary, in_argv, None, None))


_WIDE = " ".join(f"[a{index}]" for index in range(1500))
_UNSCORABLE = f"Usage:\n  prog safe [--verbose]\n  prog start [--verbose] ({_WIDE})\n\nOptions:\n  --verbose  Chatty."
_SAFE_LINE = "prog safe [--verbose]"


@pytest.mark.parametrize(
    ("argv", "settings", "summary", "declared"),
    [
        (["safe", "--verbsoe"], {}, "error: unknown option `--verbsoe`", (_SAFE_LINE, 13, "--verbose")),
        (["safe", "--verbsoe"], {"suggest": False}, "error: unexpected argument `--verbsoe`", None),
        (
            ["safe", "--verbose", "--verbose"],
            {},
            "error: unexpected argument `--verbose`",
            (_SAFE_LINE, 13, "--verbose"),
        ),
        (["--verbose"], {}, _NO_MATCH, None),
    ],
)
def test_a_usage_line_too_wide_to_score_is_ranked_last_and_the_refusal_is_worded_from_the_others(
    argv, settings, summary, declared
):
    lines = _refused(_UNSCORABLE, argv, **settings)
    assert_that((lines[0], _caret(lines, "in the usage:"))).is_equal_to((summary, declared))


def test_no_command_is_hinted_that_docopt_itself_would_refuse():
    # the first line alone takes `commit`, and docopt() still refuses it: matching primes the second line too
    doc = f"Usage:\n  prog commit\n  prog commit {_WIDE}"
    assert_that(_refused(doc, ["commit"])[0]).is_equal_to("error: the arguments are too deeply nested to match")
    assert_that(_hinted(doc, ["comit"])).is_equal_to((_NO_MATCH, None, None, None))


class _Port(Cli):
    __cli_doc__ = "Usage: prog commit <port>"
    commit: bool
    port: int


def test_the_proof_of_a_hint_is_the_usage_taking_the_argv_not_a_schema_binding_it():
    typo = _summary_and_help(lambda: _Port.parse(["comit", "eighty"], complete=False))
    value = _summary_and_help(lambda: _Port.parse(["commit", "eighty"], complete=False))
    assert_that((typo, value)).is_equal_to((_COMIT, ("error: invalid value for `<port>`", [])))


def test_a_usage_that_takes_any_command_accepts_the_token_as_it_is():
    said = _refused(_ANY_COMMAND, ["comit", "x"])
    assert_that(said).is_equal_to([f"accepted: {docopt(_ANY_COMMAND, ['comit', 'x'], suggest=False)}"])
    assert_that(docopt(_ANY_COMMAND, ["comit", "x"])["<command>"]).is_equal_to("comit")


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        # a mistyped option: declared in the line the argv came closest to, else where it is first written
        (
            ["commit", "--verbsoe"],
            _unknown(
                "option",
                "--verbsoe",
                "--verbose",
                ("commit --verbsoe", 7, "--verbsoe"),
                ("app commit [--verbose] [--amend]", 14, "--verbose"),
            ),
        ),
        (
            ["commit", "--forse"],
            _unknown(
                "option",
                "--forse",
                "--force",
                ("commit --forse", 7, "--forse"),
                ("app push [--force] [--verbose]", 12, "--force"),
            ),
        ),
        (
            ["--verbsoe"],
            _unknown(
                "option",
                "--verbsoe",
                "--verbose",
                ("--verbsoe", 0, "--verbsoe"),
                ("app add <path> [--verbose]", 18, "--verbose"),
            ),
        ),
        # an option given twice: the same rule for where it is declared
        (
            ["push", "--verbose", "--verbose"],
            (
                "error: unexpected argument `--verbose`",
                ("push --verbose --verbose", 15, "--verbose"),
                ("app push [--force] [--verbose]", 22, "--verbose"),
                "   = help: give it at most once, not with a mutually exclusive option",
            ),
        ),
    ],
)
def test_an_option_is_cross_referenced_in_the_usage_line_the_argv_came_closest_to(argv, expected):
    assert_that(_hinted(_APP, argv)).is_equal_to(expected)


def test_a_handler_table_refuses_a_mistyped_command_with_the_same_hint():
    app = Dispatch(_GIT)
    app.on("commit")(lambda args: "committed")
    assert_that(_summary_and_help(lambda: app.run(["comit", "--amend"], complete=False))).is_equal_to(_COMIT)
    assert_that(app.run(["commit", "--amend"], complete=False)).is_equal_to("committed")


def test_an_argv_that_can_be_read_only_once_gets_the_hint_and_no_caret():
    declared = ("git commit [--amend] [-m <msg>]", 6, "commit")
    expected = ("error: unknown command `comit`", None, declared, "   = help: did you mean `commit`?")
    assert_that(_hinted(_GIT, iter(["comit", "--amend"]))).is_equal_to(expected)


class _Git(Cli):
    __cli_doc__ = _GIT
    commit: bool
    amend: bool


def _summary_and_help(call):
    """The summary line and the help lines of the refusal ``call`` raises, or what it returned."""
    try:
        return call()
    except SystemExit as refusal:
        lines = str(refusal).splitlines()
        return lines[0], [line for line in lines if line.startswith("   = help: ")]


_COMIT = ("error: unknown command `comit`", ["   = help: did you mean `commit`?"])


def test_a_schema_class_hints_by_default_too_and_not_with_suggest_off():
    hinted = _summary_and_help(lambda: _Git.parse(["comit", "--amend"], complete=False))
    plain = _summary_and_help(lambda: _Git.parse(["comit", "--amend"], complete=False, suggest=False))
    assert_that((hinted, plain)).is_equal_to((_COMIT, (_NO_MATCH, [])))


def _searched(doc, argv):
    """What the search for a mistyped command finds in ``argv``: the typo and the command meant, or None, or a leak."""
    usage = single_usage_section(doc)
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_tokens(usage), options)
    leaves = _argv_leaves(Tokens(argv), pattern, options, False, False, True)
    pattern.fix()
    try:
        found = _mistyped_command(pattern, leaves)
    except Exception as leaked:
        return f"leaked: {type(leaked).__name__}"
    return found and (leaves[found[0]].value, found[1][found[0]].value)


def _budgets(monkeypatch, limit=1000):
    """Give every search a budget of ``limit`` and return the list that fills with what each opened budget spent."""
    spent = []

    class Metered(MatchBudget):
        def __exit__(self, *raised):
            spent.append(limit - _match_budget.get()[0])
            super().__exit__(*raised)

    monkeypatch.setattr("docopt2._core.MatchBudget", lambda: Metered(limit))
    return spent


def test_the_search_for_a_hint_stops_with_none_once_it_has_spent_its_budget(monkeypatch):
    assert_that(_searched(_GIT, ["comit", "--amend"])).is_equal_to(("comit", "commit"))
    _budgets(monkeypatch, limit=0)
    assert_that(_searched(_GIT, ["comit", "--amend"])).is_none()


def test_every_attempt_of_one_search_draws_on_the_one_budget_the_search_opened(monkeypatch):
    spent = _budgets(monkeypatch)
    assert_that(_searched(_ONLY_START_IS_CLOSE, ["star", "f"])).is_none()
    assert_that(_searched(_ONLY_STAT_IS_CLOSE, ["star", "f"])).is_equal_to(("star", "stat"))
    on_start, on_stat = spent
    assert_that(min(on_start, on_stat)).is_greater_than(0)
    # `start` is tried first and does not fit, then `stat` does: two attempts, one budget, and it pays for both
    assert_that(_searched(_START_ALONE, ["star", "f"])).is_equal_to(("star", "stat"))
    assert_that(spent).is_equal_to([on_start, on_stat, on_start + on_stat])
    _budgets(monkeypatch, limit=on_start + on_stat - 1)
    assert_that(_searched(_START_ALONE, ["star", "f"])).is_none()
    assert_that(_searched(_ONLY_STAT_IS_CLOSE, ["star", "f"])).is_equal_to(("star", "stat"))


def test_a_corrected_argv_that_matches_too_deep_gives_no_hint_and_no_leak():
    # a usage line this wide overflows the stack once the matcher gets past its first element
    names = [f"a{index}" for index in range(1500)]
    doc = "usage: prog start " + " ".join(names)
    assert_that(_searched(doc, ["star", *names])).is_none()
    assert_that(_refused(doc, ["star", *names])[0]).is_equal_to("error: missing or mismatched arguments")
