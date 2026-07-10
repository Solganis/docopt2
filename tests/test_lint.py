from assertpy2 import assert_that
from hypothesis import given

from _strategies import doc_strategy
from docopt2 import check


@given(doc=doc_strategy)
def test_check_is_total_and_renderable_on_any_grammar(doc):
    # A lint must never crash: check() must return (not raise) on any grammar, and every warning it
    # yields must render. Fuzzing this caught a `(X Y)...` false positive the example tests missed.
    for warning in check(doc):
        warning.render()


def _summaries(doc: str) -> list[str]:
    return [warning.summary for warning in check(doc)]


def test_unused_option_is_flagged_with_a_caret_under_its_declaration():
    doc = "Usage: prog <file>\n\nOptions:\n  --verbose  Be verbose.\n"
    warnings = check(doc)
    assert_that(warnings).is_length(1)
    assert_that(warnings[0].summary).contains("`--verbose`").contains("never used")
    assert_that(warnings[0].level).is_equal_to("warning")
    rows = warnings[0].render().splitlines()
    caret_row = next(row for row in rows if "^" in row)
    source_row = rows[rows.index(caret_row) - 1]
    assert_that(caret_row.index("^")).is_equal_to(source_row.index("--verbose"))


def test_dead_default_on_an_always_required_option():
    doc = "Usage: prog --speed=<kn>\n\nOptions:\n  --speed=<kn>  Speed [default: 10].\n"
    assert_that(_summaries(doc)).is_length(1)
    assert_that(_summaries(doc)[0]).contains("dead default").contains("`--speed`")


def test_dead_default_on_an_always_required_positional():
    doc = "Usage: prog <host>\n\nArguments:\n  <host>  Host [default: localhost].\n"
    assert_that(_summaries(doc)).is_length(1)
    assert_that(_summaries(doc)[0]).contains("dead default").contains("`<host>`")


def test_empty_options_shortcut_bracketed_points_a_caret_at_it():
    doc = "Usage: prog [options] <file>\n"
    warnings = check(doc)
    assert_that(warnings).is_length(1)
    assert_that(warnings[0].summary).contains("`[options]`").contains("nothing")
    assert_that(warnings[0].render()).contains("^")


def test_empty_options_shortcut_bare_degrades_to_no_caret():
    # `options` without brackets is still the shortcut, but cannot be located for a caret, so the
    # warning degrades to summary + help (exercises the span-less rendering path).
    warnings = check("Usage: prog options <file>\n")
    assert_that(warnings).is_length(1)
    assert_that(warnings[0].render()).does_not_contain("^")


def test_default_on_an_optional_positional_is_not_dead():
    # <host> is optional, so its default legitimately applies - no warning (the default is reachable).
    doc = "Usage: prog [<host>]\n\nArguments:\n  <host>  Host [default: localhost].\n"
    assert_that(check(doc)).is_empty()


def test_two_variadic_positionals_are_flagged_as_ambiguous():
    assert_that(_summaries("usage: prog <a>... <b>...")[0]).contains("ambiguous").contains("variadic")


def test_a_variadic_followed_by_a_fixed_positional_is_fine():
    # `<src>... <dest>` is well-defined (the backtracking matcher gives the last token to <dest>).
    assert_that(check("usage: prog <src>... <dest>")).is_empty()


def test_a_repeated_positional_group_is_not_flagged():
    # `(<a> <b>)...` pairs its positionals deterministically (a b a b ...) - one unit, not two
    # competing variadics with a free boundary; flagging it would be a false positive.
    assert_that(check("usage: prog (<a> <b>)...")).is_empty()


def test_a_repeated_flag_is_not_a_variadic_positional():
    # `[-v]...` repeats a flag, not a positional, so it is not a variadic positional at all.
    assert_that(check("usage: prog [-v]... <file>")).is_empty()


def test_variadics_in_separate_alternatives_are_not_ambiguous():
    assert_that(check("usage: prog (<a>... | <b>...)")).is_empty()


def test_duplicate_mutually_exclusive_alternative_is_flagged():
    assert_that(_summaries("usage: prog (--a | --a)")[0]).contains("redundant")


def test_distinct_alternatives_are_not_redundant():
    assert_that(check("usage: prog (--a | --b)")).is_empty()


def test_clean_grammar_produces_no_warnings():
    doc = "Usage: prog [--speed=<kn>] <file>\n\nOptions:\n  --speed=<kn>  Speed [default: 10].\n"
    assert_that(check(doc)).is_empty()


def test_unparseable_usage_yields_no_warnings():
    # A malformed usage surfaces its error at parse time; the linter stays quiet rather than crash.
    assert_that(check("usage: prog (a]")).is_empty()


def test_malformed_option_line_is_skipped_not_crashed():
    doc = "Usage: prog <file>\n\nOptions:\n  -k some description here\n"
    assert_that(check(doc)).is_empty()


def test_multiline_option_description_continuation_is_ignored():
    doc = "Usage: prog [--verbose]\n\nOptions:\n  --verbose  Be verbose. It is\n             a long description.\n"
    assert_that(check(doc)).is_empty()


def test_corpus_of_valid_grammars_is_warning_free():
    # No-false-positives net: real, well-formed usage messages must produce zero warnings.
    naval = (
        "Naval Fate.\n\nUsage:\n  naval ship new <name>...\n  naval ship <name> move <x> <y> [--speed=<kn>]\n"
        "  naval mine (set|remove) <x> <y> [--moored|--drifting]\n  naval --help\n\n"
        "Options:\n  -h --help     Show screen.\n  --speed=<kn>  Speed [default: 10].\n"
        "  --moored      Moored.\n  --drifting    Drifting.\n"
    )
    git = "usage: git [--version] [--help] <command> [<args>...]\n\nOptions:\n  --version  V.\n  --help     H.\n"
    for doc in (naval, git):
        assert_that(check(doc)).described_as(doc).is_empty()
