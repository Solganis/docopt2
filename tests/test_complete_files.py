import dataclasses
import pathlib
import re
import sys
from typing import Annotated, List, Literal, Optional, TypedDict  # noqa: UP035 - `List` is a case below

import pytest
from assertpy2 import assert_that

from docopt2 import Dispatch, DocoptLanguageError, docopt, generate_completion
from docopt2._completion import reply_to_completion_request
from docopt2._typed import field_paths

_DOC = """Usage:
  filer [go] <file> [--out=<path>] [--mode=<m>] [--name=<n>]

Options:
  --out=<path>  Where to write.
  --mode=<m>    Mode.
  --name=<n>    A label.
"""
_OPTIONS = ["--mode", "--mode=json", "--mode=yaml", "--name", "--out"]
_SHELLS = ["bash", "zsh", "fish", "powershell", "nushell"]
_MARK = "\tfiles"


@dataclasses.dataclass
class _Filer:
    go: bool
    file: pathlib.Path
    out: pathlib.Path | None
    mode: Literal["json", "yaml"] | None
    name: str | None


def _reply(monkeypatch, words, doc=_DOC, schemas=(_Filer,), per_command=False, ask="2"):
    """The names a completion request for ``words`` is answered with, and whether the reply opens with the mark."""
    monkeypatch.setenv("_DOCOPT2_COMPLETE", ask)
    monkeypatch.setenv("_DOCOPT2_WORDS", "\n".join(words))
    reply = reply_to_completion_request(doc, schemas, per_command=per_command)
    lines = reply.split("\n") if reply else []
    marked = lines[:1] == [_MARK]
    return [line.split("\t")[0] for line in lines[marked:]], marked


def _printed(capsys, call):
    """What a call that answers a completion request prints, and the status it leaves with."""
    with pytest.raises(SystemExit) as left:
        call()
    return capsys.readouterr().out, left.value.code


@pytest.mark.parametrize(
    ("words", "names", "marked"),
    [
        ([], [*_OPTIONS, "go"], True),
        (["go"], _OPTIONS, True),
        (["--"], ["go"], True),
        (["notes.txt"], _OPTIONS, False),
        (["notes.txt", "--out"], [], True),
        (["--out"], [], True),
        (["notes.txt", "--mode"], ["json", "yaml"], False),
        (["notes.txt", "--name"], [], False),
        (["notes.txt", "extra"], [], False),
        (["--mode", "xml"], [], False),
        (["notes.txt", "--mode", "xml", "--out"], [], False),
        (["--bogus"], [], False),
    ],
)
def test_a_file_name_is_asked_for_where_a_path_field_comes_next_and_nowhere_else(monkeypatch, words, names, marked):
    assert_that(_reply(monkeypatch, words)).is_equal_to((names, marked))


@pytest.mark.parametrize("ask", ["1", "", "3", "yes", "22", " 2"])
def test_only_a_request_of_version_2_gets_the_mark(monkeypatch, ask):
    # a script from before the mark asks with 1: to it the mark would be a candidate with no name
    assert_that(_reply(monkeypatch, [], ask=ask)).is_equal_to(([*_OPTIONS, "go"], False))
    assert_that(_reply(monkeypatch, ["notes.txt", "--out"], ask=ask)).is_equal_to(([], False))


def test_the_mark_is_one_line_that_no_name_can_be(monkeypatch):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "2")
    monkeypatch.setenv("_DOCOPT2_WORDS", "go")
    lines = reply_to_completion_request(_DOC, (_Filer,)).split("\n")
    assert_that(lines[0]).is_equal_to("\tfiles")
    assert_that([line for line in lines[1:] if line.startswith("\t")]).is_empty()
    assert_that([line.split("\t")[0] for line in lines[1:]]).is_equal_to(_OPTIONS)


@pytest.mark.parametrize("words", [[], ["go"], ["notes.txt", "--out"], ["--out"]])
def test_without_a_schema_no_file_name_is_asked_for(monkeypatch, words):
    assert_that(_reply(monkeypatch, words, schemas=())[1]).is_false()


_TEXT_FIRST = [("name", str), ("file", pathlib.Path)]
_COMMAND_FIRST = [("read", bool), ("file", pathlib.Path)]


