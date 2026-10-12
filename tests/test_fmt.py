import re

import pytest
from assertpy2 import assert_that
from hypothesis import given, settings
from hypothesis import strategies as st

from docopt2 import DocoptLanguageError, docopt, format_usage
from docopt2._parser import parse_defaults, section_line_numbers
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


def test_a_whitespace_only_spacer_line_keeps_the_options_after_it_in_the_section():
    # A spacer line of only spaces sits INSIDE the options section (it starts with a space). Emptying it
    # (rstrip) would end the section early, so `docopt(fmt(doc))` would no longer see `-b` - format_usage
    # promises to be semantics-preserving. It also broke idempotency: the second pass saw a shorter section.
    doc = "Usage:\n  prog [options]\n\nOptions:\n  -a  All.\n  \n  --bee=<n>  Bee.\n"
    once = format_usage(doc)
    assert_that(dict(docopt(once, ["--bee", "3"], help=False, complete=False))).is_equal_to(
        dict(docopt(doc, ["--bee", "3"], help=False, complete=False))
    )
    assert_that(format_usage(once)).is_equal_to(once)  # idempotent across the spacer


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
    """A usage doc whose Options lines have random misalignment, trailing spaces, and optional defaults.

    It also grows a PROSE section with `-`-led bullets. That is not decoration: the generator used to emit
    docs whose only indented block was `Options:`, which is exactly the condition under which the old
    formatter's assumption ("every `-`-led line is an option") happened to hold - so the layout-only
    property could not fail, and did not, while `fmt` was silently rewriting prose and deleting its commas.
    """
    count = draw(st.integers(min_value=1, max_value=4))
    usage = " ".join(f"[--opt{index}=<v{index}>]" for index in range(count))
    lines = [f"Usage: prog {usage} <x>", "", "Options:"]
    for index in range(count):
        gap = " " * draw(st.integers(min_value=2, max_value=6))  # docopt needs 2+ spaces to split spec/description
        trailing = " " * draw(st.integers(min_value=0, max_value=3))
        default = draw(st.none() | st.text(alphabet="abc123", min_size=1, max_size=4))
        default_part = "" if default is None else f" [default: {default}]"
        lines.append(f"  --opt{index}=<v{index}>{gap}Description {index}{default_part}.{trailing}")
    if draw(st.booleans()):  # a bullet list wrapped INSIDE an option's description - inside the section
        lines.append("              - fast,  quick, unsafe")
    if draw(st.booleans()):
        lines += ["", draw(st.sampled_from(["Notes:", "Examples:", "See also:"]))]
        for index in range(draw(st.integers(min_value=1, max_value=3))):
            lines.append(f"  - bullet {index}, with a comma  and a wide gap")
    return "\n".join(lines) + "\n"


_OPTION_LINE = re.compile(r"-\S")


def _not_option_lines(doc: str) -> list[str]:
    """Every line the parser does NOT read an option from - the lines fmt has no business rewriting.

    Being outside an `options:` section is not the test: a wrapped description holds prose bullets INSIDE
    the section, and `- fast, quick` is not an option - the parser wants a dash and a non-space.
    """
    covered = section_line_numbers("options:", doc)
    return [
        line.rstrip()
        for index, line in enumerate(doc.splitlines())
        if not (index in covered and _OPTION_LINE.match(line.lstrip()))
    ]


@given(doc=_option_doc())
@settings(max_examples=400, deadline=None)
def test_formatting_preserves_the_parse_over_arbitrary_layouts(doc):
    # the safety net over messy layouts: fmt is layout-only, so the parsed options never change, and it settles
    formatted = format_usage(doc)
    assert _signature(formatted) == _signature(doc)
    assert format_usage(formatted) == formatted  # idempotent
    # A line outside `options:` is prose: fmt may strip its trailing whitespace and nothing else.
    assert _not_option_lines(formatted) == _not_option_lines(doc)


