import subprocess
import sys

from assertpy2 import assert_that

# `import docopt2` used to cost ~2x what it does now, and a timing benchmark is the wrong guard for that:
# noisy, machine-dependent, and it never says WHAT regressed. What was actually fixed is structural, so
# this pins it structurally. Re-adding an eager import - a top-level `importlib.metadata` for `__version__`,
# or an eager tooling import in the facade - fails right here and names the module that did it.

# importlib.metadata alone drags in email, zipfile, shutil and more; the tooling is what `docopt()` never
# touches. Both are deferred, and both must stay deferred.
_MUST_STAY_UNIMPORTED = (
    "importlib.metadata",
    "email",
    "zipfile",
    "shutil",
    "json",
    "docopt2._compat",
    "docopt2._lint",
    "docopt2._fmt",
    "docopt2._format",
    "docopt2._generate",
    "docopt2._stub",
)


def _modules_loaded_by(statement: str) -> set[str]:
    code = f"{statement}; import sys; print(chr(10).join(sys.modules))"
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return set(completed.stdout.split())


def test_importing_docopt2_pulls_in_neither_the_metadata_chain_nor_the_tooling():
    loaded = _modules_loaded_by("import docopt2")
    assert_that(sorted(loaded & set(_MUST_STAY_UNIMPORTED))).is_empty()


def test_the_deferred_names_still_resolve_when_they_are_asked_for():
    # Laziness must not become absence: reading the version, or reaching for a tool, still works.
    loaded = _modules_loaded_by("import docopt2; docopt2.__version__; docopt2.check")
    assert_that(loaded).contains("importlib.metadata", "docopt2._lint")
