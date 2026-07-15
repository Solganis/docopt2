from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from docopt2 import complete, generate_completion

# The completion tests pin what the generated SCRIPTS say; they never run them, which is exactly where a
# completion bug hides. A shell's scripting interface does not close the gap either: a hand-built COMP_WORDS
# never reproduces bash's own wordbreak split, and a second Tab masks a defect that only shows on the first.
# So this opens a pty, types the line, presses Tab, and reads what the shell really offers. PowerShell
# exposes its completion engine to code, so it needs no pty.

_NAVAL = """Naval Fate.

Usage:
  naval ship new <name>...
  naval ship <name> move <x> <y> [--speed=<kn>]
  naval mine (set|remove) <x> <y> [--moored | --drifting]
  naval --version

Options:
  --version     Show version.
  --speed=<kn>  Speed in knots [default: 10].
  --moored      Moored (anchored) mine.
  --drifting    Drifting mine.
"""

_TOOL = """Tool.

Usage:
  tool [--opt=<v>] build <target>
  tool [--opt=<v>] test
  tool [--opt=<v>] deploy <env>

Options:
  --opt=<v>  An option that takes a value.
"""

_DOCS = {"naval": _NAVAL, "tool": _TOOL}

_PROGRAM = '''#!{python}
"""{doc}"""
import sys
from docopt2 import docopt, generate_completion

if len(sys.argv) >= 3 and sys.argv[1] == "--completion":
    print(generate_completion(__doc__, prog="{prog}", shell=sys.argv[2]))
    sys.exit(0)
print(docopt(__doc__))
'''

# `tool --opt=x` is a token bash shreds at a wordbreak, and the `$fpath` case below fires on zsh's FIRST
# Tab. Both are known to fail against an unfixed script, so this check is proven to catch what it guards.
_CASES = [
    ("naval", []),
    ("naval", ["mine"]),
    ("naval", ["mine", "set"]),
    ("naval", ["ship"]),
    ("tool", ["--opt=x"]),
]

_READY = "DOCOPT2-READY"
# The split that matters is not SGR-vs-rest but WIDTH. A sequence that moves the cursor or erases really
# does separate two regions of the screen, so it must become a space - otherwise a redrawn prompt glues
# onto the candidate list and `test` arrives as `testtool`. Everything else (colour, terminal modes) takes
# no space at all, so it must vanish: a shell paints the matched `--` of `--drifting` in one colour and the
# rest in another, and turning that into a space would split the candidate and the check would "miss" it.
_MOVE = re.compile(r"\x1b\[[0-9;?]*[A-HJKSTfd]|\r")
_ZERO = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()>=][A-Za-z0-9]?|\x1bP.*?\x1b\\|\x07", re.S)


def _install(bin_dir: Path, prog: str, doc: str) -> None:
    """Put `prog` on PATH under its bare name: every generated script invokes the command the user typed."""
    script = bin_dir / f"{prog}.py"
    script.write_text(_PROGRAM.format(python=sys.executable, doc=doc, prog=prog), encoding="utf-8", newline="\n")
    if platform.system() == "Windows":
        (bin_dir / f"{prog}.cmd").write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="ascii")
    else:
        launcher = bin_dir / prog
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8", newline="\n")
        launcher.chmod(0o755)


def _read_until(fd: int, want: str | None, *, idle: float, cap: float) -> str:
    """Read a pty until `want` appears, or until it has been quiet for `idle` seconds. Never sleeps blindly."""
    import select

    chunks: list[bytes] = []
    deadline = time.monotonic() + cap
    last = time.monotonic()
    while time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.05)
        if readable:
            try:
                data = os.read(fd, 65536)
            except OSError:  # the shell closed the pty: EIO, not a failure
                break
            if not data:
                break
            chunks.append(data)
            last = time.monotonic()
            if want and want in b"".join(chunks).decode("utf-8", "replace"):
                break
        elif want is None and time.monotonic() - last >= idle:
            break  # waiting for a marker must not give up on a lull: fish sits silent for 2s on startup
    return b"".join(chunks).decode("utf-8", "replace")  # raw: a failure must be able to show the escapes


