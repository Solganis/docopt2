from assertpy2 import assert_that
from pytest import raises

from docopt2 import Arguments, DocoptExit, DocoptLanguageError, Option, Tokens, docopt


def test_none_doc_raises_language_error():
    # docopt(__doc__) is the canonical call, and __doc__ is str | None; None must fail loudly.
    assert_that(docopt).raises(DocoptLanguageError).when_called_with(None, "")


def test_usage_section_with_no_program_raises_a_clear_error():
    # A `Usage:` header with an empty body names no program; fail loudly, not with an IndexError.
    with raises(DocoptLanguageError) as exc_info:
        docopt("Usage:", "")
    assert_that(str(exc_info.value)).contains("no program")


def test_deeply_nested_pattern_fails_cleanly_not_with_a_recursion_error():
    # An adversarially deep docstring must raise a DocoptLanguageError, not an uncaught RecursionError.
    deep = "usage: prog " + "[" * 600 + "a" + "]" * 600
    with raises(DocoptLanguageError) as exc_info:
        docopt(deep, "a")
    assert_that(str(exc_info.value)).contains("too deeply")


def test_deeply_repeated_argv_fails_cleanly_not_with_a_recursion_error():
    # A very long repetition match must exit cleanly (DocoptExit), not crash with a RecursionError.
    assert_that(docopt).raises(DocoptExit).when_called_with("usage: prog <x>...", ["a"] * 4000)


def test_alternation_heavy_usage_does_not_blow_up_during_fix():
    # Many `(a | b)` alternations used to expand into disjunctive normal form (2**k cases) inside
    # fix(), hanging on the docstring alone before any argv was matched. The fix phase is now
    # polynomial, so this returns promptly (the argv fails fast at the first unmatched command).
    groups = " ".join(f"(a{index} | b{index})" for index in range(30))
    doc = f"usage: prog {groups}"
    assert_that(docopt).raises(DocoptExit).when_called_with(doc, ["zzz"])


def test_single_space_before_option_description_gives_a_clear_error():
    # An option and its description must be separated by two spaces. A single space used to
    # surface downstream as a cryptic "unmatched '('"; now the error names the real cause and
    # draws a caret under the first word that was misread as an argument.
    doc = "Usage:\n  prog -k\n\nOptions:\n  -k some option description\n"
    with raises(DocoptLanguageError) as exc_info:
        docopt(doc, "-k")
    message = str(exc_info.value)
    assert_that(message).contains("two spaces")
    # the offending source line is reproduced with a caret under the stray word "some"
    assert_that(message).contains("-k some option description").contains("^")
    rows = message.splitlines()
    caret_row = next(row for row in rows if "^" in row)
    source_row = rows[rows.index(caret_row) - 1]
    assert_that(caret_row.index("^")).is_equal_to(source_row.index("some"))


def test_option_parse_error_without_a_source_degrades_to_plain_text():
    # Option.parse is public and may be called without the docstring; with no source to locate
    # the line in, the error keeps its text but carries no caret (graceful degradation).
    with raises(DocoptLanguageError) as exc_info:
        Option.parse("--bad thing here")
    assert_that(str(exc_info.value)).contains("two spaces").does_not_contain("^")


def test_option_parse_error_with_a_source_missing_the_line_degrades_to_plain_text():
    # A source that does not contain the option line cannot be pointed at; degrade to plain text.
    with raises(DocoptLanguageError) as exc_info:
        Option.parse("--bad thing here", "an unrelated docstring")
    assert_that(str(exc_info.value)).contains("two spaces").does_not_contain("^")


def test_unclosed_bracket_names_the_missing_closer_with_a_caret():
    with raises(DocoptLanguageError) as exc_info:
        docopt("usage: prog (-a -b", "")
    message = str(exc_info.value)
    assert_that(message).contains("unclosed").contains("`)`")
    # a caret points at the offending '(' under the reproduced source line
    assert_that(message).contains("usage: prog (-a -b").contains("^")


