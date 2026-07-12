from assertpy2 import assert_that
from hypothesis import given, settings
from hypothesis import strategies as st

from docopt2 import docopt, format_usage
from docopt2._parser import parse_defaults
from docopt2.hypothesis import argv_strategy


def _signature(doc):
    """The full parsed option set (incl. env/config, which Option.__eq__ ignores), for a strict compare."""
    return [(o.short, o.long, o.argcount, o.value, o.env, o.config_key) for o in parse_defaults(doc)]


def test_aligns_every_option_description_into_one_column():
    doc = "Usage: p\n\nOptions:\n  --port=<n>   Port.\n  --host=<h>  Host.\n"
    assert_that(format_usage(doc)).contains("  --port=<n>  Port.").contains("  --host=<h>  Host.")


def test_normalizes_comma_separators_and_strips_trailing_whitespace():
    doc = "Usage: p\n\nOptions:\n  -v, --verbose      Loud.   \n"
    assert_that(format_usage(doc)).is_equal_to("Usage: p\n\nOptions:\n  -v --verbose  Loud.\n")


def test_is_idempotent():
    doc = "Usage: p\n\nOptions:\n  --port=<n>   Port.\n  --host=<h>  Host.\n"
    once = format_usage(doc)
    assert_that(format_usage(once)).is_equal_to(once)


def test_a_usage_without_options_is_only_whitespace_tidied():
    assert_that(format_usage("Usage: prog <a> <b>   \n")).is_equal_to("Usage: prog <a> <b>\n")


def test_a_doc_without_a_trailing_newline_gets_no_trailing_junk():
    # format_usage mirrors the doc's final-newline state: none in, none out - and never appends stray text.
    assert_that(format_usage("Usage: p\n\nOptions:\n  -v, --verbose  Loud.")).is_equal_to(
        "Usage: p\n\nOptions:\n  -v --verbose  Loud."
    )


def test_an_option_line_without_a_description_is_left_bare():
    assert_that(format_usage("Usage: p\n\nOptions:\n  --flag\n")).is_equal_to("Usage: p\n\nOptions:\n  --flag\n")


_OPTION_DOCS = [
    "Usage: prog serve <root> [--port=<n>] [-v]\n\n"
    "Options:\n  --port=<n>  Port [default: 80] [env: PORT].\n  -v  Verbose.\n",
    "Usage:\n  prog add <x>\n  prog rm <x> [--force]\n\nOptions:\n  --force  Force.\n",
    "Usage: prog [--name=<n>] [--tag=<t>]...\n\nOptions:\n  --name=<n>  Name.\n  --tag=<t>  Tag.\n",
]


@given(data=st.data())
@settings(max_examples=100, deadline=None)
def test_formatting_is_layout_only_and_preserves_every_parse(data):
    doc = data.draw(st.sampled_from(_OPTION_DOCS))
    formatted = format_usage(doc)
    assert _signature(formatted) == _signature(doc)  # options unchanged, incl. defaults/env/config
    argv = data.draw(argv_strategy(doc))
    assert docopt(doc, argv, help=False, complete=False) == docopt(formatted, argv, help=False, complete=False)


@st.composite
def _option_doc(draw: st.DrawFn) -> str:
    """A usage doc whose Options lines have random misalignment, trailing spaces, and optional defaults."""
    count = draw(st.integers(min_value=1, max_value=4))
    usage = " ".join(f"[--opt{index}=<v{index}>]" for index in range(count))
    lines = [f"Usage: prog {usage} <x>", "", "Options:"]
    for index in range(count):
        gap = " " * draw(st.integers(min_value=2, max_value=6))  # docopt needs 2+ spaces to split spec/description
        trailing = " " * draw(st.integers(min_value=0, max_value=3))
        default = draw(st.none() | st.text(alphabet="abc123", min_size=1, max_size=4))
        default_part = "" if default is None else f" [default: {default}]"
        lines.append(f"  --opt{index}=<v{index}>{gap}Description {index}{default_part}.{trailing}")
    return "\n".join(lines) + "\n"


@given(doc=_option_doc())
@settings(max_examples=400, deadline=None)
def test_formatting_preserves_the_parse_over_arbitrary_layouts(doc):
    # the safety net over messy layouts: fmt is layout-only, so the parsed options never change, and it settles
    formatted = format_usage(doc)
    assert _signature(formatted) == _signature(doc)
    assert format_usage(formatted) == formatted  # idempotent
