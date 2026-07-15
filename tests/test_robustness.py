"""Two invariants nobody had written down, and the corpus that exercises them.

The suite has always tested what each entry point DOES. These test what none of them may do: raise an
exception that is not its own, or take a visible amount of time. Both were being violated in shipped
code - a GUI program with no `sys.stderr` crashed inside the error's own constructor, and a Tab press on
a 25-flag CLI took over a second - and the reason neither was caught is that the property generators are
grammar-shaped: they only ever build well-formed usage from a dozen atoms, with balanced brackets by
construction and no Options section at all. They cannot reach the shapes that break things.
"""

import itertools
import time
from pathlib import Path

import pytest
from assertpy2 import assert_that
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import docopt2
from docopt2 import DocoptExit, DocoptLanguageError
from docopt2._completion import _frontier
from docopt2._parser import (
    MATCH_LIMIT,
    Tokens,
    _MatchBudgetExceededError,
    expand_options_shortcut,
    formal_tokens,
    formal_usage,
    match_budget,
    parse_argv,
    parse_defaults,
    parse_pattern,
    single_usage_section,
)

_CORPUS = sorted((Path(__file__).parent / "corpus").glob("*.txt"))
_CORPUS_IDS = [path.stem for path in _CORPUS]

# Every public entry point, and the argv (where it takes one) it is driven with.
_ENTRY_POINTS = {
    "docopt": lambda doc, argv: docopt2.docopt(doc, argv, help=False, complete=False),
    "check": lambda doc, argv: docopt2.check(doc),
    "format_usage": lambda doc, argv: docopt2.format_usage(doc),
    "generate_stub": lambda doc, argv: docopt2.generate_stub(doc),
    "generate_examples": lambda doc, argv: docopt2.generate_examples(doc, count=2, seed=0),
    "generate_config_template": lambda doc, argv: docopt2.generate_config_template(doc),
    "generate_completion": lambda doc, argv: docopt2.generate_completion(doc, "prog"),
    "complete": lambda doc, argv: docopt2.complete(doc, argv),
    "parse_tree": lambda doc, argv: docopt2.parse_tree(doc),
    "check_compat": lambda doc, argv: docopt2.check_compat(doc, doc),
}

# DocoptExit and DocoptLanguageError are the two errors this library defines; SystemExit is DocoptExit's
# base (and the `--help` path). ValueError is allowed for format_argv ALONE, which documents it - letting
# every entry point off the same hook would be the test grading its own homework.
_OWN_ERRORS: tuple[type[BaseException], ...] = (DocoptExit, DocoptLanguageError, SystemExit)


def _drive(name: str, doc: str, argv: list[str]) -> None:
    """Call an entry point and let only its own errors through."""
    try:
        _ENTRY_POINTS[name](doc, argv)
    except _OWN_ERRORS:
        pass


@pytest.mark.parametrize("doc_path", _CORPUS, ids=_CORPUS_IDS)
@pytest.mark.parametrize("name", sorted(_ENTRY_POINTS))
def test_a_real_usage_message_never_makes_an_entry_point_raise_a_foreign_error(name, doc_path):
    doc = doc_path.read_text(encoding="utf-8")
    argvs = [[], ["--nope"], ["-"], ["--"], *docopt2.generate_examples(doc, count=5, seed=0)]
    for argv in argvs:
        _drive(name, doc, argv)  # a foreign exception escapes and fails the test


@pytest.mark.parametrize("doc_path", _CORPUS, ids=_CORPUS_IDS)
def test_format_argv_round_trips_every_example_a_real_usage_accepts(doc_path):
    # The corpus doubles as the round-trip's input: an argv the usage accepts must format back to itself.
    doc = doc_path.read_text(encoding="utf-8")
    for argv in docopt2.generate_examples(doc, count=8, seed=1):
        result = docopt2.docopt(doc, argv, help=False, complete=False)
        formatted = docopt2.format_argv(result, doc)
        assert_that(docopt2.docopt(doc, formatted, help=False, complete=False)).is_equal_to(result)


