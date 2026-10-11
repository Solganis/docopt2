import subprocess
import sys

import pytest
from assertpy2 import assert_that

from docopt2 import docopt
from docopt2._diagnostics import Caret, Diagnostic, Snippet, _columns

_SPEED = "Usage: prog <ファイル> --速度=<kn>\n\nOptions:\n  --速度=<kn>  Speed."


def _drawn(doc, argv, source):
    """The source line under ``source`` and the caret line under it, as a refusal prints them."""
    try:
        return [f"accepted: {docopt(doc, argv, complete=False)}"]
    except SystemExit as refusal:
        lines = str(refusal).splitlines()
    at = lines.index(f"   |  {source}")
    return lines[at + 1 : at + 3]


@pytest.mark.parametrize(
    ("argv", "shown", "marks"),
    [
        # a wide character takes two columns, before the caret and under it
        (["日本語", "extra"], "日本語 extra", "       ^^^^^"),
        (["x", "日本語"], "x 日本語", "  ^^^^^^"),
        (["a\U0001f642b", "extra"], "a\U0001f642b extra", "     ^^^^^"),
        # a combining mark and a zero-width joiner take none
        (["e\u0301te\u0301", "extra"], "e\u0301te\u0301 extra", "    ^^^^^"),
        (["a\u200db", "extra"], "a\u200db extra", "   ^^^^^"),
        # a combining mark takes none even where the tables call it wide: U+3099 is both
        (["\u304b\u3099", "extra"], "\u304b\u3099 extra", "   ^^^^^"),
        # a character outside ASCII that is one column wide, and none at all
        (["über", "extra"], "über extra", "     ^^^^^"),
        (["plain", "extra"], "plain extra", "      ^^^^^"),
    ],
)
def test_a_caret_stands_at_the_column_the_terminal_draws_the_token_at(argv, shown, marks):
    drawn = _drawn("Usage: prog <a>", argv, "in the arguments:")
    assert_that(drawn).is_equal_to([f"   |    {shown}", f"   |    {marks} not allowed here"])


def test_a_caret_in_a_usage_written_with_wide_characters_is_aligned_too():
    drawn = _drawn(_SPEED, ["x", "--速度=3", "--速度=4"], "in the usage:")
    assert_that(drawn).is_equal_to(
        ["   |    Usage: prog <ファイル> --速度=<kn>", "   |                           ^^^^^^^^^^^ declared here"]
    )


def test_a_caret_on_a_later_usage_line_counts_the_columns_of_that_line_only():
    doc = "Usage:\n  prog 追加 <名前>\n  prog 削除 <名前> [--強制]\n\nOptions:\n  --強制  Force."
    drawn = _drawn(doc, ["削除", "x", "--強制", "--強制"], "in the usage:")
    assert_that(drawn).is_equal_to(
        ["   |      prog 削除 <名前> [--強制]", "   |                        ^^^^^^ declared here"]
    )


@pytest.mark.parametrize(
    ("text", "columns"),
    [
        ("", 0),
        ("abc", 3),
        ("日本", 4),
        ("\uff46\uff55\uff4c\uff4c", 8),
        ("e\u0301", 1),
        ("a\u200db", 2),
        ("\u20dd", 0),
        ("über", 4),
        ("\u304b\u3099", 2),
        # counted character by character, as wcwidth does: an emoji sequence is not read as one glyph
        ("\U0001f469\u200d\U0001f4bb", 4),
        ("αβγ", 3),
    ],
)
def test_the_columns_of_a_text_count_two_for_a_wide_character_and_none_for_one_that_takes_no_room(text, columns):
    assert_that(_columns(text)).is_equal_to(columns)


def test_a_span_with_a_tab_inside_is_underlined_as_wide_as_the_tab_is_drawn():
    snippet = Snippet("a\tb c", "in the arguments:", [Caret(0, 3, "here"), Caret(4, 5, "there")])
    rendered = Diagnostic(summary="s", snippets=[snippet]).render()
    assert_that(rendered.splitlines()[3:6]).is_equal_to(
        ["   |    a       b c", "   |    ^^^^^^^^^ here", "   |              ^ there"]
    )


def test_a_zero_width_span_still_draws_one_caret_whatever_stands_before_it():
    rendered = Diagnostic(summary="s", snippets=[Snippet("日本", "in the arguments:", [Caret(2, 2, "here")])]).render()
    assert_that(rendered.splitlines()[3:5]).is_equal_to(["   |    日本", "   |        ^ here"])


_REFUSE = """
import sys
import docopt2
try:
    docopt2.docopt("Usage: prog <a>", [{first!r}, "extra"], complete=False)
except SystemExit:
    print(chr(10).join(sys.modules))
"""


def _modules_loaded_by_refusing(first):
    script = _REFUSE.format(first=first)
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    return set(completed.stdout.split())


def test_only_a_caret_line_with_a_character_outside_ascii_imports_the_width_tables():
    assert_that(_modules_loaded_by_refusing("x")).contains("docopt2").does_not_contain("unicodedata")
    assert_that(_modules_loaded_by_refusing("\u65e5")).contains("docopt2", "unicodedata")
