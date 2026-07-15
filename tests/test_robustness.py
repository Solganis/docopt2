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
    expand_options_shortcut,
    formal_usage,
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


def test_an_ambiguous_pattern_does_not_hang_on_a_long_argv():
    # 24 optional flags before a required <END>: an argv of all the flags and no END token has 2**24 ways
    # to assign the optionals, and none is complete. The per-Either cap does not bound this - the dead
    # branches yield nothing, so nothing is counted - and matching ran for tens of seconds. The global
    # match budget charges each exploration step, so an unmatchable argv is rejected in well under a second.
    flags = " ".join(f"[-{chr(97 + index)}]" for index in range(24))
    doc = f"usage: prog {flags} <END>"
    argv = [f"-{chr(97 + index)}" for index in range(24)]
    start = time.perf_counter()
    with pytest.raises(DocoptExit):
        docopt2.docopt(doc, argv, help=False)
    assert_that(time.perf_counter() - start).described_as("matching a 2**24-ambiguous argv").is_less_than(3.0)


def test_an_exponential_pattern_with_a_long_argv_still_rejects_in_bounded_time():
    # The subtler cousin: many optional flags before a MISSING required option, then a long file tail. The
    # optionals' 2**n dead-ends fail at the missing option before they reach the files, so the fan is
    # independent of the argv - but the long argv would inflate an argv-scaled budget past that fan and let it
    # run for tens of seconds. The whole match stays on ONE fixed ceiling, so it rejects fast regardless.
    flags = " ".join(f"[-{chr(97 + index)}]" for index in range(24))
    doc = f"usage: prog {flags} --need <files>..."
    argv = [f"-{chr(97 + index)}" for index in range(24)] + [f"f{index}" for index in range(300)]
    start = time.perf_counter()
    with pytest.raises(DocoptExit):
        docopt2.docopt(doc, argv, help=False)
    # Generous bound: the fix rejects in ~1s (a few seconds on a loaded runner), a regression runs for tens
    # of seconds - so 10s separates them without flaking on a slow CI cell (a tight 3s did, on ubuntu 3.10).
    assert_that(time.perf_counter() - start).described_as("an exponential pattern with a long argv").is_less_than(10.0)