@pytest.mark.parametrize(
    ("usage", "fields", "words", "marked"),
    [
        # a text before the path: the file is asked for once the text is given, not before and not after
        ("Usage: p <name> <file>", _TEXT_FIRST, [], False),
        ("Usage: p <name> <file>", _TEXT_FIRST, ["x"], True),
        ("Usage: p <name> <file>", _TEXT_FIRST, ["x", "y"], False),
        # a command before the path
        ("Usage: p read <file>", _COMMAND_FIRST, [], False),
        ("Usage: p read <file>", _COMMAND_FIRST, ["read"], True),
        ("Usage: p read <file>", _COMMAND_FIRST, ["write"], False),
    ],
)
def test_the_path_is_asked_for_where_it_is_the_next_positional_of_a_line_that_can_still_be(
    monkeypatch, usage, fields, words, marked
):
    schema = dataclasses.make_dataclass("Schema", fields)
    assert_that(_reply(monkeypatch, words, usage, (schema,))[1]).is_equal_to(marked)


_EITHER = """Usage:
  p --as-text <name>
  p --as-file <path>
"""


@dataclasses.dataclass
class _Either:
    as_text: bool
    as_file: bool
    name: str | None
    path: pathlib.Path | None


@pytest.mark.parametrize(
    ("words", "marked"),
    [
        ([], True),
        (["--as-file"], True),
        (["--as-text"], False),
        (["--as-text", "x"], False),
        (["x", "--as-file"], False),
    ],
)
def test_an_option_that_rules_the_line_of_the_path_out_rules_its_file_names_out(monkeypatch, words, marked):
    assert_that(_reply(monkeypatch, words, _EITHER, (_Either,))[1]).is_equal_to(marked)


@pytest.mark.parametrize(
    "annotation",
    [
        pathlib.Path,
        pathlib.Path | None,
        Optional[pathlib.Path],  # noqa: UP045 - the spelling under test
        Annotated[pathlib.Path, "where"],
        Annotated[pathlib.Path | None, "where"],
        Annotated[pathlib.Path, "where"] | None,
        list[pathlib.Path],
        list[Annotated[pathlib.Path, "where"]],
        int | pathlib.Path,
        str | pathlib.Path,
    ],
)
def test_a_field_is_a_path_alone_annotated_in_a_union_or_as_the_element_of_a_list(monkeypatch, annotation):
    schema = dataclasses.make_dataclass("Schema", [("file", annotation)])
    assert_that(field_paths([schema])).is_equal_to({"file"})
    assert_that(_reply(monkeypatch, [], "Usage: filer <file>...", (schema,))[1]).is_true()


_NOT_PATHS = [str, str | None, int, Literal["a", "b"], list[str], pathlib.PurePath, object, list, Annotated[str, "p"]]
_NOT_PATHS.append(List)  # noqa: UP006 - a bare `List` has an origin and no element


@pytest.mark.parametrize("annotation", _NOT_PATHS)
def test_a_field_of_another_type_is_no_path(monkeypatch, annotation):
    schema = dataclasses.make_dataclass("Schema", [("file", annotation)])
    assert_that(field_paths([schema])).is_empty()
    assert_that(_reply(monkeypatch, [], "Usage: filer <file>...", (schema,))[1]).is_false()


def test_a_repeated_path_is_asked_for_again_after_each_one(monkeypatch):
    schema = dataclasses.make_dataclass("Schema", [("file", list[pathlib.Path])])
    typed = [[], ["a.txt"], ["a.txt", "b.txt"]]
    marks = [_reply(monkeypatch, words, "Usage: filer <file>...", (schema,))[1] for words in typed]
    assert_that(marks).is_equal_to([True, True, True])


def test_a_path_field_of_a_typed_dict_and_of_a_pydantic_model_is_read_too(monkeypatch):
    pydantic = pytest.importorskip("pydantic")

    class Typed(TypedDict):
        file: pathlib.Path

    class Model(pydantic.BaseModel):
        file: pathlib.Path

    for schema in (Typed, Model):
        assert_that(_reply(monkeypatch, [], "Usage: filer <file>", (schema,))[1]).is_true()


