# Coverage-guided fuzzing of the public API with atheris (Linux/macOS only; there is no Windows wheel).
# The invariant is the one tests/test_robustness.py states and Hypothesis checks on grammar-shaped input:
# no entry point may raise anything but its own DocoptExit / DocoptLanguageError for ANY input. Hypothesis
# only ever builds well-formed usage; atheris reaches the malformed shapes it cannot - unbalanced brackets,
# NUL bytes, an option line run into its description - from arbitrary bytes under coverage feedback, and the
# libFuzzer -timeout turns a runaway (a pathological slowdown or an outright hang) into a reported finding.
#
# atheris has no Windows wheel; run on Linux/macOS. The Fuzz workflow is the canonical invocation (corpus
# seeds + dict + flags); replay a saved reproducer with:  python fuzz/fuzz_docopt.py <reproducer-file>
from __future__ import annotations

import contextlib
import sys

import atheris

with atheris.instrument_imports():
    from docopt2 import (
        DocoptExit,
        DocoptLanguageError,
        check,
        complete,
        docopt,
        format_usage,
        generate_completion,
        generate_config_template,
        generate_examples,
        generate_stub,
        parse_tree,
    )

# DocoptExit (a SystemExit subclass, and the --help path) and DocoptLanguageError are the only errors the
# public API may raise. Anything else escaping is the finding. Mirrors _OWN_ERRORS in test_robustness.py so
# the fuzzer and the property suite can never disagree on what "correct" means.
_OWN_ERRORS = (DocoptExit, DocoptLanguageError, SystemExit)

# Every public entry point, driven with help and completion off so a fuzzed `--help` cannot exit the
# process mid-run. One input exercises all of them. check_compat is deliberately absent: it runs docopt()
# once per generated sample against argvs IT builds from the (fuzzer-maximised) grammar, so it manufactures
# a slow-but-bounded run that is a property of the sample count, not a defect - its own logic is
# deterministic and unit-tested. The runtime surface it shares (docopt, generate_examples) is fuzzed here.
_ENTRY_POINTS = (
    lambda doc, argv: docopt(doc, argv, help=False, complete=False),
    lambda doc, argv: check(doc),
    lambda doc, argv: format_usage(doc),
    lambda doc, argv: generate_stub(doc),
    lambda doc, argv: generate_examples(doc, count=2, seed=0),
    lambda doc, argv: generate_config_template(doc),
    lambda doc, argv: generate_completion(doc, "prog"),
    lambda doc, argv: complete(doc, argv),
    lambda doc, argv: parse_tree(doc),
)


def test_one_input(data: bytes) -> None:
    """Split the bytes on NUL into a usage message and argv tokens, then drive every entry point.

    A plain split (rather than atheris.FuzzedDataProvider) keeps the encoding transparent: a seed file that
    is a real usage message decodes back to itself, so the corpus in fuzz/corpus and the docopt.dict tokens
    actually steer the fuzzer into the parser instead of leaving it to guess the word ``usage:`` from noise.
    """
    usage_bytes, *argv_bytes = data.split(b"\x00")
    doc = usage_bytes.decode("utf-8", "replace")
    # Cap the token count: the matcher is linear per step but each step scans the argv, so an ambiguous
    # pattern against a many-hundred-token argv is bounded-but-slow. A real invocation is short (a long
    # `<files>...` glob is the OneOrMore path, which stays linear), so 32 tokens covers the shapes worth
    # fuzzing without letting the harness manufacture a slow run out of an unrealistic argv.
    argv = [token.decode("utf-8", "replace") for token in argv_bytes[:32]]
    for entry in _ENTRY_POINTS:
        with contextlib.suppress(*_OWN_ERRORS):
            entry(doc, argv)


def main() -> None:
    """libFuzzer entry: flags (-max_total_time, -timeout, -artifact_prefix, ...) come in on sys.argv."""
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
