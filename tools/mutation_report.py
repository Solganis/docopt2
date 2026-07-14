from __future__ import annotations

import collections
import json
import pathlib
import sys

# mutmut writes one of these per source module, mapping each mutant to the exit code of the test run
# that judged it: non-zero means a test failed, so the mutant was caught. Read that instead of scraping
# the emoji progress line, which carries carriage returns and depends on the runner's locale.
_RESULTS = pathlib.Path("mutants/src/docopt2")


def _tally() -> tuple[int, int, collections.Counter[str]]:
    """Total mutants, how many were killed, and the surviving count per module."""
    killed = 0
    total = 0
    survivors: collections.Counter[str] = collections.Counter()
    for meta in sorted(_RESULTS.glob("*.meta")):
        codes = json.loads(meta.read_text(encoding="utf-8")).get("exit_code_by_key", {})
        for code in codes.values():
            total += 1
            if code:
                killed += 1
            else:
                survivors[meta.name.removesuffix(".py.meta")] += 1
    return total, killed, survivors


def main() -> int:
    """Write a markdown summary of the mutation run to stdout."""
    if not _RESULTS.is_dir():
        print("no mutation results found - did `mutmut run` fail?", file=sys.stderr)
        return 1
    total, killed, survivors = _tally()
    if total == 0:
        print("no mutants were generated", file=sys.stderr)
        return 1
    print("## Mutation testing\n")
    print(f"**{killed / total:.1%}** of mutants killed - {killed} of {total}. {total - killed} survived.\n")
    print("A survivor is a change to the source that no test noticed. Most are equivalent (message text,")
    print("scoring weights with slack); the rest are gaps worth a test.\n")
    print("| module | survivors |")
    print("| --- | --- |")
    for module, count in survivors.most_common():
        print(f"| `{module}` | {count} |")
    return 0


if __name__ == "__main__":  # pragma: no cover - a CI script, not library code
    raise SystemExit(main())
