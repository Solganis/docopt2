from assertpy2 import assert_that
from hypothesis import given
from hypothesis import strategies as st
from pytest import raises

from docopt2 import DocoptExit, DocoptLanguageError, docopt
from docopt2._parser import (
    Argument,
    Command,
    Either,
    Option,
    Required,
    formal_tokens,
    parse_defaults,
    parse_pattern,
    required_leaf_names,
    single_usage_section,
)
from docopt2.hypothesis import argv_strategy

_DOC = (
    "Usage:\n"
    "  git push [--force] <remote>\n"
    "  git commit --message=<msg>\n"
    "  git add <path>...\n\n"
    "Options:\n"
    "  --force          Force.\n"
    "  --message=<msg>  Message.\n"
)


def test_near_miss_carets_a_missing_positional():
    with raises(DocoptExit) as exc_info:
        docopt(_DOC, "push", complete=False)
    message = str(exc_info.value)
    assert_that(message).contains("missing required `<remote>`").contains("closest of 3 usage patterns")
    assert_that(message).contains("git push [--force] <remote>")  # the snippet shows the closest line
    assert_that(message).contains("^")  # with a caret drawn under the missing element


def test_near_miss_carets_a_missing_valued_option():
    with raises(DocoptExit) as exc_info:
        docopt(_DOC, "commit", complete=False)
    assert_that(str(exc_info.value)).contains("missing required `--message`").contains("git commit")


def test_near_miss_picks_the_line_the_argv_got_furthest_into():
    # `push --force` fits the first line up to the still-missing <remote>, not commit or add.
    with raises(DocoptExit) as exc_info:
        docopt(_DOC, "push --force", complete=False)
    diagnostic = str(exc_info.value).split("\nUsage:")[0]  # drop the trailing usage reprint, which lists every line
    assert_that(diagnostic).contains("`<remote>`")
    assert_that(diagnostic).does_not_contain("--message").does_not_contain("<path>")


def test_no_near_miss_without_evidence_of_a_line():
    # A token matching no line's leading command is no evidence; fall back to the generic message.
    with raises(DocoptExit) as exc_info:
        docopt(_DOC, "clone", complete=False)
    assert_that(str(exc_info.value)).does_not_contain("closest of")


def test_single_line_usage_has_no_near_miss():
    with raises(DocoptExit) as exc_info:
        docopt("Usage: prog <host> <port>", "onlyhost", complete=False)
    assert_that(str(exc_info.value)).does_not_contain("closest of")


def _vocabulary(doc):
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_tokens(single_usage_section(doc)), options)
    names = {leaf.name for leaf in pattern.flat(Argument, Command, Option) if leaf.name}
    return names | {name for option in options for name in (option.short, option.long) if name}


_TOKENS = ["push", "commit", "add", "--force", "--message=m", "x", "origin", "--nope", "-z"]


@given(argv=st.lists(st.sampled_from(_TOKENS), max_size=5))
def test_near_miss_never_crashes_and_names_a_real_element(argv):
    # Whatever the argv, a near-miss must name an element the usage actually declares - never invent one.
    try:
        docopt(_DOC, argv, complete=False)
    except DocoptLanguageError:
        raise  # a doc error would be a real bug
    except DocoptExit as exit_signal:
        message = str(exit_signal)
        if "closest of" in message:
            named = message.split("missing required `")[1].split("`")[0]
            assert_that(named).is_in(*_vocabulary(_DOC))


_DISPATCH = "Usage:\n  tool build <target>\n  tool test [--fast]\n  tool deploy <env> <version>\n"
_MULTI_DOCS = [_DOC, _DISPATCH, "Usage:\n  p a <x>\n  p b <y> <z>\n"]


def _fail(doc, argv):
    """The DocoptExit message from a failing parse, for inspecting the near-miss it produced."""
    with raises(DocoptExit) as exc_info:
        docopt(doc, argv, complete=False)
    return str(exc_info.value)


def _required_names(doc):
    """Every element some usage line requires - via required_leaf_names, independent of the near-miss scorer,
    so it can cross-check what near-miss claims is missing."""
    pattern = parse_pattern(formal_tokens(single_usage_section(doc)), parse_defaults(doc))
    is_multi = isinstance(pattern, Required) and pattern.children and isinstance(pattern.children[0], Either)
    lines = pattern.children[0].children if is_multi else [pattern]
    return {name for line in lines for name in required_leaf_names(line)}


def test_near_miss_names_the_requirement_of_the_command_that_was_typed():
    # each leading command belongs to exactly one line, so near-miss must name THAT line's missing element
    assert_that(_fail(_DISPATCH, "build")).contains("missing required `<target>`")
    assert_that(_fail(_DISPATCH, "deploy prod")).contains("missing required `<version>`")


def test_near_miss_stays_on_the_line_as_the_argv_gets_further_in():
    # adding a token the push line accepts must not switch the diagnostic to a different line
    assert_that(_fail(_DOC, "push")).contains("`<remote>`")
    assert_that(_fail(_DOC, "push --force")).contains("`<remote>`")


@given(data=st.data())
def test_near_miss_names_a_genuinely_required_unmet_element(data):
    # Cross-validation against an independent oracle: take a valid argv, drop its last token so it fails,
    # and whatever near-miss names must be an element the grammar actually REQUIRES (per required_leaf_names)
    # - never an optional element it invented, nor a non-requirement.
    doc = data.draw(st.sampled_from(_MULTI_DOCS))
    full = data.draw(argv_strategy(doc))
    if not full:
        return
    try:
        docopt(doc, full[:-1], help=False, complete=False)
    except DocoptExit as exit_signal:
        message = str(exit_signal)
    else:
        return  # dropping the token still matched (it was optional) - not a near-miss case
    if "closest of" in message:
        named = message.split("missing required `")[1].split("`")[0]
        assert_that(named).is_in(*_required_names(doc))
