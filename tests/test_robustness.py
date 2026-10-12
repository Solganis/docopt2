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
from docopt2 import DocoptExit, DocoptLanguageError, _completion
from docopt2._completion import _frontier, _Steps
from docopt2._parser import (
    MATCH_LIMIT,
    MatchBudget,
    Tokens,
    _MatchBudgetExceededError,
    expand_options_shortcut,
    formal_tokens,
    formal_usage,
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


_TOO_DEEP = ["usage: prog " + opening * 400 + "<x>" + closing * 400 for opening, closing in ("[]", "()")]


@pytest.mark.parametrize("doc", _TOO_DEEP, ids=["optional", "required"])
@pytest.mark.parametrize("name", sorted(_ENTRY_POINTS))
def test_a_usage_nested_too_deeply_is_refused_as_a_usage_by_every_entry_point_that_parses_it(name, doc):
    try:
        _ENTRY_POINTS[name](doc, ["x"])
        said = "returned"
    except DocoptLanguageError as refused:
        said = str(refused).splitlines()[0]
    except RecursionError:
        said = "RecursionError leaked"
    assert_that(said).is_in("returned", "error: the usage pattern nests too deeply to parse")
    parses_it = {"docopt", "generate_stub", "generate_examples", "generate_completion", "parse_tree", "check_compat"}
    assert_that(said == "returned").is_equal_to(name not in parses_it)


def _refusal(doc: str) -> str | None:
    """The error ``docopt()`` raises for ``doc`` as a usage, as it prints. None where the doc parses."""
    try:
        docopt2.docopt(doc, [], help=False, complete=False)
    except DocoptLanguageError as refused:
        return str(refused)
    except SystemExit:
        return None
    return None


_NESTS_TOO_DEEPLY = "error: the usage pattern nests too deeply to parse"


def _options(doc: str) -> list[tuple[object, ...]]:
    return [(o.short, o.long, o.argcount, o.value, o.env, o.config_key) for o in parse_defaults(doc)]


def _broken_law(doc: str) -> str | None:
    """The law ``doc`` breaks, or None. Mirrors _hold_the_laws in fuzz/fuzz_docopt.py, which holds them over what
    coverage finds."""
    refusal = _refusal(doc)
    errors = [found.render() for found in docopt2.check(doc) if found.level == "error"]
    if _NESTS_TOO_DEEPLY in (refusal, *errors):
        return None  # how deep is too deep depends on the stack the parser was called from: no law at that edge
    if errors != ([] if refusal is None else [refusal]):
        return "check() reports an error exactly where docopt() refuses the usage"
    if refusal is None:
        formatted = docopt2.format_usage(doc)
        if _refusal(formatted) is not None:
            return "a usage that parses still parses once formatted"
        if _options(formatted) != _options(doc):
            return "formatting changes no option"
        if docopt2.format_usage(formatted) != formatted:
            return "formatting twice is formatting once"
    return None


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(doc=_hostile_doc)
def test_a_hostile_docstring_keeps_the_laws_the_fuzzer_holds(doc):
    assert_that(_broken_law(doc)).is_none()


def test_the_laws_are_waived_for_a_usage_nested_too_deeply_and_for_nothing_that_only_says_so(monkeypatch):
    assert_that(_refusal(_TOO_DEEP[0])).is_equal_to(_NESTS_TOO_DEEPLY)
    quoting = "Usage: prog (nests too deeply"
    assert_that(_refusal(quoting)).contains("unclosed `(`", "nests too deeply").is_not_equal_to(_NESTS_TOO_DEEPLY)
    assert_that(_broken_law(quoting)).is_none()
    # with a check() that goes blind, the first law is broken for that usage and waived for the deep one
    monkeypatch.setattr(docopt2, "check", lambda _doc: [])
    assert_that(_broken_law(quoting)).is_equal_to("check() reports an error exactly where docopt() refuses the usage")
    assert_that(_broken_law(_TOO_DEEP[0])).is_none()


@pytest.mark.parametrize(
    ("format_usage", "law"),
    [
        (lambda doc: doc.replace("[options]", "[options"), "a usage that parses still parses once formatted"),
        (lambda doc: doc.replace("--opt=<v>", "--opt"), "formatting changes no option"),
        (lambda doc: doc + " ", "formatting twice is formatting once"),
    ],
)
def test_each_law_of_the_formatter_is_one_a_wrong_formatter_breaks(monkeypatch, format_usage, law):
    monkeypatch.setattr(docopt2, "format_usage", format_usage)
    doc = "Usage: prog [options]\n\nOptions:\n  --opt=<v>  Value [default: 7]."
    assert_that(_broken_law(doc)).is_equal_to(law)


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
    flags = " ".join(f"[-{chr(97 + index)}]" for index in range(24))
    stopped_at, later, unbudgeted = _descents_of_a_refusal(f"usage: prog {flags} <END>", 24)
    assert_that(stopped_at).described_as("descents before the budget stopped the match").is_equal_to(5001)
    assert_that(later).described_as("descents of what ran under a budget after it").is_less_than(10)
    assert_that(unbudgeted).described_as("descents made under no budget").is_equal_to(0)


def test_scoring_the_usage_lines_of_a_refusal_runs_under_a_budget_too():
    # the same optionals in ONE group: scoring the lines to word the refusal ran 2**n descents under no budget
    flags = " ".join(f"[-{chr(97 + index)}]" for index in range(18))
    stopped_at, later, unbudgeted = _descents_of_a_refusal(f"usage: prog ({flags} <END>)", 18)
    assert_that((stopped_at, unbudgeted)).is_equal_to((5001, 0))
    assert_that(later).is_less_than(10)


def _descents_of_a_refusal(doc: str, flags: int) -> tuple[int, int, int]:
    """Refuse an argv of ``flags`` short options with the budget tripping past 5000 descents.

    Returns the descents charged up to the first trip, the ones charged under a budget after it, and the ones
    made under no budget at all.
    """
    charges, trips, unbudgeted = 0, [], 0

    def counting_spend() -> None:
        nonlocal charges, unbudgeted
        if docopt2._parser._match_budget.get() is None:
            unbudgeted += 1
            return
        charges += 1
        if charges > 5000:
            trips.append(charges)
            raise docopt2._parser._MatchBudgetExceededError

    argv = [f"-{chr(97 + index)}" for index in range(flags)]
    original = docopt2._parser._spend_budget
    docopt2._parser._spend_budget = counting_spend
    try:
        with pytest.raises(DocoptExit):
            docopt2.docopt(doc, argv, help=False)
    finally:
        docopt2._parser._spend_budget = original
    return trips[0], charges - trips[0], unbudgeted


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
    with pytest.raises(_MatchBudgetExceededError), MatchBudget(100):
        next(pattern.matches(argv, []), None)


def _walk(doc, typed):
    """The paths the completion walk yields for ``typed``, and the steps it spent of its budget."""
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_usage(single_usage_section(doc)), options)
    expand_options_shortcut(pattern, options)
    steps = _Steps()
    paths = list(_frontier(pattern, parse_argv(Tokens(list(typed)), list(options)), block=False, steps=steps))
    return paths, MATCH_LIMIT - steps.left


