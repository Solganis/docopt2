import contextlib
import io

from assertpy2 import assert_that
from pytest import raises

from docopt2 import DocoptExit, DocoptLanguageError, docopt, generate_examples
from docopt2._generate import _unknown_option

# A spread of grammar shapes: commands, positionals, variadics, alternation, required and optional
# groups, valued and flag options, the [options] shortcut, and nesting.
_DOCS = [
    "Naval Fate.\n\nUsage:\n  naval ship new <name>...\n  naval ship <name> move <x> <y> [--speed=<kn>]\n"
    "  naval ship shoot <x> <y>\n  naval -h\n\nOptions:\n  --speed=<kn>  Speed [default: 10].\n  -h  Help.",
    "Usage:\n  git-tool clone <url> [--depth=<n>]\n  git-tool commit [-m <msg>] [--amend]\n"
    "  git-tool remote add <name> <url>\n\nOptions:\n  --depth=<n>  Depth.\n  -m <msg>  Msg.\n  --amend  Amend.",
    "Usage: prog --port=<n>",
    "Usage: prog (add | rm) <x>",
    "Usage: prog [<a> <b>] <c>",
    "Usage: prog (a [<x>] | b <y>)... [-v]\n\nOptions:\n  -v  V.",
    "Usage: prog [options] <f>\n\nOptions:\n  -v  V.\n  --port=<n>  P.",
    # `[--]` takes every later token as a positional, so an appended unknown option does not reject.
    "Usage: prog [--] <cmd> <args>...",
]


def test_every_valid_example_parses():
    # The generator's core promise: every argv it labels valid is one docopt actually accepts.
    for doc in _DOCS:
        for argv in generate_examples(doc, count=25, seed=1):
            docopt(doc, argv, help=False, complete=False)  # raises DocoptExit if the generator diverges


def test_every_invalid_example_is_rejected():
    # `help=True`, the way a program really calls docopt: the old `help=False` here switched off the very
    # short-circuit that broke the promise, so an argv carrying `--help` exited 0 unseen.
    for doc in _DOCS:
        for argv in generate_examples(doc, count=25, valid=False, seed=1):
            with contextlib.redirect_stdout(io.StringIO()), raises(DocoptExit):
                docopt(doc, argv, complete=False)


def test_examples_are_distinct_and_reproducible():
    doc = "Usage: prog (add | rm) <x> [--force]\n\nOptions:\n  --force  Force.\n"
    first = generate_examples(doc, count=6, seed=99)
    assert_that(first).is_length(len({tuple(argv) for argv in first}))  # no duplicates
    assert_that(generate_examples(doc, count=6, seed=99)).is_equal_to(first)  # same seed, same output


def test_a_tiny_grammar_returns_fewer_than_requested():
    # `prog` alone accepts one argv (empty), so deduplication caps the result at that one example.
    assert_that(generate_examples("Usage: prog", count=10)).is_equal_to([[]])


def test_count_zero_returns_no_examples():
    assert_that(generate_examples("Usage: prog <x>", count=0)).is_empty()


def test_generate_examples_raises_on_a_malformed_usage():
    assert_that(generate_examples).raises(DocoptLanguageError).when_called_with("usage: prog (a]")


def test_unknown_option_picks_a_free_name_when_the_obvious_one_is_taken():
    doc = "Usage: prog [--unknown]\n\nOptions:\n  --unknown  Taken.\n"
    assert_that(_unknown_option(doc)).is_equal_to("--unknown-x")
