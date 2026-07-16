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

# The type tables - the schema coercers and the set a `[config:]` value may hold - name these, and a plain
# docopt() call reaches neither. Together they were 70% of what importing docopt2 cost: `dataclasses` and
# `typing_extensions` each drag in `inspect`, and `pathlib` drags in `urllib.parse`. Every one is built on
# first use now, so a single top-level `from pathlib import Path` would silently undo it - hence this list.
_MUST_STAY_UNIMPORTED_UNTIL_TYPED = (
    "dataclasses",
    "inspect",
    "typing_extensions",
    "pathlib",
    "decimal",
    "uuid",
    "datetime",
)


def _modules_loaded_by(statement: str) -> set[str]:
    code = f"{statement}; import sys; print(chr(10).join(sys.modules))"
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return set(completed.stdout.split())


def test_importing_docopt2_pulls_in_neither_the_metadata_chain_nor_the_tooling():
    loaded = _modules_loaded_by("import docopt2")
    assert_that(sorted(loaded & set(_MUST_STAY_UNIMPORTED))).is_empty()


def test_parsing_without_a_schema_pulls_in_none_of_the_typed_machinery():
    # The whole point: a CLI that just parses argv must not pay for coercion it never asks for.
    loaded = _modules_loaded_by("import docopt2; docopt2.docopt('Usage: prog <x>', ['a'], complete=False)")
    assert_that(sorted(loaded & set(_MUST_STAY_UNIMPORTED_UNTIL_TYPED))).is_empty()


def test_importing_docopt2_never_imports_pydantic():
    # pydantic support is REFLECTIVE (detected by `model_validate`), so the core must not import it at all -
    # a different claim from the deferred lists above, which is why it sits in its own test. concepts/
    # design-boundaries.md shows exactly this as `"pydantic" in sys.modules` -> False. Only a CLEAN process
    # can answer it: inside the suite other tests have already imported pydantic, so the docs fence gate
    # deliberately skips that block and defers to this one.
    assert_that(_modules_loaded_by("import docopt2")).does_not_contain("pydantic")


def test_the_deferred_names_still_resolve_when_they_are_asked_for():
    # Laziness must not become absence: reading the version, or reaching for a tool, still works.
    loaded = _modules_loaded_by("import docopt2; docopt2.__version__; docopt2.check")
    assert_that(loaded).contains("importlib.metadata", "docopt2._lint")


def test_a_schema_still_coerces_the_types_whose_modules_are_deferred():
    # And laziness must not become absence here either: the coercion table is built on demand, so a
    # deferred `pathlib`/`decimal`/`uuid`/`datetime` must still arrive the moment a schema names one.
    code = (
        "import dataclasses, datetime, decimal, pathlib, uuid, docopt2\n"
        "@dataclasses.dataclass\n"
        "class Args:\n"
        "    path: pathlib.Path\n"
        "    amount: decimal.Decimal\n"
        "    ident: uuid.UUID\n"
        "    when: datetime.date\n"
        "doc = 'Usage: prog <path> <amount> <ident> <when>'\n"
        "got = docopt2.docopt(doc, ['/tmp/x', '1.5', '12345678-1234-5678-1234-567812345678', '2026-07-14'],\n"
        "                     schema=Args, complete=False)\n"
        "print(type(got.path).__name__, type(got.amount).__name__, type(got.ident).__name__, type(got.when).__name__)"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert_that(completed.stdout.split()).is_equal_to(
        ["WindowsPath" if sys.platform == "win32" else "PosixPath", "Decimal", "UUID", "date"]
    )