def test_a_pydantic_model_is_read_for_paths_as_it_writes_them_whatever_else_the_union_holds(monkeypatch):
    pydantic = pytest.importorskip("pydantic")

    class PathFirst(pydantic.BaseModel):
        file: pathlib.Path | Literal[1]

    class PathLast(pydantic.BaseModel):
        file: Literal[1] | pathlib.Path

    class NoPath(pydantic.BaseModel):
        file: Literal[1] | str

    # a closed set that is not all strings is handed to the value completion as `str`: the path must survive that
    marks = [_reply(monkeypatch, [], "Usage: filer <file>", (schema,))[1] for schema in (PathFirst, PathLast, NoPath)]
    assert_that(marks).is_equal_to([True, True, False])


def test_a_usage_that_does_not_parse_asks_for_nothing_and_raises_nothing(monkeypatch):
    assert_that(_reply(monkeypatch, [], "Usage: filer (<file>")).is_equal_to(([], False))


def test_a_schema_whose_annotations_do_not_resolve_asks_for_nothing_and_raises_nothing(monkeypatch):
    @dataclasses.dataclass
    class Unresolved:
        file: "NoSuchName"  # noqa: F821 - the name is to stay unresolved

    assert_that(_reply(monkeypatch, [], "Usage: filer <file>", (Unresolved,))).is_equal_to(([], False))


def test_a_path_is_not_looked_for_before_pathlib_is_imported(monkeypatch):
    names = [name for name in list(sys.modules) if name == "pathlib" or name.startswith("pathlib.")]
    for name in names:
        monkeypatch.delitem(sys.modules, name)
    assert_that(field_paths([_Filer])).is_empty()


_TABLE_DOC = """Usage:
  tool read <file> [--out=<path>]
  tool label <file> [--out=<path>]
"""


@dataclasses.dataclass
class _Read:
    file: pathlib.Path
    out: pathlib.Path | None


@dataclasses.dataclass
class _Label:
    file: str
    out: pathlib.Path | None


def test_handlers_ask_for_a_file_name_where_every_schema_that_declares_the_field_types_it_as_a_path(monkeypatch):
    both = (_Read, _Label)
    # `file` is a path for one handler and a text for the other, `out` a path for both
    assert_that(_reply(monkeypatch, ["read"], _TABLE_DOC, both, per_command=True)).is_equal_to((["--out"], False))
    assert_that(_reply(monkeypatch, ["read", "x", "--out"], _TABLE_DOC, both, per_command=True)[1]).is_true()
    assert_that(_reply(monkeypatch, ["read"], _TABLE_DOC, (_Read,), per_command=True)[1]).is_true()


def test_docopt_prints_the_mark_and_leaves_as_it_leaves_any_request(monkeypatch, capsys):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "2")
    monkeypatch.setenv("_DOCOPT2_WORDS", "go")
    printed, status = _printed(capsys, lambda: docopt(_DOC, [], schema=_Filer))
    assert_that(printed.split("\n")[0]).is_equal_to(_MARK)
    assert_that([line.split("\t")[0] for line in printed.splitlines()[1:]]).is_equal_to(_OPTIONS)
    # the status is no part of the answer: a program that fails with a status of its own asks for nothing
    assert_that(status).is_none()
    monkeypatch.setenv("_DOCOPT2_WORDS", "notes.txt")
    printed, status = _printed(capsys, lambda: docopt(_DOC, [], schema=_Filer))
    assert_that((printed.startswith("\t"), status)).is_equal_to((False, None))


def test_a_handler_table_prints_the_mark_too(monkeypatch, capsys):
    app = Dispatch(_TABLE_DOC)
    app.on("read", schema=_Read)(lambda arguments: arguments)
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "2")
    monkeypatch.setenv("_DOCOPT2_WORDS", "read")
    printed, status = _printed(capsys, lambda: app.run([]))
    assert_that((printed.split("\n")[0], status)).is_equal_to((_MARK, None))
    monkeypatch.setenv("_DOCOPT2_WORDS", "label\nx")
    printed, status = _printed(capsys, lambda: app.run([]))
    assert_that((printed.startswith("\t"), status)).is_equal_to((False, None))


@pytest.mark.parametrize(
    ("usage", "program"),
    [
        ("Usage: filer <file>", "filer"),
        ("usage:\n  naval ship <name>\n  naval mine", "naval"),
        ("Usage: ./tools/filer.py <file>", "filer.py"),
        ("Usage: a.b-c_d [options]", "a.b-c_d"),
    ],
)
def test_the_script_is_written_for_the_program_the_usage_names(monkeypatch, usage, program):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "bash")
    try:
        answered = reply_to_completion_request(usage)
    except ValueError as refused:
        answered = str(refused)
    assert_that(answered).is_equal_to(generate_completion(usage, program, "bash"))


