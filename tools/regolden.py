from __future__ import annotations

from pathlib import Path

from docopt2 import generate_completion

# The same usage and program name the golden test generates from; both read this one definition.
DOC = """Usage:
  git-tool clone <url> [--depth=<n>]
  git-tool commit [-m <msg>] [--amend]
  git-tool remote add <name> <url>

Options:
  --depth=<n>  Clone depth.
  -m <msg>     Message.
  --amend      Amend commit.
"""
PROG = "git-tool"
SHELLS = ("bash", "zsh", "fish", "powershell")


def main() -> int:
    """Rewrite the golden completion scripts. Run after an intentional change to a shell template."""
    golden = Path(__file__).parent.parent / "tests" / "golden"
    golden.mkdir(exist_ok=True)
    for shell in SHELLS:
        target = golden / f"completion_{shell}.txt"
        target.write_text(generate_completion(DOC, PROG, shell), encoding="utf-8", newline="\n")
        print(f"wrote {target.relative_to(golden.parent.parent)}")
    return 0


if __name__ == "__main__":  # pragma: no cover - a maintenance script, not library code
    raise SystemExit(main())
