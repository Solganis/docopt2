import io
import sys

import pytest
from assertpy2 import assert_that
from hypothesis import given
from hypothesis import strategies as st

from docopt2 import DocoptExit, DocoptLanguageError, docopt
from docopt2._diagnostics import Caret, Diagnostic, Snippet, use_color

_PREFIX = len("   |    ")  # gutter + indent shared by the source and caret rows
_SOURCE_CHARS = st.sampled_from(["\t", " ", "a", "b", "-", "<", ">", "|", "["])


def _underlines(rendered: str) -> list[tuple[str, str]]:
    """Each caret row of a rendered diagnostic, paired with the source row it is drawn under.

    A caret row is one whose body begins (after the pad) with `^`; the source alphabet never does.
    """
    pairs: list[tuple[str, str]] = []
    source_row = ""
    for row in rendered.splitlines():
        if not row.startswith("   |    "):
            continue
        body = row[_PREFIX:]
        if body.lstrip().startswith("^"):
            pairs.append((source_row, body))
        else:
            source_row = body
    return pairs


def test_use_color_follows_the_tty_and_no_color(monkeypatch):
    # ANSI only to a real terminal, and never when NO_COLOR is set (an opt-out even on a tty).
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    assert_that(use_color(sys.stderr)).is_true()
    monkeypatch.setenv("NO_COLOR", "1")
    assert_that(use_color(sys.stderr)).is_false()
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    assert_that(use_color(sys.stderr)).is_false()


def test_use_color_survives_a_stream_that_cannot_answer(monkeypatch):
    # pythonw.exe and a windowed build hand a GUI program `sys.stderr is None`, and a closed stream
    # raises on isatty(). Either one used to crash inside DocoptExit's own constructor.
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert_that(use_color(None)).is_false()
    closed = io.StringIO()
    closed.close()
    assert_that(use_color(closed)).is_false()


def test_a_gui_program_with_no_stderr_still_raises_docopt_exit(monkeypatch):
    # The whole error path, not just use_color: under pythonw a bad argv must still be a DocoptExit.
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys, "stderr", None)
    with pytest.raises(DocoptExit):
        docopt("Usage: prog <x>", [])


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
    # Totality alone let a real defect through: this generator has been drawing multi-line sources all
    # along, and only ever asserted "did not raise". Every caret must also FIT the line it is drawn under.
    for source_row, underline in _underlines(diagnostic.render()):
        assert_that(underline.index("^") + underline.count("^")).is_less_than_or_equal_to(len(source_row) + 1)


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


def test_two_carets_on_different_lines_are_each_drawn_under_their_own_line():
    # A snippet is not always one line. Drawing both carets under the first one pointed at columns that
    # line does not have - and silently claimed the second token was somewhere it is not.
    source = "prog (add\nprog rm]"
    opener, closer = source.index("("), source.index("]")
    carets = [Caret(opener, opener + 1, "opens here"), Caret(closer, closer + 1, "cannot close it")]
    rows = Diagnostic("mismatched", [Snippet(source, "in the usage:", carets)]).render().splitlines()
    bodies = [row[_PREFIX:] for row in rows if row.startswith("   |    ")]
    assert_that(bodies).is_equal_to(
        [
            "prog (add",
            "     ^ opens here",
            "prog rm]",
            "       ^ cannot close it",
        ]
    )


def test_a_caret_running_past_its_line_is_clamped_to_it():
    # A group's span covers everything between `(` and `)`, which may be on the next line; the underline
    # used to run off the end of the rendered line by the length of the rest of the span.
    source = "prog run (--from=<a>\n          --to=<b>)"
    start, end = source.index("("), source.index(")") + 1
    text = Diagnostic("missing", [Snippet(source, "in the usage:", [Caret(start, end, "required here")])]).render()
    (source_row, underline), *rest = _underlines(text)
    assert_that(rest).is_empty()
    assert_that(underline.index("^") + underline.count("^")).is_less_than_or_equal_to(len(source_row))


def test_a_failed_parse_carries_the_usage_message():
    # docopt's oldest contract: what a user sees on a bad argv ENDS with the usage. Nothing asserted it,
    # so dropping `usage=` from the exit would have printed a bare diagnostic and left the user guessing.
    doc = "Usage:\n  prog ship <name> move <x> <y>\n"
    with pytest.raises(DocoptExit) as caught:
        docopt(doc, ["ship"])
    assert_that(str(caught.value)).ends_with("Usage:\n  prog ship <name> move <x> <y>")


def test_an_option_error_in_the_usage_carets_the_option():
    # Tokens.fail is the shared error path for both the usage and the argv; blanking the span it points
    # at left every message it raises caretless, and no test noticed.
    doc = "Usage: prog --speed\n\nOptions:\n  --speed=<kn>  Speed.\n"
    with pytest.raises(DocoptLanguageError) as caught:
        docopt(doc, [])
    source_row, underline = _underlines(str(caught.value))[0]
    assert_that(str(caught.value)).contains("`--speed` requires an argument")
    assert_that(source_row[underline.index("^") : underline.index("^") + underline.count("^")]).is_equal_to("--speed")


def test_a_bracket_mismatch_across_two_usage_lines_carets_both():
    # The end-to-end shape of the same defect, through the real parser.
    doc = "Usage:\n  prog (add\n  prog rm]\n"
    with pytest.raises(DocoptLanguageError) as caught:
        docopt(doc, ["add"])
    for source_row, underline in _underlines(str(caught.value)):
        assert_that(underline.index("^")).is_less_than(len(source_row))
