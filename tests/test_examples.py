import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from assertpy2 import assert_that

_EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

# Each example script, a representative argv, and a stable marker its output must contain. Runs the
# script as __main__ so an API change that breaks one fails here instead of silently rotting.
_CASES = [
    ("naval_fate.py", ["ship", "new", "Titanic"], "Titanic"),
    ("typed.py", ["localhost", "8080"], "port=8080"),
    ("cli.py", ["./data", "./backups"], "backing up"),
    ("dispatch.py", ["commit", "--message=hi"], "committing"),
    ("completion.py", ["--completion=bash"], "COMP_WORDS"),
    ("layered.py", [], "from config"),
    ("rich_help.py", ["./public"], "./public"),
    ("round_trip.py", ["web", "--replicas=3", "--force"], "rebuilt: deploy web --replicas=3 --force"),
]


@pytest.mark.parametrize(("filename", "argv", "expected"), _CASES)
def test_example_runs_and_prints_expected(filename, argv, expected, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", [filename, *argv])
    for variable in ("APP_PORT", "APP_LOG", "PORT", "HOST"):
        monkeypatch.delenv(variable, raising=False)  # keep [env:] fallbacks from perturbing the resolution
    try:
        runpy.run_path(str(_EXAMPLES_DIR / filename), run_name="__main__")
    except SystemExit as exit_signal:
        assert_that(exit_signal.code in (None, 0)).is_true()  # a clean exit (help/version) is fine, an error is not
    assert_that(capsys.readouterr().out).contains(expected)


def test_every_example_is_covered_by_a_case():
    # A new examples/*.py without a smoke case would go unguarded - fail until it is added above.
    scripts = {path.name for path in _EXAMPLES_DIR.glob("*.py")}
    assert_that({filename for filename, _, _ in _CASES}).is_equal_to(scripts)


def test_the_completion_example_answers_the_completion_protocol():
    # The generated script is a callback: at each Tab it re-invokes the program, and docopt() answers with
    # the candidates. The example used to only PRINT the script and never call docopt, so sourcing it gave
    # the shell nothing - it just printed the script back at itself.
    root = Path(__file__).parent.parent
    env = {**os.environ, "_DOCOPT2_COMPLETE": "1", "_DOCOPT2_WORDS": "", "PYTHONIOENCODING": "utf-8"}
    out = subprocess.run(
        [sys.executable, str(root / "examples" / "completion.py")],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    ).stdout
    offered = {line.split("\t")[0] for line in out.splitlines() if line}
    assert_that(offered).contains("serve", "build")