def _clean(raw: str) -> str:
    return _ZERO.sub("", _MOVE.sub(" ", raw))


def _tab(shell: list[str], setup: str, line: str, tabs: int = 2) -> str:
    """Type `line` at a real prompt, press Tab, and return only what the shell painted in reply."""
    import fcntl
    import pty
    import struct
    import termios

    master, slave = pty.openpty()
    # A pty starts 0x0, and a shell that believes it has no room paints no candidate list at all. The size
    # has to be set on the tty itself; COLUMNS is not read.
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))

    def _take_controlling_tty() -> None:
        # A new session alone is not enough: without TIOCSCTTY the pty is not the session's CONTROLLING
        # terminal, and fish then refuses to be interactive ("No TTY for interactive shell") and paints
        # nothing at all. bash and zsh tolerate that; fish does not.
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    environment = {**os.environ, "TERM": "xterm-256color"}  # TERM=dumb would disable the painting read below
    process = subprocess.Popen(
        shell, stdin=slave, stdout=slave, stderr=slave, preexec_fn=_take_controlling_tty, env=environment
    )
    os.close(slave)
    try:
        # Wait for the shell to finish coming up BEFORE typing anything: fish queries the terminal and sits
        # silent for two seconds, and input sent while it is doing that is simply lost.
        _read_until(master, None, idle=3.5, cap=25.0)
        os.write(master, f"{setup}\necho {_READY}\n".encode())
        _read_until(master, _READY, idle=1.0, cap=20.0)  # the script is loaded and the shell is at a prompt
        os.write(master, line.encode())
        _read_until(master, None, idle=0.3, cap=5.0)  # drain the echo of the line just typed
        # readline lists only on the SECOND Tab when the first one merely inserts a common prefix, so both
        # are sent and both replies are kept.
        offered = ""
        for _ in range(tabs):
            os.write(master, b"\t")
            offered += _read_until(master, None, idle=0.6, cap=15.0)
        return offered
    finally:
        process.kill()
        process.wait()
        os.close(master)


