# Collects language-agnostic *.docopt case files; ported from the original docopt conftest.
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import pytest
from hypothesis import HealthCheck, settings

from docopt2 import DocoptExit, docopt

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Property tests run a fixed, reproducible set of examples so the gate never flakes; run a
# wider exploration manually with `--hypothesis-profile=explore` when hunting for edge cases.
settings.register_profile(
    "docopt2", max_examples=300, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.register_profile("explore", max_examples=10000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
# Mutation testing replays the suite once per mutant, thousands of times over. Derandomised, these are
# the first 25 examples the full profile draws, so it can only ever under-kill - measured against the
# full 300 over 4558 mutants, it misses 3 of them, and reports those 3 as survivors to look at anyway.
settings.register_profile(
    "mutation", max_examples=25, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.load_profile("docopt2")

Case = tuple[str, str, Any]


def pytest_collect_file(file_path: Path, parent: pytest.Collector) -> DocoptTestFile | None:
    """Collect any ``test*.docopt`` file as a suite of usage cases."""
    if file_path.suffix == ".docopt" and file_path.name.startswith("test"):
        return DocoptTestFile.from_parent(parent, path=file_path)
    return None


def parse_test(raw: str) -> Iterator[tuple[str, list[Case]]]:
    """Yield ``(docstring, cases)`` fixtures parsed from a ``.docopt`` file body."""
    raw = re.sub(r"#.*$", "", raw, flags=re.MULTILINE).strip()
    if raw.startswith('"""'):
        raw = raw[3:]
    for fixture in raw.split('r"""'):
        doc, _, body = fixture.partition('"""')
        cases: list[Case] = []
        for case in body.split("$")[1:]:
            argv, _, expect = case.strip().partition("\n")
            prog, _, argv = argv.strip().partition(" ")
            cases.append((prog, argv, json.loads(expect)))
        yield doc, cases


class DocoptTestFile(pytest.File):
    """A collected ``.docopt`` file, exposing each invocation as a test item."""

    def collect(self) -> Iterator[DocoptTestItem]:
        raw = self.path.read_text(encoding="utf-8")
        stem = self.path.stem
        index = 1
        for doc, cases in parse_test(raw):
            for case in cases:
                yield DocoptTestItem.from_parent(self, name=f"{stem}({index})", doc=doc, case=case)
                index += 1


class DocoptTestItem(pytest.Item):
    """A single ``$ prog ...`` invocation checked against its expected result."""

    def __init__(self, *, doc: str, case: Case, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.doc = doc
        self.prog, self.argv, self.expect = case

    def runtest(self) -> None:
        try:
            result: Any = docopt(self.doc, argv=self.argv)
        except DocoptExit:
            result = "user-error"
        if self.expect != result:
            raise DocoptTestException(self, result)

    def repr_failure(self, excinfo: pytest.ExceptionInfo[BaseException], **kwargs: Any) -> str:
        if isinstance(excinfo.value, DocoptTestException):
            result = excinfo.value.args[1]
            return "\n".join(
                [
                    "usecase execution failed:",
                    self.doc.rstrip(),
                    f"$ {self.prog} {self.argv}",
                    f"result> {json.dumps(result)}",
                    f"expect> {json.dumps(self.expect)}",
                ]
            )
        return str(super().repr_failure(excinfo, **kwargs))

    def reportinfo(self) -> tuple[Path, int, str]:
        return self.path, 0, f"usecase: {self.name}"


class DocoptTestException(Exception):
    """Raised by a docopt usecase item when the parsed result differs from expected."""