# Fragments a docstring is really made of, including the ones that are subtly WRONG - an unbalanced
# bracket, an option line run together with its description, two config keys that collide.
_USAGE_FRAGMENTS = [
    "usage: prog <x>",
    "Usage:\n  prog ship <name> move <x> <y>\n  prog mine (set|remove) <x> <y>",
    "usage: prog [options] <x>...",
    "usage: prog (a | b) [--opt=<v>]",
    "usage: prog [--to=<a>]... <c>",
    "usage: prog (a",
    "usage: prog a]",
    "usage: prog [[[[<x>]]]]",
    "usage:",
    "usage: prog --",
    "Usage: prog <x>\nUsage: prog <y>",
    "  prog <x>",
    "",
]
_OPTION_FRAGMENTS = [
    "",
    "\n\nOptions:\n  -v --verbose  Loud.",
    "\n\nOptions:\n  --opt=<v>  Value [default: 7].",
    "\n\nOptions:\n  --to=<a>  Target [env: T] [config: a.b].",
    "\n\nOptions:\n  --opt=<v>  Run together with description",
    "\n\nOptions:\n  - fast, quick  A prose bullet, not an option.",
    "\n\nOptions:\n  --a=<x>  One [config: k].\n  --b=<y>  Two [config: k].",
    "\n\nArguments:\n  <x>  Positional [default: 9].",
    "\n\nOptions:\n\t-t\tTabbed.",
]
_NOISE = ["", "\r\n", "\x00", "é", "\n\n\n", "        "]

_hostile_doc = st.builds(
    lambda usage, options, before, after: before + usage + options + after,
    st.sampled_from(_USAGE_FRAGMENTS),
    st.sampled_from(_OPTION_FRAGMENTS),
    st.sampled_from(_NOISE),
    st.sampled_from(_NOISE),
)
_hostile_argv = st.lists(
    st.sampled_from(["a", "ship", "set", "-v", "--verbose", "--opt=1", "--to=x", "--", "-", "1", "\x00"]),
    max_size=5,
)


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(doc=_hostile_doc, argv=_hostile_argv)
@pytest.mark.parametrize("name", sorted(_ENTRY_POINTS))
def test_a_hostile_docstring_never_makes_an_entry_point_raise_a_foreign_error(name, doc, argv):
    _drive(name, doc, argv)


def _frontier_paths(doc: str) -> int:
    """How many partial-consumption paths the completion resolver walks for an empty prefix."""
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_usage(single_usage_section(doc)), options)
    expand_options_shortcut(pattern, options)
    return sum(1 for _ in itertools.islice(_frontier(pattern, [], block=False), MATCH_LIMIT))


def test_the_completion_walk_is_linear_in_the_option_count_not_exponential():
    # The deterministic half of the latency guard, and the exact invariant that broke: every optional
    # element used to fork the walk in two, so `[options]` over N options cost 2**N paths. At N=18 that
    # already hit MATCH_LIMIT (200,000 paths), and one Tab press took seconds.
    walked = [_frontier_paths(_many_flags(count)) for count in (5, 15, 25)]
    assert_that(walked).described_as("paths walked for 5, 15 and 25 options").is_equal_to([1, 1, 1])


def _many_flags(count: int) -> str:
    options = "\n".join(f"  --opt{index}=<v>  Option {index}." for index in range(count))
    return f"usage: prog [options] <x>\n\nOptions:\n{options}"


def test_completion_answers_a_real_sized_cli_without_a_visible_pause():
    # The user-facing half: a Tab press is the most latency-sensitive call in the library, and a CLI the
    # size of `kubectl get` is not adversarial. The budget is ~100x the real cost, so a loaded CI runner
    # cannot flake it - only a return of the exponential walk can.
    doc = (Path(__file__).parent / "corpus" / "many_flags.txt").read_text(encoding="utf-8")
    for words in ([""], ["get", ""], ["get", "pods", ""], ["get", "pods", "--w"]):
        start = time.perf_counter()
        docopt2.complete(doc, words)
        assert_that(time.perf_counter() - start).described_as(f"complete({words})").is_less_than(1.0)