def _zsh_autoloaded(work: Path, prog: str, typed: list[str]) -> str:
    """zsh, installed the way the guide documents: saved as `_prog` on $fpath and autoloaded.

    ONE Tab, deliberately. Autoloaded, zsh runs the file's body AS the completion function, so a body that
    only defines and registers offers nothing on the FIRST Tab and works on the second. A two-Tab driver
    would mask exactly that.
    """
    fpath = work / "fpath"
    fpath.mkdir(exist_ok=True)
    (fpath / f"_{prog}").write_text((work / f"{prog}.zsh").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    setup = f"PS1='> '\nfpath=({fpath} $fpath)\nautoload -Uz compinit && compinit -u"
    return _tab(["zsh", "-f", "-i"], setup, " ".join([prog, *typed, ""]), tabs=1)


def _posix(shell: str, work: Path, prog: str, typed: list[str]) -> str:
    script = work / f"{prog}.{shell}"
    setup = {
        # show-all-if-ambiguous: readline otherwise only inserts the common prefix on the first Tab and
        # lists on the second, which hides the candidates whenever they share one (`--drifting`/`--moored`).
        "bash": f"PS1='> '\nbind 'set show-all-if-ambiguous on'\nsource {script}",
        "zsh": f"PS1='> '\nautoload -Uz compinit && compinit -u\nsource {script}",
        "fish": f"function fish_prompt; printf '> '; end\nsource {script}",
    }[shell]
    binary = {"bash": ["bash", "--norc", "-i"], "zsh": ["zsh", "-f", "-i"], "fish": ["fish", "-i"]}[shell]
    return _tab(binary, setup, " ".join([prog, *typed, ""]))


def _powershell(work: Path, prog: str, typed: list[str]) -> str:
    line = " ".join([prog, *typed, ""])
    driver = (
        f". '{work / f'{prog}.ps1'}'; "
        f"[System.Management.Automation.CommandCompletion]::CompleteInput('{line}', {len(line)}, $null)"
        ".CompletionMatches | ForEach-Object { $_.CompletionText }"
    )
    return subprocess.run(
        ["pwsh", "-NoProfile", "-Command", driver], capture_output=True, text=True, check=False
    ).stdout


def _nushell(work: Path, prog: str, typed: list[str]) -> str:
    """nushell exposes its completion engine to code, so no pty: feed the line to `commandline complete`
    (nushell 0.114+). The module is `use`d by the file name the check writes it under."""
    script = work / f"{prog}-completions.nu"
    line = " ".join([prog, *typed, ""])
    driver = f'use {script} *; "{line}" | commandline complete | str join (char newline)'
    return subprocess.run(["nu", "-n", "-c", driver], capture_output=True, text=True, check=False).stdout


_EXECUTABLE = {"bash": "bash", "zsh": "zsh", "fish": "fish", "powershell": "pwsh", "nushell": "nu"}


def _report(label: str, expected: list[str], raw: str) -> int:
    """Hold what the shell offered against the grammar; on a miss, show the escapes it actually painted."""
    offered = _clean(raw)
    missing = [name for name in expected if not re.search(rf"(?<![\w=-]){re.escape(name)}(?![\w=-])", offered)]
    print(f"{'ok  ' if not missing else 'FAIL'} {label} <TAB>", flush=True)
    if missing:
        print(f"       expected: {expected}", flush=True)
        print(f"       missing : {missing}", flush=True)
        print(f"       offered : {' '.join(offered.split())[:300]!r}", flush=True)
        print(f"       raw     : {raw[-400:]!r}", flush=True)  # the escapes: no guessing across terminals
    return bool(missing)


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="docopt2-shells-"))
    bin_dir = work / "bin"
    bin_dir.mkdir()
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    for prog, doc in _DOCS.items():
        _install(bin_dir, prog, doc)

    # Git Bash on Windows is not a target: the program lands there as a `.cmd` shim a POSIX script cannot
    # invoke. bash/zsh/fish are driven on Linux, PowerShell on Windows.
    wanted = ["powershell"] if platform.system() == "Windows" else ["bash", "zsh", "fish", "nushell"]
    shells = [name for name in wanted if shutil.which(_EXECUTABLE[name])]
    if not shells:
        print("no shell available to drive - the check would pass vacuously", file=sys.stderr)
        return 1

    failures = 0
    for shell in shells:
        for prog, doc in _DOCS.items():
            # nushell's module file must not be named `<prog>.nu` (a module cannot export an extern of its
            # own name), so it is saved under another name and `use`d by it.
            suffix = "ps1" if shell == "powershell" else shell
            name = f"{prog}-completions.nu" if shell == "nushell" else f"{prog}.{suffix}"
            (work / name).write_text(generate_completion(doc, prog=prog, shell=shell), encoding="utf-8", newline="\n")
        for prog, typed in _CASES:
            expected = complete(_DOCS[prog], [*typed, ""])
            if shell == "powershell":
                raw = _powershell(work, prog, typed)
            elif shell == "nushell":
                raw = _nushell(work, prog, typed)
            else:
                raw = _posix(shell, work, prog, typed)
            failures += _report(f"{shell:11} {prog} {' '.join(typed)}", expected, raw)
        if shell == "zsh":  # the documented $fpath install, on the FIRST Tab
            failures += _report(
                "zsh         naval mine (autoloaded from $fpath)",
                complete(_NAVAL, ["mine", ""]),
                _zsh_autoloaded(work, "naval", ["mine"]),
            )
    total = len(shells) * len(_CASES) + ("zsh" in shells)
    print(f"\n{total - failures} passed, {failures} failed, over {', '.join(shells)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
