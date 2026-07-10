from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from _strategies import argv_strategy, doc_strategy
from docopt2 import DocoptExit, DocoptLanguageError, complete, docopt
from docopt2._parser import (
    Command,
    Option,
    Tokens,
    formal_usage,
    parse_argv,
    parse_defaults,
    parse_pattern,
    parse_section,
)


def _vocabulary(doc: str) -> set[str] | None:
    """The command and option names a doc defines, or None if it does not parse (an oracle)."""
    try:
        usage = parse_section("usage:", doc)
        if not usage:
            return None
        options = parse_defaults(doc)
        pattern = parse_pattern(formal_usage(usage[0]), options)
    except (DocoptLanguageError, DocoptExit):
        return None
    names = {str(command.name) for command in pattern.flat(Command)}
    names |= {name for option in [*options, *pattern.flat(Option)] for name in (option.short, option.long) if name}
    return names


@given(doc=doc_strategy, argv=argv_strategy)
def test_allow_extra_is_a_no_op_on_already_valid_input(doc, argv):
    # Whatever the strict parser accepts, allow_extra must accept identically: same values, same
    # provenance, and no surplus. This pins the salvage path so it can never perturb a valid parse.
    try:
        strict = docopt(doc, argv, help=False)
    except (DocoptExit, DocoptLanguageError):
        return
    relaxed = docopt(doc, argv, help=False, allow_extra=True)
    assert dict(relaxed) == dict(strict)
    assert relaxed.extra == []
    assert relaxed.provided == strict.provided
    # provenance can only ever name elements that are actually in the result
    assert strict.provided <= set(strict.keys())


@given(doc=doc_strategy, argv=argv_strategy, code=st.integers(min_value=2, max_value=255))
def test_custom_exit_code_is_honored_on_every_failure_path(doc, argv, code):
    # Every argv-rejection path must carry the configured status onto the SystemExit, no matter
    # which branch (suggest, unmatched, missing, or an argv tokenizing error) raised it.
    try:
        docopt(doc, argv, help=False, exit_code=code)
    except DocoptExit as exc:
        assert exc.code == code
    except DocoptLanguageError:
        pass  # a malformed docstring is a developer error, not a process exit


@given(doc=doc_strategy, words=argv_strategy)
def test_completion_is_safe_sorted_and_within_the_grammar_vocabulary(doc, words):
    # The resolver must never crash, whatever the grammar or typed prefix; its output must be a
    # sorted, duplicate-free subset of the doc's real command/option names, each matching the
    # partial word under the cursor.
    result = complete(doc, words)
    assert result == sorted(set(result))
    incomplete = words[-1] if words else ""
    assert all(candidate.startswith(incomplete) for candidate in result)
    vocabulary = _vocabulary(doc)
    if vocabulary is not None:
        assert set(result) <= vocabulary


@given(doc=doc_strategy, typed=argv_strategy)
def test_completion_offers_every_token_that_immediately_completes(doc, typed):
    # Completeness, cross-validated against the REAL matcher (not the resolver's own `_frontier`):
    # if appending a vocabulary token activates the command/option NAMED by it (result[token] is
    # truthy - it matched as a keyword, not as an arbitrary positional value that happens to look
    # like one), the resolver must offer it. This catches a `_frontier` that is too conservative or
    # diverges from `matches`.
    vocabulary = _vocabulary(doc)
    if vocabulary is None:
        return
    if "--" in typed:
        return  # after a POSIX separator the oracle cannot tell a keyword from a positional value
    options = parse_defaults(doc)
    parse_pattern(formal_usage(parse_section("usage:", doc)[0]), options)  # enrich with inline options
    try:
        parse_argv(Tokens(list(typed)), list(options))
    except (DocoptExit, DocoptLanguageError):
        return  # typed ends mid-option-argument -> the resolver completes a value, not a keyword
    offered = set(complete(doc, [*typed, ""]))
    for token in vocabulary:
        if token in typed:
            continue  # already supplied; result[token] would read as active from `typed`, not the append
        try:
            result = docopt(doc, [*typed, token], help=False, complete=False)
        except (DocoptExit, DocoptLanguageError):
            continue
        if result.get(token):
            assert token in offered, f"resolver missed {token!r} which completes {typed} in {doc!r}"
