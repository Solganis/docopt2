import io

from assertpy2 import assert_that
from pytest import raises

from docopt2.__main__ import main


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_stub_reads_a_module_docstring_without_importing_the_file(tmp_path, capsys):
    source = _write(tmp_path, "cli.py", '"""Usage: prog <host> <port>"""\n\nraise SystemExit("must not run")\n')
    exit_code = main(["stub", source])
    captured = capsys.readouterr()
    assert_that(exit_code).is_equal_to(0)
    assert_that(captured.out).contains("class Args:").contains("host: str").contains("port: str")


def test_stub_reads_a_python_file_that_starts_with_a_utf8_bom(tmp_path, capsys):
    # Windows editors prepend a UTF-8 BOM; Python runs such a file fine, but the CLI read it as plain
    # utf-8 and fed the leading U+FEFF to ast.parse, which rejected it. utf-8-sig strips the BOM.
    path = tmp_path / "bom.py"
    path.write_text('"""Usage: prog <host>"""\n', encoding="utf-8-sig")
    exit_code = main(["stub", str(path)])
    captured = capsys.readouterr()
    assert_that(exit_code).is_equal_to(0)
    assert_that(captured.out).contains("class Args:").contains("host: str")


def test_stub_reads_raw_usage_from_a_non_python_file(tmp_path, capsys):
    source = _write(tmp_path, "usage.txt", "Usage: prog <host>")
    main(["stub", source])
    assert_that(capsys.readouterr().out).contains("host: str")


def test_stub_reads_usage_from_stdin(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("Usage: prog <host>"))
    main(["stub", "-"])
    assert_that(capsys.readouterr().out).contains("host: str")


def test_stub_honours_style_and_name(tmp_path, capsys):
    source = _write(tmp_path, "usage.txt", "Usage: prog <host>")
    main(["stub", source, "--style=typeddict", "--name=Cmdline"])
    assert_that(capsys.readouterr().out).contains("class Cmdline(TypedDict):")


def test_stub_rejects_an_unknown_style(tmp_path, capsys):
    source = _write(tmp_path, "usage.txt", "Usage: prog <host>")
    exit_code = main(["stub", source, "--style=pydantic"])
    assert_that(exit_code).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("--style must be").contains("pydantic")


def test_stub_reports_a_python_file_with_no_docstring(tmp_path, capsys):
    source = _write(tmp_path, "cli.py", "x = 1\n")
    exit_code = main(["stub", source])
    assert_that(exit_code).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("no module docstring")


def test_stub_reports_a_missing_file(tmp_path, capsys):
    exit_code = main(["stub", str(tmp_path / "absent.txt")])
    assert_that(exit_code).is_equal_to(1)
    assert_that(capsys.readouterr().err).starts_with("error:")


def test_stub_reports_a_malformed_python_source(tmp_path, capsys):
    source = _write(tmp_path, "broken.py", "def (:\n")
    exit_code = main(["stub", source])
    assert_that(exit_code).is_equal_to(1)
    assert_that(capsys.readouterr().err).starts_with("error:")


def test_stub_reports_a_malformed_usage(tmp_path, capsys):
    source = _write(tmp_path, "usage.txt", "usage: prog (a]")
    exit_code = main(["stub", source])
    assert_that(exit_code).is_equal_to(1)
    assert_that(capsys.readouterr().err).starts_with("error:")


def test_stub_reports_an_invalid_class_name(tmp_path, capsys):
    source = _write(tmp_path, "usage.txt", "Usage: prog <host>")
    exit_code = main(["stub", source, "--name=not valid"])
    assert_that(exit_code).is_equal_to(1)
    assert_that(capsys.readouterr().err).starts_with("error:").contains("valid Python identifier")


def test_stub_reports_a_non_utf8_file(tmp_path, capsys):
    source = tmp_path / "latin1.txt"
    source.write_bytes(b"Usage: prog \xe9")  # 0xe9 is not valid UTF-8
    exit_code = main(["stub", str(source)])
    assert_that(exit_code).is_equal_to(1)
    assert_that(capsys.readouterr().err).starts_with("error:").contains("UTF-8")


def test_check_is_silent_and_zero_on_a_clean_usage(tmp_path, capsys):
    source = _write(tmp_path, "usage.txt", "Usage: prog <file>")
    exit_code = main(["check", source])
    captured = capsys.readouterr()
    assert_that(exit_code).is_equal_to(0)
    assert_that(captured.err).is_empty()


