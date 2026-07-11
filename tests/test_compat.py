import re

from assertpy2 import assert_that
from hypothesis import given, settings
from hypothesis import strategies as st
from pytest import raises

from _strategies import _expr, doc_strategy
from docopt2 import DocoptExit, DocoptLanguageError, check_compat, docopt

_PUSH = "Usage: prog push [--force] <remote>\n\nOptions:\n  --force  Force."
_ANY_DOC = st.one_of(
    doc_strategy,
    st.lists(_expr, min_size=1, max_size=3).map(lambda bodies: "usage:\n" + "\n".join(f"  prog {b}" for b in bodies)),
)


def test_no_break_when_adding_an_optional_flag():
    old = "Usage: prog push <remote>"
    new = "Usage: prog push [--verbose] <remote>\n\nOptions:\n  --verbose  Verbose."
    assert_that(check_compat(old, new)).is_empty()


def test_no_break_when_adding_a_new_usage_line():
    old = "Usage: prog push <remote>"
    assert_that(check_compat(old, "Usage:\n  prog push <remote>\n  prog pull <remote>")).is_empty()


def test_a_removed_option_is_reported_structurally():
    assert_that(check_compat(_PUSH, "Usage: prog push <remote>")).contains("option `--force` removed")


def test_a_removed_command_is_reported_structurally():
    old = "Usage:\n  prog add <x>\n  prog rm <x>"
    assert_that(check_compat(old, "Usage: prog add <x>")).contains("command `rm` removed")


def test_a_new_required_positional_is_caught_by_a_concrete_counterexample():
    breaks = check_compat("Usage: prog checkout <name>", "Usage: prog checkout <name> <branch>")
    assert_that(breaks).is_not_empty()
    assert_that(any("no longer accepted" in entry for entry in breaks)).is_true()


def test_a_structural_break_suppresses_its_redundant_sampled_examples():
    # removing --force is named once; the many `push --force ...` argvs it explains are not also listed
    assert_that(check_compat(_PUSH, "Usage: prog push <remote>")).is_equal_to(["option `--force` removed"])


def test_a_break_with_no_structural_cause_still_reports_only_a_few_shapes():
    # a new required positional yields many `checkout v1/v2/...` argvs, but they share one shape -> one line
    breaks = check_compat("Usage: prog checkout <name>", "Usage: prog checkout <name> <branch>")
    assert_that(len(breaks)).is_less_than_or_equal_to(5)


def test_the_report_is_deterministic():
    old, new = "Usage: prog checkout <name>", "Usage: prog checkout <name> <branch>"
    assert_that(check_compat(old, new)).is_equal_to(check_compat(old, new))


def test_the_example_list_is_capped_to_stay_scannable():
    # six command lines each gain a required <y>, so six distinct breaking shapes exist; the report caps them
    commands = "abcdef"
    old = "Usage:\n" + "\n".join(f"  prog {name} <x>" for name in commands)
    new = "Usage:\n" + "\n".join(f"  prog {name} <x> <y>" for name in commands)
    assert_that(len(check_compat(old, new))).is_equal_to(5)


@given(doc=_ANY_DOC)
@settings(max_examples=100, deadline=None)
def test_a_usage_is_compatible_with_itself(doc):
    # reflexivity: no version breaks from itself, so no false break is ever reported for an unchanged usage
    try:
        reported = check_compat(doc, doc)
    except DocoptLanguageError:
        return
    assert reported == []


@given(old=_ANY_DOC, new=_ANY_DOC)
@settings(max_examples=100, deadline=None)
def test_every_reported_counterexample_is_genuine(old, new):
    # soundness: an argv reported "no longer accepted" is really accepted by old and rejected by new
    try:
        reported = check_compat(old, new)
    except DocoptLanguageError:
        return
    for entry in reported:
        match = re.fullmatch(r"`(.*)` no longer accepted", entry)
        if match is None:
            continue  # a structural "option/command removed" line, not a sampled counterexample
        argv = match.group(1).split()
        docopt(old, argv, help=False, complete=False)  # raises if old does not actually accept it
        with raises(DocoptExit):
            docopt(new, argv, help=False, complete=False)
