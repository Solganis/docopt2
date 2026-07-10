from assertpy2 import assert_that
from hypothesis import given
from hypothesis import strategies as st

from docopt2._diagnostics import Caret, Diagnostic, Snippet

_PREFIX = len("   |    ")  # gutter + indent shared by the source and caret rows
_SOURCE_CHARS = st.sampled_from(["\t", " ", "a", "b", "-", "<", ">", "|", "["])


@given(source=st.text(alphabet=_SOURCE_CHARS, max_size=30), data=st.data())
def test_caret_column_matches_the_span_start_display_position(source, data):
    # The caret must sit under its span even when the source line has tabs: the pad is the DISPLAY
    # width of the prefix (tabs expanded to the tab stop), not the raw character count.
    start = data.draw(st.integers(min_value=0, max_value=len(source)))
    end = data.draw(st.integers(min_value=start, max_value=len(source)))
    rendered = Diagnostic("summary", [Snippet(source, "src:", [Caret(start, end, "x")])]).render()
    caret_row = rendered.splitlines()[4]  # header, gutter, intro, source, caret
    assert_that(caret_row.index("^")).is_equal_to(_PREFIX + len(source[:start].expandtabs(8)))


@given(
    summary=st.text(max_size=20),
    sources=st.lists(st.text(alphabet=st.sampled_from(["\t", " ", "a", "\n", "-"]), max_size=20), max_size=3),
    note=st.one_of(st.none(), st.text(max_size=10)),
    help_text=st.one_of(st.none(), st.text(max_size=10)),
    data=st.data(),
)
def test_render_is_total_over_arbitrary_diagnostics(summary, sources, note, help_text, data):
    # Rendering must never raise, whatever the summary, sources (incl. newlines), carets, or note/help.
    snippets = []
    for source in sources:
        carets = []
        for _ in range(data.draw(st.integers(min_value=0, max_value=3))):
            start = data.draw(st.integers(min_value=0, max_value=len(source)))
            end = data.draw(st.integers(min_value=start, max_value=len(source)))
            carets.append(Caret(start, end, data.draw(st.text(max_size=5))))
        snippets.append(Snippet(source, "src:", carets))
    diagnostic = Diagnostic(summary, snippets, note, help_text)
    assert_that(diagnostic.render()).is_instance_of(str)
    assert_that(diagnostic.render(color=True)).is_instance_of(str)


def test_render_has_header_source_caret_note_and_help_aligned():
    diagnostic = Diagnostic(
        summary="something is wrong",
        snippets=[Snippet("usage: prog X", "in the usage:", [Caret(12, 13, "here")])],
        note="a note",
        help="a fix",
    )
    text = diagnostic.render()
    assert_that(text).contains("error: something is wrong")
    assert_that(text).contains("usage: prog X").contains("^").contains("here")
    assert_that(text).contains("note: a note").contains("help: a fix")
    # source and caret rows share the gutter, so the caret still aligns under 'X'
    source_row = next(row for row in text.splitlines() if "usage: prog X" in row)
    caret_row = next(row for row in text.splitlines() if "^" in row)
    assert_that(caret_row.index("^")).is_equal_to(source_row.index("X"))


def test_render_with_color_wraps_in_ansi_escapes():
    text = Diagnostic("boom", [Snippet("ab", "src:", [Caret(0, 1, "x")])]).render(color=True)
    assert_that(text).contains("\033[")


def test_warning_level_heads_with_warning_in_yellow():
    assert_that(Diagnostic("careful", level="warning").render()).starts_with("warning: careful")
    assert_that(Diagnostic("careful", level="warning").render(color=True)).contains("\033[33m")


def test_render_without_note_or_help_omits_those_lines():
    text = Diagnostic("bare", [Snippet("ab", "src:", [Caret(0, 1)])]).render()
    assert_that(text).does_not_contain("note:").does_not_contain("help:")


def test_render_a_caretless_snippet_shows_the_source_with_no_underline():
    text = Diagnostic("no carets", [Snippet("hello", "src:", [])]).render()
    assert_that(text).contains("hello").does_not_contain("^")


def test_render_shows_only_the_line_that_holds_the_caret():
    source = "line one\nline two <x> here\nline three"
    at = source.index("<x>")
    text = Diagnostic("multi", [Snippet(source, "src:", [Caret(at, at + 3, "this")])]).render()
    assert_that(text).contains("line two <x> here").does_not_contain("line one")