def test_a_dash_led_line_outside_options_is_prose_and_is_left_alone():
    # A prose bullet used to go through the option-spec tidier, which turns `,` into a separator.
    doc = "Tool.\n\nNotes:\n  - alpha, beta  gamma\n\nUsage:\n  prog [-v]\n\nOptions:\n  -v,--verbose   Loud.\n"
    formatted = format_usage(doc)
    assert_that(formatted).contains("  - alpha, beta  gamma")  # prose, untouched, commas intact
    assert_that(formatted).contains("  -v --verbose  Loud.")  # the option, tidied and aligned to ITS width


def test_a_dash_space_bullet_inside_an_option_description_is_prose():
    # The parser reads an option line as `-\S` (a dash and a NON-space). A wrapped description may hold a
    # bullet list - `- fast, quick` - which is prose: restricting fmt to the `options:` section is not enough,
    # the line must also look like an option, or the spec tidier eats the bullet's commas.
    doc = (
        "Usage: prog [--mode=<m>]\n\nOptions:\n  --mode=<m>  Mode:\n"
        "              - fast,  quick, unsafe\n              [default: fast]\n"
    )
    formatted = format_usage(doc)
    assert_that(formatted).contains("- fast,  quick, unsafe")  # prose, untouched, commas intact
    assert_that(formatted).contains("--mode=<m>  Mode:")  # the option, tidied
    assert_that(format_usage(formatted)).is_equal_to(formatted)


def _reads_as(doc):
    """Whether ``docopt()`` takes ``doc`` as a usage: "a usage", or the first line of its refusal."""
    try:
        docopt(doc, [], help=False)
    except DocoptLanguageError as refused:
        return str(refused).splitlines()[0]
    except SystemExit:
        return "a usage"
    return "a usage"


_BREAKS_FOR_SPLITLINES = ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]


@pytest.mark.parametrize("character", _BREAKS_FOR_SPLITLINES, ids=[f"U+{ord(c):04X}" for c in _BREAKS_FOR_SPLITLINES])
def test_a_character_that_only_splitlines_takes_for_a_line_break_is_not_one_to_the_formatter(character):
    # the parser splits a doc at a newline alone. Split at these too, the second usage line lost its indent
    doc = f"Usage: prog (<x>\n     {character}<y>) [--opt=<v>]\n\nOptions:\n  --opt=<v>   Value [default: 7].\n"
    formatted = format_usage(doc)
    assert_that(formatted.count("\n")).is_equal_to(doc.count("\n"))
    assert_that(formatted).contains(f"     {character}<y>)", "--opt=<v>  Value [default: 7].")
    assert_that(_reads_as(formatted)).is_equal_to("a usage")
    assert_that(format_usage(formatted)).is_equal_to(formatted)


