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
    from docopt2._parser import parse_defaults

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


def _refusal(doc: str) -> str | None:
    """The error ``docopt()`` raises for ``doc`` as a usage, as it prints. None where the doc parses."""
    try:
        docopt(doc, [], help=False, complete=False)
    except DocoptLanguageError as refused:
        return str(refused)
    except SystemExit:
        return None
    return None


_TOO_DEEP = "error: the usage pattern nests too deeply to parse"


def _options(doc: str) -> list[tuple[object, ...]]:
    """Every option ``doc`` declares, with all the parser reads of it."""
    return [(o.short, o.long, o.argcount, o.value, o.env, o.config_key) for o in parse_defaults(doc)]


def _hold_the_laws(doc: str) -> None:
    """Raise where ``check()`` and ``docopt()`` disagree on a usage, or ``format_usage()`` changes what one means.

    Mirrors _broken_law in tests/test_robustness.py.
    """
    refusal = _refusal(doc)
    errors = [found.render() for found in check(doc) if found.level == "error"]
    if _TOO_DEEP in (refusal, *errors):
        return  # how deep is too deep depends on the stack the parser was called from: no law at that edge
    if errors != ([] if refusal is None else [refusal]):
        raise AssertionError(f"check() says {errors!r} of a usage of which docopt() says {refusal!r}")
    if refusal is not None:
        return
    formatted = format_usage(doc)
    if (broken := _refusal(formatted)) is not None:
        raise AssertionError(f"format_usage() made a usage that parses into one that does not: {broken}")
    if _options(formatted) != _options(doc):
        raise AssertionError(f"format_usage() changed the options: {_options(doc)!r} to {_options(formatted)!r}")
    if format_usage(formatted) != formatted:
        raise AssertionError(f"format_usage() is not idempotent: {formatted!r} to {format_usage(formatted)!r}")


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
    _hold_the_laws(doc)


def main() -> None:
    """libFuzzer entry: flags (-max_total_time, -timeout, -artifact_prefix, ...) come in on sys.argv."""
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
