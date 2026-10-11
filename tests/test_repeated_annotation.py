import pytest
from assertpy2 import assert_that

from docopt2 import check, docopt
from docopt2._parser import parse_defaults

_USAGE = "Usage: prog [--port=<n>] [--host=<h>]\n\nOptions:\n"


def _warned(options):
    """Each warning of the linter for these option lines: its summary, the text under its caret and its help."""
    doc = _USAGE + options
    said = []
    try:
        warnings = check(doc)
    except IndexError as leaked:
        return [f"leaked: {type(leaked).__name__}"]
    for warning in warnings:
        carets = [caret for snippet in warning.snippets for caret in snippet.carets]
        under = doc[carets[0].start : carets[0].end] if carets else None
        said.append((warning.summary, under, carets[0].label if carets else None, warning.help))
    return said


def _repeated(kind, option, under):
    summary = f"option `{option}` has more than one `[{kind}: ...]`"
    return summary, under, "one too many", f"keep a single `[{kind}: ...]` on `{option}`"


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ("  --port=<n>  Port [config: a.port] [config: b.port].", [_repeated("config", "--port", "[config: b.port]")]),
        ("  --port=<n>  Port [env: PORT] [env: OTHER].", [_repeated("env", "--port", "[env: OTHER]")]),
        ("  --port=<n>  Port [default: 1] [default: 2].", [_repeated("default", "--port", "[default: 2]")]),
        # the second one on a wrapped line of the same description
        (
            "  --port=<n>  Port [env: PORT]\n              and again [env: OTHER].",
            [_repeated("env", "--port", "[env: OTHER]")],
        ),
        # three: the caret is under the second
        (
            "  --port=<n>  Port [config: a] [config: b] [config: c].",
            [_repeated("config", "--port", "[config: b]")],
        ),
        # two kinds repeated on one option, and the option named is the one that carries them
        (
            "  --host=<h>  Host.\n  --port=<n>  Port [default: 1] [default: 2] [env: A] [env: B].",
            [_repeated("default", "--port", "[default: 2]"), _repeated("env", "--port", "[env: B]")],
        ),
    ],
)
def test_an_annotation_written_twice_on_one_option_is_flagged_at_the_second_one(options, expected):
    assert_that(_warned(options)).is_equal_to(expected)


@pytest.mark.parametrize(
    "options",
    [
        "  --port=<n>  Port [default: 1] [env: PORT] [config: a.port].",
        # the same annotation on two options is one each
        "  --port=<n>  Port [env: PORT].\n  --host=<h>  Host [env: HOST].",
        "  --port=<n>  Port [env: PORT].\n  --host=<h>  Host\n              on two lines [env: HOST].",
    ],
)
def test_one_annotation_of_each_kind_on_an_option_is_not_flagged(options):
    assert_that(_warned(options)).is_empty()


def test_a_description_does_not_run_on_into_the_next_options_section():
    # prose that opens a second section belongs to no option, which is how the parser reads it
    first = "  --port=<n>  Port [env: PORT]."
    second = (
        "\n\nMore options:\n"
        "              see also [env: OTHER]\n"
        "  --host=<h>  Host [env: HOST]\n"
        "              or [env: NAME]."
    )
    assert_that(_warned(first + second)).is_equal_to([_repeated("env", "--host", "[env: NAME]")])
    sources = {option.name: option.env for option in parse_defaults(_USAGE + first + second)}
    assert_that(sources).is_equal_to({"--port": "PORT", "--host": "HOST"})


def test_a_usage_too_malformed_to_parse_gets_no_warning_at_all():
    repeated = "\n\nOptions:\n  --port=<n>  Port [env: A] [env: B]."
    assert_that(check("Usage: prog [--port=<n>]" + repeated)).is_length(1)
    assert_that(check("Usage: prog [--port=<n>" + repeated)).is_empty()


def test_the_lint_says_what_the_parser_does_only_the_first_source_is_read(monkeypatch):
    monkeypatch.setenv("FIRST", "1")
    monkeypatch.setenv("SECOND", "2")
    doc = _USAGE + "  --port=<n>  Port [env: FIRST] [env: SECOND] [config: one] [config: two]."
    assert_that(docopt(doc, [])["--port"]).is_equal_to("1")
    monkeypatch.delenv("FIRST")
    assert_that(docopt(doc, [], config={"one": "11", "two": "22"})["--port"]).is_equal_to("11")
    assert_that(docopt(doc, [], config={"two": "22"})["--port"]).is_none()