# Each made `format_usage` change what a usage means: whether it parses, which options it declares, or its own output.
_FOUND_BY_FUZZING = [
    "Usa\ne,1Usage: prog [options]ose  Loud.\n  --port=(<n>    \x1cPortLoudroptiontion)sUsage�: oO:",
    "Usage: prog [options] <x>\n\nOptions:\n  -v, --verbose  Loud.\n  --port<n>   \n Port [default: 80].\n",
    "Usage: prog [--count=<n>]...\n\nOptions:\r\n  --count=<n> N [default: 1 2].\n",
    "Usage: prog ship <name> move <x\x1c <y> [--speed=<k,n>]\n       prog -h | --help\n\n"
    "Options:\n  -h --help\n\x85 --speed=<kn> Options: Speed [default: 10].\n",
    "Usage:\n  app deploy <env>\n\nOptions:\n \x1c --format=<f>\\ Format [env: FMT].\n",
    "Usage:\n  a[e\x1cv: VAR]pp deploy <env> [--format=<f>]\n  app status\n\n"
    "Options:\n  \r--format=<f> Format [env: FMT] [config: ...out.format].\n",
    "Usage: prog ship <x> [--speeda<kn>]\n\nOptions:\x0c\n  -h --help\n  --speed=<kn>- Speed [default: 10].\n",
    "Usage: prog [--count=<n>]...\n\nOptiona:\n Options: --count=<n>  \n [default: 1 2].\n",
    "Usage: prog [options]\n\nOptions:\n  --port=<n>  \n \n Port [default: 80].\n",
    "Usage: prog [options] <x>\n\nOptions:\n  -, --verbose  Loud.\n  --port=<n>  Port [default: 80]\n",
    "Usage: prog [--count=<n>]...\n\nOptionsx:\n  --count=<options:\xa0n>  N [default: 1 2].\n--version",
    "Usage: prog [options] <x>\n\nOptios:\n  -voptions:, --verbose  Loud.\n  --port=<n>     Port [default: 80].\n",
    "Usage: prog [--count=<n>Options:usUsage: \n  -v,]. --",
    "Usage: prog [options] <x>\n\nOptions:\n  -v, -arguments:-verbose  Loud.\n"
    "  --port=<n>    \n Parguments:ort [default: 80].\n",
]


@pytest.mark.parametrize("doc", _FOUND_BY_FUZZING)
def test_a_usage_the_fuzzing_found_means_the_same_once_formatted_and_is_formatted_once(doc):
    formatted = format_usage(doc)
    assert_that(_reads_as(formatted)).is_equal_to(_reads_as(doc))
    if _reads_as(doc) == "a usage":
        assert_that(_signature(formatted)).is_equal_to(_signature(doc))
    assert_that(format_usage(formatted)).is_equal_to(formatted)


def test_a_doc_with_windows_line_ends_is_formatted_as_the_same_doc_with_unix_ones():
    doc = "Usage: prog [options]\n\nOptions:\n  -v, --verbose   Loud.\n  --opt=<v>   Value.  \n\n  -q  Quiet.\n"
    assert_that(format_usage(doc.replace("\n", "\r\n"))).is_equal_to(format_usage(doc))
    assert_that(format_usage(doc)).contains("  -v --verbose  Loud.\n  --opt=<v>     Value.\n")


def test_two_blanks_that_end_an_option_line_stay_where_the_description_starts_on_the_next_line():
    # they end the spec: stripped, the description joins it and its first word is read as an argument name
    doc = "Usage: prog [options]\n\nOptions:\n  --port=<n>   \n Port [default: 80].\n  -v   Loud.\n  -q  \n"
    formatted = format_usage(doc)
    # the two blanks kept are no part of the column: `-v` is padded to the ten of `--port=<n>`
    assert_that(formatted).is_equal_to(
        "Usage: prog [options]\n\nOptions:\n  --port=<n>  \n Port [default: 80].\n  -v          Loud.\n  -q\n"
    )
    assert_that(_signature(formatted)).is_equal_to(_signature(doc))
    assert_that(format_usage(formatted)).is_equal_to(formatted)


def test_two_blanks_before_a_blank_line_and_another_option_end_nothing_and_go():
    doc = "Usage: prog [options]\n\nOptions:\n  --port=<n>   \n \n  -v  Loud.\n"
    assert_that(format_usage(doc)).is_equal_to(
        "Usage: prog [options]\n\nOptions:\n  --port=<n>\n \n  -v          Loud.\n"
    )


def test_a_line_led_by_a_blank_the_parser_does_not_indent_by_is_a_description_and_not_the_next_option():
    doc = "Usage: prog [options]\n\nOptions:\n  --port=<n>   \n \x0c-x text.\n"
    formatted = format_usage(doc)
    assert_that(formatted).is_equal_to("Usage: prog [options]\n\nOptions:\n  --port=<n>  \n \x0c-x text.\n")
    assert_that(_signature(formatted)).is_equal_to(_signature(doc))