def test_stray_closing_bracket_is_reported_with_a_caret():
    with raises(DocoptLanguageError) as exc_info:
        docopt("usage: prog -a )", "")
    message = str(exc_info.value)
    assert_that(message).contains("unexpected closing").contains("`)`").contains("^")


def test_mismatched_bracket_pair_points_a_caret_at_both_brackets():
    with raises(DocoptLanguageError) as exc_info:
        docopt("usage: prog (a]", "")
    message = str(exc_info.value)
    assert_that(message).contains("mismatched").contains("`(`").contains("`]`")
    # a same-line two-span diagnostic: one caret under '(', a second under ']'
    source_row = next(row for row in message.splitlines() if "prog (a]" in row)
    caret_rows = [row for row in message.splitlines() if "^" in row]
    assert_that(caret_rows[0].index("^")).is_equal_to(source_row.index("("))
    assert_that(caret_rows[1].index("^")).is_equal_to(source_row.index("]"))


def test_tokens_move_on_empty_stream_returns_none():
    assert_that(Tokens([]).move()).is_none()


def test_missing_required_argument_names_what_the_usage_needs():
    with raises(DocoptExit) as exc_info:
        docopt("usage: prog <host> <port>", "h")
    assert_that(str(exc_info.value)).contains("usage requires").contains("<port>")


def test_extra_arguments_are_reported_with_an_argv_caret():
    with raises(DocoptExit) as exc_info:
        docopt("usage: prog <a>", "x y")
    message = str(exc_info.value)
    assert_that(message).contains("unexpected").contains("`y`")
    # the reproduced argv carries a caret under the first extra token
    source_row = next(row for row in message.splitlines() if row.endswith("x y"))
    caret_row = next(row for row in message.splitlines() if "^" in row)
    assert_that(caret_row.index("^")).is_equal_to(source_row.index("y"))


def test_mutually_exclusive_violation_cross_references_argv_and_usage():
    # `[--a | --b]` accepts at most one; giving both leaves --b with no slot. The diagnostic names it
    # (`--b`, not the internal boolean) and points a caret at it in BOTH the argv and the usage.
    doc = "Usage: prog [--a | --b]\n\nOptions:\n  --a  A.\n  --b  B.\n"
    with raises(DocoptExit) as exc_info:
        docopt(doc, "--a --b")
    message = str(exc_info.value)
    assert_that(message).contains("`--b`").does_not_contain("True")
    rows = message.splitlines()
    caret_indexes = [index for index, row in enumerate(rows) if "^" in row]
    assert_that(caret_indexes).is_length(2)  # one caret in the argv, one in the usage
    for index in caret_indexes:
        source_row, caret_row = rows[index - 1], rows[index]
        assert_that(caret_row.index("^")).is_equal_to(source_row.index("--b"))


_MULTILINE_DOC = "usage: prog ship <name>\n       prog rm <id>\n"


def test_multi_line_usage_carets_the_missing_element_of_the_closest_line():
    # `ship` matches the first line's command, so the diagnostic names its unmet requirement, not a
    # generic mismatch: the near-miss points a caret at `<name>` and says which line was closest.
    with raises(DocoptExit) as exc_info:
        docopt(_MULTILINE_DOC, "ship")
    message = str(exc_info.value)
    assert_that(message).contains("missing required").contains("<name>").contains("closest of 2 usage patterns")


def test_multi_line_usage_without_a_matching_subcommand_falls_back():
    # An unknown leading command is no evidence of intent, so no near-miss is claimed - just the usage.
    with raises(DocoptExit) as exc_info:
        docopt(_MULTILINE_DOC, "fly")
    assert_that(str(exc_info.value)).does_not_contain("closest of")


def test_multi_line_usage_without_a_positional_token_falls_back():
    # No positional token to match against any line's leading command.
    with raises(DocoptExit) as exc_info:
        docopt(_MULTILINE_DOC, "--nope")
    assert_that(str(exc_info.value)).does_not_contain("closest of")