@pytest.mark.parametrize("shell", _SHELLS)
def test_a_request_that_names_a_shell_is_answered_with_the_script_of_that_shell(monkeypatch, capsys, shell):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", shell)
    monkeypatch.setenv("_DOCOPT2_WORDS", "go")  # not read: the script is asked for, not the names after `go`
    printed, status = _printed(capsys, lambda: docopt(_DOC, ["an", "argv", "that", "is", "not", "read"], schema=_Filer))
    assert_that((printed, status)).is_equal_to((generate_completion(_DOC, "filer", shell) + "\n", None))


def test_a_handler_table_answers_a_request_for_a_script_too(monkeypatch, capsys):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "fish")
    printed, status = _printed(capsys, lambda: Dispatch(_TABLE_DOC).run([]))
    assert_that((printed, status)).is_equal_to((generate_completion(_TABLE_DOC, "tool", "fish") + "\n", None))


@pytest.mark.parametrize("usage", ["Usage:", "Usage: we$rd <file>"])
def test_a_usage_that_names_no_plain_command_is_refused_as_generate_completion_refuses_it(monkeypatch, usage):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "bash")
    assert_that(reply_to_completion_request).raises(ValueError).when_called_with(usage).contains(
        "must be a plain command name"
    )


@pytest.mark.parametrize("value", ["1", "", "tcsh", "BASH", "bash "])
def test_any_value_that_names_no_shell_asks_for_names(monkeypatch, value):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", value)
    monkeypatch.setenv("_DOCOPT2_WORDS", "notes.txt\n--mode")
    assert_that(reply_to_completion_request(_DOC, (_Filer,))).is_equal_to("json\t\nyaml\t")


def test_a_program_told_not_to_complete_runs_though_a_script_is_asked_for(monkeypatch):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "bash")
    assert_that(docopt(_DOC, ["notes.txt"], complete=False)["<file>"]).is_equal_to("notes.txt")


@pytest.mark.parametrize("shell", _SHELLS)
@pytest.mark.parametrize("usage", ["Usage: filer (<file>", "Usage: filer [<file>", "Usage: filer <file> )"])
def test_no_script_is_written_for_a_usage_that_a_tab_press_could_not_read(monkeypatch, shell, usage):
    try:
        written = generate_completion(usage, "filer", shell)
    except DocoptLanguageError as refused:
        written = type(refused).__name__
    assert_that(written).is_equal_to("DocoptLanguageError")
    monkeypatch.setenv("_DOCOPT2_COMPLETE", shell)
    try:
        asked = docopt(usage, [])
    except DocoptLanguageError as refused:
        asked = type(refused).__name__
    except SystemExit:
        asked = "a script was printed"
    assert_that(asked).is_equal_to("DocoptLanguageError")


@pytest.mark.parametrize("shell", _SHELLS)
def test_every_script_asks_with_version_2_reads_the_mark_and_holds_no_placeholder(shell):
    script = generate_completion(_DOC, "filer", shell)
    assert_that(re.findall(r"__[A-Z]+__", script)).is_empty()
    asks, reads = {
        "bash": ('reply="$(_DOCOPT2_COMPLETE=2 _DOCOPT2_WORDS=', "if [[ $reply == $'\\t'* ]]; then"),
        "zsh": ("$(_DOCOPT2_COMPLETE=2 _DOCOPT2_WORDS=", "if [[ $line == $'\\t'* ]]; then"),
        "fish": (
            "(env _DOCOPT2_COMPLETE=2 _DOCOPT2_WORDS=",
            "if string match -q -- \\t'*' $reply\n        for file in (__fish_complete_path",
        ),
        "powershell": ("$env:_DOCOPT2_COMPLETE = '2'", 'if ($_.StartsWith("`t")) {'),
        "nushell": ('{_DOCOPT2_COMPLETE: "2", _DOCOPT2_WORDS:', "| where {|line| $line | str starts-with (char tab)})"),
    }[shell]
    assert_that(script).contains(asks, reads)