def test_check_reports_warnings_and_exits_nonzero(tmp_path, capsys):
    source = _write(tmp_path, "usage.txt", "Usage: prog <file>\n\nOptions:\n  --verbose  Be verbose.\n")
    exit_code = main(["check", source])
    captured = capsys.readouterr()
    assert_that(exit_code).is_equal_to(1)
    assert_that(captured.err).contains("--verbose").contains("never used")


def test_examples_prints_valid_invocations(tmp_path, capsys):
    source = _write(tmp_path, "usage.txt", "Usage: prog ship new <name>")
    exit_code = main(["examples", source, "--seed=1"])
    out = capsys.readouterr().out
    assert_that(exit_code).is_equal_to(0)
    assert_that(out).contains("ship").contains("new")  # every example walks the one usage line


def test_examples_count_caps_output_and_invalid_appends_an_unknown_option(tmp_path, capsys):
    source = _write(tmp_path, "usage.txt", "Usage: prog [--fast] <a>\n\nOptions:\n  --fast  Go fast.\n")
    main(["examples", source, "--count=3", "--invalid", "--seed=7"])
    lines = capsys.readouterr().out.splitlines()
    assert_that(lines).is_not_empty()
    assert_that(len(lines)).is_less_than_or_equal_to(3)
    for line in lines:
        assert_that(line).contains("--unknown")  # invalid examples carry the undefined option


def test_examples_seed_makes_output_reproducible(tmp_path, capsys):
    source = _write(tmp_path, "usage.txt", "Usage: prog (add | rm) <x> [--force]\n\nOptions:\n  --force  Force.\n")
    main(["examples", source, "--seed=42"])
    first = capsys.readouterr().out
    main(["examples", source, "--seed=42"])
    assert_that(capsys.readouterr().out).is_equal_to(first)


def test_examples_rejects_a_non_integer_count(tmp_path, capsys):
    source = _write(tmp_path, "usage.txt", "Usage: prog <x>")
    exit_code = main(["examples", source, "--count=lots"])
    assert_that(exit_code).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("--count must be an integer").contains("lots")


def test_config_template_prints_a_toml_skeleton(tmp_path, capsys):
    doc = "Usage: prog [--port=<n>]\n\nOptions:\n  --port=<n>  Port [default: 80] [env: PORT] [config: server.port]."
    source = _write(tmp_path, "usage.txt", doc)
    exit_code = main(["config-template", source])
    out = capsys.readouterr().out
    assert_that(exit_code).is_equal_to(0)
    assert_that(out).contains("[server]").contains("port = 80").contains("# --port, env PORT")


def test_compat_reports_breaks_and_exits_nonzero(tmp_path, capsys):
    old = _write(tmp_path, "old.txt", "Usage: prog push [--force] <remote>\n\nOptions:\n  --force  Force.")
    new = _write(tmp_path, "new.txt", "Usage: prog push <remote>")
    exit_code = main(["compat", old, new])
    captured = capsys.readouterr()
    assert_that(exit_code).is_equal_to(1)
    assert_that(captured.err).contains("--force").contains("removed")


def test_compat_is_silent_and_zero_when_no_break_is_found(tmp_path, capsys):
    old = _write(tmp_path, "old.txt", "Usage: prog push <remote>")
    new = _write(tmp_path, "new.txt", "Usage: prog push [--verbose] <remote>\n\nOptions:\n  --verbose  V.")
    exit_code = main(["compat", old, new])
    captured = capsys.readouterr()
    assert_that(exit_code).is_equal_to(0)
    assert_that(captured.err).is_empty()


def test_fmt_aligns_and_tidies_the_options_block(tmp_path, capsys):
    doc = "Usage: prog serve <root>\n\nOptions:\n  --port=<n>  Port.\n  -v, --verbose      Loud.\n"
    source = _write(tmp_path, "usage.txt", doc)
    exit_code = main(["fmt", source])
    out = capsys.readouterr().out
    assert_that(exit_code).is_equal_to(0)
    assert_that(out).contains("  -v --verbose  Loud.")  # comma normalized to a space, column aligned


def test_version_prints_and_exits(capsys):
    with raises(SystemExit):
        main(["--version"])
    assert_that(capsys.readouterr().out.strip()).is_not_empty()


def test_help_prints_usage_and_exits(capsys):
    with raises(SystemExit):
        main(["--help"])
    assert_that(capsys.readouterr().out).contains("docopt2 stub")


def test_no_command_fails_with_usage(capsys):
    with raises(SystemExit):
        main([])
