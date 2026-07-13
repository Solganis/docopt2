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
    _usage_lines,
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
    assert_that(message).contains("missing required `<remote>`")
    assert_that(message).contains("of 3 usage patterns, your arguments came closest to this one")
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
    assert_that(str(exc_info.value)).does_not_contain("came closest to")


def test_a_positional_only_usage_has_no_literal_to_take_as_evidence():
    # Positionals match any token, so `onlyhost` is evidence of nothing and there is no line to caret.
    with raises(DocoptExit) as exc_info:
        docopt("Usage: prog <host> <port>", "onlyhost", complete=False)
    assert_that(str(exc_info.value)).does_not_contain("required here")


def test_a_single_line_usage_carets_its_unmet_element():
    # The caret was gated off below two usage lines - the commonest shape there is. Ranking needs
    # alternatives; the caret does not, and a lone line still has an element the argv failed to supply.
    with raises(DocoptExit) as exc_info:
        docopt("Usage: prog push [--force] <remote>", "push", complete=False)
    rendered = str(exc_info.value)
    assert_that(rendered).contains("missing required `<remote>`").contains("^^^^^^^^ required here")
    assert_that(rendered).does_not_contain("came closest to")  # nothing to rank against, so no such note


def test_a_single_line_usage_carets_a_required_choice_group():
    with raises(DocoptExit) as exc_info:
        docopt("Usage: prog move (up | down) <n>", "move", complete=False)
    assert_that(str(exc_info.value)).contains("missing required `(up|down)`").contains("required here")


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
        if "came closest to" in message:
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


# --- The near-miss used to break whenever the first unmet requirement was NOT a plain leaf. Every one of
# --- these slipped past the property test below, which is blind to them three ways over: it runs only when
# --- the diagnostic fired (so a SUPPRESSED one is skipped), it asserts the named element is *a* required
# --- element rather than *the* first unmet one (so naming the wrong one passes), and its oracle,
# --- required_leaf_names, is leaf-only (so a group could never be named at all). No test doc had a
# --- two-level subcommand either, which is the single most common real-world CLI shape.

_NESTED = "Usage:\n  git remote add <name> <url>\n  git remote rm <name>\n  git push <remote>\n"
_CHOICE = "Usage:\n  tool db (up|down) <steps>\n  tool serve <port>\n"
_SEQUENCE = "Usage:\n  tool run (build test) <target>\n  tool clean\n"


def test_near_miss_fires_on_a_partial_two_level_subcommand():
    # `git remote` matches a command (+2) and then misses the next one (-2), netting exactly zero, so the
    # old score-only gate went silent precisely where a nested CLI (git remote add) leaves the user.
    message = _fail(_NESTED, "remote")
    assert_that(message).contains("missing required `add`").contains("came closest to this one")


def test_near_miss_carets_the_choice_group_not_the_leaf_after_it():
    # `tool db` is missing the `(up|down)` group. A branch that matched nothing never recorded itself, so
    # the scorer walked straight past it and blamed `<steps>` - advice that still fails when followed.
    message = _fail(_CHOICE, "db")
    assert_that(message).contains("missing required `(up|down)`").does_not_contain("`<steps>`")


def test_near_miss_names_a_missing_repetition():
    # `git add` needs `<path>...`; a OneOrMore is a branch, so `missing` was never set and the diagnostic
    # went silent even though that line was the outright winner.
    message = _fail(_DOC, "add")
    assert_that(message).contains("missing required `<path>`").contains("came closest to this one")


def test_near_miss_carets_a_missing_parenthesised_sequence():
    assert_that(_fail(_SEQUENCE, "run")).contains("missing required `(build test)`")


def test_near_miss_stays_silent_without_a_matched_literal():
    # A positional matches ANY token, so a garbage argv "resembles" every line. Only a matched command or
    # option is evidence of intent - which is why the score alone cannot gate the diagnostic.
    assert_that(_fail(_NESTED, "bogus")).does_not_contain("came closest to")


_PREFIX_DOCS = [_DOC, _DISPATCH, _NESTED, _CHOICE]


def _literals(doc):
    """Every command and option the usage writes down - tokens a user could only have typed on purpose."""
    pattern = parse_pattern(formal_tokens(single_usage_section(doc)), parse_defaults(doc))
    return {leaf.name for leaf in pattern.flat() if isinstance(leaf, Command | Option) and leaf.name}


@given(data=st.data())
def test_near_miss_never_goes_silent_on_a_real_prefix_of_a_valid_argv(data):
    # The oracle here is a VALID argv: truncate it and the user is provably on their way somewhere. If that
    # truncation named a literal, the diagnostic MUST help instead of falling back to the generic error.
    # This is exactly the assertion the older property cannot make - it skips every case where nothing fired,
    # so a silently suppressed near-miss is invisible to it.
    doc = data.draw(st.sampled_from(_PREFIX_DOCS))
    full = data.draw(argv_strategy(doc))
    if len(full) < 2:
        return
    cut = data.draw(st.integers(min_value=1, max_value=len(full) - 1))
    prefix = full[:cut]
    if not (_literals(doc) & {token.split("=")[0] for token in prefix}):
        return  # no literal typed: the diagnostic is meant to stay silent, and another test pins that
    try:
        docopt(doc, prefix, help=False, complete=False)
    except DocoptExit as exit_signal:
        message = str(exit_signal)
    else:
        return  # the prefix still parses (the rest was optional) - not a near-miss case at all
    assert "came closest to this one" in message, f"went silent on {prefix!r}, a real prefix of {full!r}"


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
    if "came closest to" in message:
        named = message.split("missing required `")[1].split("`")[0]
        assert_that(named).is_in(*_required_names(doc))


def test_usage_lines_returns_a_pattern_it_cannot_unwrap_as_the_single_line():
    # The two shapes a parsed usage takes are Required(Either(...)) and Required(Required(...)). Anything
    # else is not a usage tree, and the helper hands it back whole rather than guessing at its children.
    leaf = Command("x")
    assert_that(_usage_lines(leaf)).is_equal_to([leaf])
    shallow = Required(Argument("<x>"))  # a Required whose child is neither an Either nor a Required
    assert_that(_usage_lines(shallow)).is_equal_to([shallow])
