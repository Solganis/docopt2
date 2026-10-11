import itertools
import re

from assertpy2 import assert_that
from hypothesis import event, given
from hypothesis import strategies as st

from _strategies import argv_strategy, doc_strategy
from docopt2 import Argument, DocoptExit, DocoptLanguageError, Option, Tokens, docopt, generate_examples
from docopt2._core import _argv_leaves, _placed_tokens
from docopt2._parser import (
    MatchBudget,
    _MatchBudgetExceededError,
    formal_tokens,
    parse_defaults,
    parse_pattern,
    single_usage_section,
)

_NAMED = re.compile(r"error: (?:unexpected argument|unknown option|unknown command) `(.*)`")
_MISTYPED = st.lists(st.sampled_from(["--fooo", "--bat", "--optt=1", "ad", "cmdd"]), max_size=2)
_MISSPELLED = {"cmd": "cmdd", "add": "ad"}
_some_argv = argv_strategy.filter(len)
_argv_with_typos = st.tuples(_some_argv, _MISTYPED).flatmap(lambda drawn: st.permutations(drawn[0] + drawn[1]))


def _shape(leaves):
    return [(type(leaf).__name__, leaf.name, leaf.value) for leaf in leaves]


def _read(tokens, reading):
    """The leaves of the argv, or the summary of the refusal raised while reading it."""
    try:
        return _argv_leaves(tokens, *reading)
    except DocoptExit as refusal:
        return str(refusal).splitlines()[0]


def _fits(leaf, text):
    """Whether ``text``, cut from the line at the leaf's span, is how that leaf can be typed."""
    if not isinstance(leaf, Option):
        return text == leaf.value
    if text.startswith("--"):
        return str(leaf.long).startswith(text)
    return text in (leaf.short, str(leaf.short)[1:])


def _strangers(outcomes, given_leaves):
    """The leftover leaves that are none of ``given_leaves``, up to where the search ends or runs out of budget."""
    known = {id(leaf) for leaf in given_leaves}
    found = []
    try:
        for left, _ in outcomes:
            found += [leaf for leaf in left if id(leaf) not in known]
    except _MatchBudgetExceededError:
        pass
    return found


@given(doc_strategy, _some_argv, st.booleans(), st.booleans(), st.booleans())
def test_a_placed_read_gives_the_leaves_of_a_plain_read_each_at_the_place_of_its_own_text(
    doc, argv, options_first, negative_numbers, allow_abbrev
):
    try:
        usage = single_usage_section(doc)
        options = parse_defaults(doc)
        pattern = parse_pattern(formal_tokens(usage), options)
    except DocoptLanguageError:
        return
    reading = (pattern, options, options_first, negative_numbers, allow_abbrev)
    plain = _read(Tokens(argv), reading)
    placed = _read(_placed_tokens(argv, usage, 1), reading)
    if isinstance(plain, str):
        event("both reads compared as refusals")
        assert_that(placed).is_equal_to(plain)
        return
    event(f"leaves compared: {min(len(plain), 3)}{'+' if len(plain) > 3 else ''}")
    assert_that(_shape(placed)).is_equal_to(_shape(plain))
    line = " ".join(argv)
    misplaced = [leaf for leaf in placed if leaf.span is None or not _fits(leaf, line[leaf.span[0] : leaf.span[1]])]
    assert_that(_shape(misplaced)).is_empty()
    starts = [leaf.span[0] for leaf in placed]
    assert_that(starts).is_equal_to(sorted(set(starts)))


@given(doc_strategy, _some_argv)
def test_what_the_matcher_leaves_over_is_made_of_the_leaf_objects_it_was_given(doc, argv):
    try:
        usage = single_usage_section(doc)
        options = parse_defaults(doc)
        pattern = parse_pattern(formal_tokens(usage), options)
        given_leaves = _argv_leaves(Tokens(argv), pattern, options, False, False, True)
        pattern.fix()
    except (DocoptLanguageError, DocoptExit):
        return
    with MatchBudget():
        outcomes = itertools.islice(pattern.matches(given_leaves, []), 40)
        seen = []
        strangers = _strangers((seen.append(outcome) or outcome for outcome in outcomes), given_leaves)
    event(f"outcomes with leftovers checked: {min(sum(bool(left) for left, _ in seen), 2)}")
    assert_that(_shape(strangers)).is_empty()


def test_a_stranger_among_the_leftovers_is_reported_though_the_search_then_runs_out_of_budget():
    given_leaf, stranger = Argument(None, "x"), Argument(None, "x")

    def outcomes():
        yield [given_leaf], []
        yield [given_leaf, stranger], []
        raise _MatchBudgetExceededError

    assert_that(_strangers(outcomes(), [given_leaf])).is_length(1)
    assert_that(_strangers(outcomes(), [given_leaf])[0]).is_same_as(stranger)
    assert_that(_strangers(outcomes(), [given_leaf, stranger])).is_empty()


@given(doc_strategy, _argv_with_typos, st.booleans())
def test_a_refusal_that_names_a_token_carets_text_that_token_can_be_typed_as(doc, argv, suggest):
    try:
        docopt(doc, argv, suggest=suggest, complete=False)
    except DocoptLanguageError:
        return
    except DocoptExit as refusal:
        lines = str(refusal).splitlines()
    else:
        return
    named = _NAMED.fullmatch(lines[0])
    if named is None:
        return
    name = named.group(1)
    event(f"caret checked: {lines[0].split(' `')[0]}, the name stands {min(argv.count(name), 2)} times in the argv")
    at = lines.index("   |  in the arguments:")
    shown, marks = lines[at + 1][8:], lines[at + 2][8:]
    under = shown[marks.index("^") : marks.index("^") + marks.count("^")] if "^" in marks else None
    typed_as = [name, name[1:]] if re.fullmatch(r"-[^-]", name) else [name]
    assert_that(typed_as).contains(under)


@given(st.sampled_from(sorted(_MISSPELLED)), doc_strategy, st.integers(0, 1000), st.data())
def test_a_usage_led_by_a_command_refuses_that_command_misspelled_and_hints_back_to_it(command, doc, seed, data):
    led = doc.replace("usage: prog ", f"usage: prog {command} (", 1) + ")"
    try:
        accepted = generate_examples(led, count=6, seed=seed)
    except DocoptLanguageError:
        return
    argv = data.draw(st.sampled_from(accepted))
    at = argv.index(command)
    misspelled = [*argv[:at], _MISSPELLED[command], *argv[at + 1 :]]
    try:
        said = [f"accepted: {docopt(led, misspelled, complete=False)}"]
    except DocoptExit as refusal:
        said = str(refusal).splitlines()
    hint = [line for line in said if line.startswith("   = help: did you mean `")]
    column = said[said.index("   |  in the arguments:") + 2][8:].index("^") if hint else None
    event(f"the command stands at token {min(at, 2)} of {min(len(argv), 3)}")
    assert_that((said[0], hint, column)).is_equal_to(
        (
            f"error: unknown command `{misspelled[at]}`",
            [f"   = help: did you mean `{command}`?"],
            len(" ".join(misspelled[:at])) + bool(at),
        )
    )