def test_the_completion_walk_ends_where_it_yields_nothing_too():
    # after a word nothing takes, `[-rrr]...` tried every subset of its flags: 9.8 s for 22 of them, and no path
    doc = "usage: prog [-" + "r" * 22 + "]... expected"
    paths, spent = _walk(doc, ["wrong"])
    assert_that([remaining for remaining, _frontier_of_it, _blocks in paths if remaining == []]).is_empty()
    # the budget is spent whole, and the walk winds up within a few steps of it
    assert_that(spent).is_between(MATCH_LIMIT, MATCH_LIMIT + 1000)
    assert_that(docopt2.complete(doc, ["wrong", ""])).is_empty()
    assert_that(docopt2.complete(doc, [""])).is_equal_to(["-r", "expected"])


def test_a_path_handed_up_costs_the_walk_its_length():
    # seventy stacked flags: 200,000 steps of visiting alone yielded paths that took a Tab 7 s to carry upward
    paths, spent = _walk("usage: prog [-" + "r" * 70 + "]...", [])
    assert_that(spent).is_between(MATCH_LIMIT, MATCH_LIMIT + 1000)
    assert_that(sum(len(frontier) for _remaining, frontier, _blocks in paths)).is_less_than(MATCH_LIMIT)
    assert_that(docopt2.complete("usage: prog [-" + "r" * 70 + "]...", [""])).is_equal_to(["-r"])


def test_a_real_usage_spends_a_thousandth_of_the_budget():
    for path in _CORPUS:
        if path.stem == "many_flags":
            continue  # twenty-five flags: see the next test
        doc = path.read_text(encoding="utf-8")
        for example in docopt2.generate_examples(doc, count=5, seed=1):
            assert_that(_walk(doc, example[:-1])[1]).described_as(f"{path.stem} {example}").is_less_than(
                MATCH_LIMIT // 100
            )


def test_a_walk_cut_at_the_budget_answers_as_one_given_ten_times_more(monkeypatch):
    # each option typed doubles the walk of twenty-five flags: with thirteen typed it spends the whole budget
    doc = (Path(__file__).parent / "corpus" / "many_flags.txt").read_text(encoding="utf-8")
    longest = max(docopt2.generate_examples(doc, count=4, seed=1), key=len)
    prefixes = [[*longest[:cut], ""] for cut in (0, 8, 15, 20, len(longest))]
    spent = [_walk(doc, words[:-1])[1] for words in prefixes]
    assert_that([steps >= MATCH_LIMIT for steps in spent]).is_equal_to([False, False, True, True, True])
    answers = [docopt2.complete(doc, words) for words in prefixes]
    monkeypatch.setattr(_completion, "MATCH_LIMIT", MATCH_LIMIT * 10)
    assert_that([docopt2.complete(doc, words) for words in prefixes]).is_equal_to(answers)


_STACKED = "[-" + "r" * 17 + "]..."


@pytest.mark.parametrize(
    "doc",
    [
        f"Usage: prog ({_STACKED} | later)",
        f"Usage: prog (later | {_STACKED})",
        f"Usage:\n  prog {_STACKED}\n  prog later <x>",
        f"Usage: prog {_STACKED} later",
    ],
)
def test_an_alternative_beside_one_that_spends_its_share_of_the_walk_is_still_offered(doc):
    # on a budget of its own the first alternative spent all of it, and `later` was never reached
    assert_that(docopt2.complete(doc, [""])).is_equal_to(["-r", "later"])


def test_a_walk_out_of_budget_winds_up_at_once_however_wide_the_usage():
    words = " ".join(f"[w{n}]" for n in range(60))
    assert_that(_walk(f"Usage: prog {_STACKED} {words}", [])[1] - MATCH_LIMIT).is_between(0, 1)
    # an alternative winds up on its own share: a few steps each, and never a budget each
    alternatives = " | ".join(f"{_STACKED} c{n}" for n in range(40))
    assert_that(_walk(f"Usage: prog ({alternatives})", [])[1] - MATCH_LIMIT).is_between(0, 40 * 20)
