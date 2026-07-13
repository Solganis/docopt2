import ast
from pathlib import Path

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


def test_check_returns_no_warnings_on_a_deeply_nested_usage():
    # check() promises no warnings for an unparseable doc; a pathologically deep grammar raises
    # RecursionError inside the parser, which must be swallowed like a DocoptLanguageError.
    deep = "Usage: prog " + "( " * 2000 + "x " + ") " * 2000
    assert_that(check(deep)).is_equal_to([])


def test_check_flags_an_unused_option_declared_after_a_wrapped_description():
    # A continuation line (indented, not starting with `-`) must be skipped, not end the scan: an option
    # declared after another option's wrapped description is still linted.
    doc = "Usage: prog [--foo] <x>\n\nOptions:\n  --foo  Enable foo,\n    continued here.\n  --bar  Unused.\n"
    assert_that([warning.summary for warning in check(doc)]).contains("option `--bar` is declared but never used")


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


# Both rules below were dead for any doc with more than one usage line - the case they exist for.
def test_a_dead_default_is_caught_when_every_usage_line_requires_the_option():
    doc = "Usage:\n  prog a --port=<n>\n  prog b --port=<n>\n\nOptions:\n  --port=<n>  Port [default: 8].\n"
    assert_that([d.summary for d in check(doc)]).contains("dead default on `--port`, which the usage always requires")


def test_a_default_is_not_dead_when_only_one_usage_line_requires_the_option():
    # The other half of the rule: an option required by one line and absent from another can still default.
    doc = "Usage:\n  prog a --port=<n>\n  prog b\n\nOptions:\n  --port=<n>  Port [default: 8].\n"
    assert_that(check(doc)).is_empty()


def test_a_dead_argument_default_is_caught_across_usage_lines():
    doc = "Usage:\n  prog a <host>\n  prog b <host>\n\nArguments:\n  <host>  Host [default: local].\n"
    assert_that([d.summary for d in check(doc)]).contains("dead default on `<host>`, which the usage always requires")


def test_a_redundant_alternative_is_caught_inside_a_usage_line():
    # A multi-line usage is itself the outermost Either, so an `(add | add)` inside a line went unseen.
    for doc in ("Usage:\n  prog (add | add)\n  prog rm\n", "Usage: prog ((add | add) | rm)"):
        summaries = [d.summary for d in check(doc)]
        assert_that(summaries).described_as(doc).contains("redundant alternative: this branch repeats an earlier one")


def test_distinct_usage_lines_are_not_redundant_alternatives():
    assert_that(check("Usage:\n  prog add\n  prog rm\n")).is_empty()


def test_check_never_raises_on_a_doc_with_no_usage_section():
    # `check` is documented never to raise: a usage too malformed to parse is the parser's error to report,
    # not the linter's. `single_usage_section` throws when there is no `Usage:` at all, so it must sit
    # inside the guard - a refactor that lifted it out slipped past the whole suite.
    assert_that(check("No usage here at all.")).is_empty()
    assert_that(check("")).is_empty()
    assert_that(check("Options:\n  -v  Verbose.\n")).is_empty()


def test_the_canonical_naval_fate_example_is_warning_free():
    # `-h | --help` is one option under its two spellings, so it parses to two identical leaves - and the
    # redundant-alternative rule saw a duplicate in the most famous usage message docopt has. It is an
    # idiom, not a slip: a linter that fires on the canonical example is a linter people switch off.
    doc = Path(__file__).parent.parent.joinpath("examples/naval_fate.py").read_text(encoding="utf-8")
    assert_that(check(ast.get_docstring(ast.parse(doc)))).is_empty()


def test_the_same_option_written_twice_is_still_redundant():
    # The other side of it: `(-h | -h)` is the same spelling twice, which is the slip the rule exists for.
    assert_that(_summaries("Usage: prog (-h | -h)\n\nOptions:\n  -h --help  H.\n")[0]).contains("redundant")