def test_arguments_repr_is_sorted_and_dict_like():
    text = repr(docopt("usage: prog [-v] <name>", "-v alice"))
    assert_that(text).starts_with("{").ends_with("}")
    # Keys appear sorted (the '-' key before the '<' key).
    assert_that(text.index("'-v'")).is_less_than(text.index("'<name>'"))
    assert_that(repr(Arguments())).is_equal_to("{}")


def test_version_is_printed_and_exits():
    doc = "usage: prog --version\noptions: --version  Show version."
    assert_that(docopt).raises(SystemExit).when_called_with(doc, "--version", version="1.2.3")


def test_version_not_printed_when_flag_absent():
    doc = "usage: prog [--version]\noptions: --version  Show version."
    assert_that(docopt(doc, "", version="1.2.3")).is_equal_to({"--version": False})


def test_default_help_alias_overrides_help():
    # default_help wins over the positional help when provided.
    doc = "usage: prog [-h]\noptions: -h  Show help."
    assert_that(docopt(doc, "-h", help=True, default_help=False)).is_equal_to({"-h": True})


def test_fix_on_a_leaf_is_a_noop():
    assert_that(Option("-a").fix()).is_equal_to(Option("-a"))


def test_docopt_exit_carries_collected_and_left():
    with raises(DocoptExit) as exc_info:
        docopt("usage: prog <a>", "x y")
    # <a> is consumed; the extra "y" is reported as an unexpected argument.
    assert_that(str(exc_info.value)).contains("unexpected")
    assert_that(exc_info.value.left).is_not_empty()
    assert_that([pattern.value for pattern in exc_info.value.left]).contains("y")
    assert_that([pattern.name for pattern in exc_info.value.collected]).contains("<a>")


def test_unmatched_warning_shows_token_values_not_internal_repr():
    # The message must read the raw token, not leak the internal `Argument(...)` repr.
    with raises(DocoptExit) as exc_info:
        docopt("usage: prog <a>", "x y")
    message = str(exc_info.value)
    assert_that(message).contains("unexpected").contains("`y`")
    assert_that(message).does_not_contain("Argument(")


def test_unmatched_short_in_a_cluster_with_a_list_argv_still_reports_cleanly():
    # A short inside a cluster (`-b` in `-ab`) is not a literal substring of the joined argv, so the
    # argv caret is omitted rather than misplaced; the option is not in the usage, so it reads as a
    # plain "unexpected argument". Also exercises a list (non-string) argv on this path.
    with raises(DocoptExit) as exc_info:
        docopt("usage: prog -a", ["-ab"])
    assert_that(str(exc_info.value)).contains("unexpected").contains("`-b`")


def test_tuple_argv_is_accepted_like_a_list():
    # argv may be a tuple (e.g. splatted *args), handled the same as a list.
    assert_that(docopt("usage: prog <a> <b>", ("x", "y"))).is_equal_to({"<a>": "x", "<b>": "y"})


def test_docopt_exit_from_suggestion_carries_collected_and_left():
    # The suggestion branch raises before the "unmatched arguments" branch, so its
    # collected/left payload needs its own coverage: <file> is collected, and both the
    # mistyped option and the trailing "b" remain unmatched.
    doc = "usage: prog [--verbose] <file>\n\noptions:\n  --verbose  Be verbose.\n"
    with raises(DocoptExit) as exc_info:
        docopt(doc, ["--verbso", "a", "b"], suggest=True)
    assert_that([pattern.name for pattern in exc_info.value.collected]).contains("<file>")
    assert_that([pattern.value for pattern in exc_info.value.left]).contains("b")


def test_docopt_exit_empty_when_required_element_missing():
    # An empty argv against a required element leaves nothing collected or left over.
    with raises(DocoptExit) as exc_info:
        docopt("usage: prog <a>", "")
    assert_that(exc_info.value.left).is_empty()
    assert_that(exc_info.value.collected).is_empty()