def test_the_budget_stops_an_exponential_match_instead_of_running_it_to_exhaustion():
    # 24 optional flags before a required <END>: 2**24 ways to assign the optionals, none complete. The match
    # must be STOPPED by the budget, not explored to exhaustion. Asserted on the descents charged, not the
    # clock: wall-clock is neither deterministic nor portable here (coverage tracing alone slows the same
    # match ~15x, and it swings 20x run to run). Trip at a small count so the test is instant even under
    # coverage; docopt() must catch the exceeded budget and reject.
    charges = 0

    def counting_spend() -> None:
        nonlocal charges
        if docopt2._parser._match_budget.get() is None:
            return  # unbudgeted (near-miss scoring after the match): do not count or trip
        charges += 1
        if charges > 5000:
            raise docopt2._parser._MatchBudgetExceededError

    flags = " ".join(f"[-{chr(97 + index)}]" for index in range(24))
    doc = f"usage: prog {flags} <END>"
    argv = [f"-{chr(97 + index)}" for index in range(24)]
    original = docopt2._parser._spend_budget
    docopt2._parser._spend_budget = counting_spend
    try:
        with pytest.raises(DocoptExit):
            docopt2.docopt(doc, argv, help=False)
    finally:
        docopt2._parser._spend_budget = original
    assert_that(charges).described_as("descents before the budget stopped the match").is_equal_to(5001)


def test_docopt_installs_one_fixed_match_ceiling_whatever_the_argv_length():
    # The whole match rides ONE fixed ceiling - MATCH_LIMIT - no matter how long the argv. A per-token budget
    # (an earlier, reverted attempt) would raise the ceiling for a long argv and let an exponential pattern
    # run for minutes; the fixed ceiling does not. Read the ceiling docopt() installs on the first descent,
    # then trip at once - deterministic and instant, where a wall-clock bound is neither.
    installed: list[int] = []

    def probe_ceiling() -> None:
        budget = docopt2._parser._match_budget.get()
        if budget is None:
            return
        installed.append(budget[0])  # the ceiling as installed, before any decrement
        raise docopt2._parser._MatchBudgetExceededError

    flags = " ".join(f"[-{chr(97 + index)}]" for index in range(24))
    doc = f"usage: prog {flags} --need <files>..."
    argv = [f"-{chr(97 + index)}" for index in range(24)] + [f"f{index}" for index in range(2000)]
    original = docopt2._parser._spend_budget
    docopt2._parser._spend_budget = probe_ceiling
    try:
        with pytest.raises(DocoptExit):
            docopt2.docopt(doc, argv, help=False)
    finally:
        docopt2._parser._spend_budget = original
    assert_that(installed[0]).described_as("match ceiling installed for a long argv").is_equal_to(MATCH_LIMIT)


def test_the_match_budget_raises_once_its_ceiling_is_spent():
    # The tests above stub out `_spend_budget`; this drives the real one to its ceiling. A small explicit
    # budget over an exponential, complete-match-less pattern (12 optionals before a required <END>) trips it
    # in a handful of descents - deterministic and cheap, no wall-clock and no 200k burn.
    doc = "usage: prog " + " ".join(f"[-{chr(97 + index)}]" for index in range(12)) + " <END>"
    usage = single_usage_section(doc)
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_tokens(usage), options)
    expand_options_shortcut(pattern, options)
    pattern.fix()
    tokens = Tokens([f"-{chr(97 + index)}" for index in range(12)], usage=usage, exit_code=1)
    argv = parse_argv(tokens, list(options))  # options_first / negative_numbers / allow_abbrev keep defaults
    with pytest.raises(_MatchBudgetExceededError), match_budget(100):
        next(pattern.matches(argv, []), None)
