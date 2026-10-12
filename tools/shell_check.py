from __future__ import annotations

import dataclasses
import functools
import inspect
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Literal

from docopt2 import Command, complete, docopt, generate_completion
from docopt2._parser import formal_usage, parse_defaults, parse_pattern, single_usage_section
from docopt2._typed import field_choices

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

_DEPLOYER = """Deployer.

Usage:
  deployer <env> [--format=<f>]

Options:
  --format=<f>  Output format.
"""


@dataclasses.dataclass
class _Deploy:
    env: Literal["dev", "staging", "prod"]
    format: Literal["json", "jsonl", "yaml"] | None


_FILER = """Filer.

Usage:
  filer [go] <file> [--out=<path>] [--mode=<m>] [--name=<n>]

Options:
  --out=<path>  Where to write.
  --mode=<m>    Mode.
  --name=<n>    A label.
"""


@dataclasses.dataclass
class _Filer:
    go: bool
    file: Path
    out: Path | None
    mode: Literal["json", "yaml"] | None
    name: str | None


_DOCS = {"naval": _NAVAL, "tool": _TOOL, "deployer": _DEPLOYER, "filer": _FILER}
# a program with a schema completes the values its closed sets hold, and file names for its `Path` fields
_SCHEMAS = {"deployer": _Deploy, "filer": _Filer}

_PROGRAM = '''#!{python}
"""{doc}"""
import dataclasses
from pathlib import Path
import sys
from typing import Literal

from docopt2 import docopt, generate_completion

{schema}
if len(sys.argv) >= 3 and sys.argv[1] == "--completion":
    print(generate_completion(__doc__, prog="{prog}", shell=sys.argv[2]))
    sys.exit(0)
print(sys.argv[1:], docopt(__doc__, schema={schema_name}))
'''

# `tool --opt=x` is a token bash shreds at a wordbreak, and the `$fpath` case below fires on zsh's FIRST
# Tab. Both are known to fail against an unfixed script, so this check is proven to catch what it guards.
# the last five complete a value: a positional, an option's argument, three behind `--format=` (the last: nothing)
_CASES = [
    ("naval", [], ""),
    ("naval", ["mine"], ""),
    ("naval", ["mine", "set"], ""),
    ("naval", ["ship"], ""),
    ("tool", ["--opt=x"], ""),
    ("deployer", [], ""),
    ("deployer", ["prod", "--format"], ""),
    ("deployer", ["prod"], "--format="),
    ("deployer", ["prod"], "--format=j"),
    ("deployer", ["prod"], "--format=x"),
]

# File names: the line, what the shell must paint, what it must not. A word that one file completes is painted as
# the rest of that name. No line names a file of the directory, so none is on the screen unless it was offered.
_FILE_NAMES = ("notes.txt", "other.log", "zeta.md")
_FILE_CASES = [
    ("filer no", ["tes.txt"], ["other.log", "zeta.md"]),
    ("filer ", [*_FILE_NAMES], []),
    ("filer zzz --out ot", ["her.log"], ["notes.txt", "zeta.md"]),
    ("filer zzz --mode ", ["json", "yaml"], [*_FILE_NAMES]),
    ("filer zzz --name ", [], [*_FILE_NAMES]),
    ("filer zzz extra ", [], [*_FILE_NAMES, "json"]),
]
# PowerShell completes file names by itself wherever a completer returns nothing, so the last two are not its
_OWN_FALLBACK = {"powershell": {"filer zzz --name ", "filer zzz extra "}}
# A word that one odd file completes, and that file. The completed line is run: the program must be handed the name.
# `x.txt` is there for `[x].txt` to be mistaken for, as a pattern.
_ODD_NAMES = ("[x].txt", "x.txt", "with space.txt", "back`tick.txt")
_EXACT = [
    ("filer [", "[x].txt"),
    ("filer wi", "with space.txt"),
    ("filer ba", "back`tick.txt"),
    ("filer with\\ s", "with space.txt"),
]
_NOT_EXACT = {name: {"filer with\\ s"} for name in ("powershell", "nushell")}  # a backslash escapes nothing there
# bash and fish are told of this name in two lines. Both start alike, so offered as files they complete `tw` to `twin`
_BROKEN_NAME = "twin\ntwins.txt"
_AS_TYPED = {"zsh": {"filer [": "filer \\["}}  # an unquoted `[` opens a pattern to zsh, whose own completion answers
_DIRECTORY = "go"  # a directory named as the command of `filer`: the command must stay a command
# how a user loads the script the program prints for `_DOCOPT2_COMPLETE=<shell>`. nushell reads a module when it
# parses a line, so one nushell saves the script and the next one `use`s it.
_ASKED_FROM_THE_PROGRAM = {
    "bash": 'eval "$(_DOCOPT2_COMPLETE=bash filer)"',
    "zsh": 'eval "$(_DOCOPT2_COMPLETE=zsh filer)"',
    "fish": "_DOCOPT2_COMPLETE=fish filer | source",
    "powershell": "$env:_DOCOPT2_COMPLETE = 'powershell'; filer | Out-String | Invoke-Expression; "
    "Remove-Item Env:_DOCOPT2_COMPLETE",
    "nushell": "_DOCOPT2_COMPLETE=nushell filer | save -f {module}",
}

_FILES = "files"  # the directory every shell is driven in, holding `_FILE_NAMES`, `_ODD_NAMES` and `_DIRECTORY`
_READY = "DOCOPT2-READY"
# The split that matters is not SGR-vs-rest but WIDTH. A sequence that moves the cursor or erases really
# does separate two regions of the screen, so it must become a space - otherwise a redrawn prompt glues
# onto the candidate list and `test` arrives as `testtool`. Everything else (colour, terminal modes) takes
# no space at all, so it must vanish: a shell paints the matched `--` of `--drifting` in one colour and the
# rest in another, and turning that into a space would split the candidate and the check would "miss" it.
_MOVE = re.compile(r"\x1b\[[0-9;?]*[A-HJKSTfd]|\r")
_ZERO = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()>=][A-Za-z0-9]?|\x1bP.*?\x1b\\|\x07", re.DOTALL)


def _install(bin_dir: Path, prog: str, doc: str) -> None:
    """Put `prog` on PATH under its bare name: every generated script invokes the command the user typed."""
    script = bin_dir / f"{prog}.py"
    schema = _SCHEMAS.get(prog)
    program = _PROGRAM.format(
        python=sys.executable,
        doc=doc,
        prog=prog,
        schema=inspect.getsource(schema) if schema else "",
        schema_name=schema.__name__ if schema else "None",
    )
    script.write_text(program, encoding="utf-8", newline="\n")
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


def _tab(shell: list[str], setup: str, line: str, tabs: int = 2, run: bool = False) -> str:
    """Type `line` at a real prompt, press Tab, and return only what the shell painted in reply. With ``run``,
    press Enter after that and return what the completed line printed too."""
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
        # silent for two seconds, and input sent while it is doing that is simply lost. bash and zsh keep what
        # is typed early, and the marker below is waited for: three seconds less for each of their sessions.
        _read_until(master, None, idle=3.5 if shell[0] == "fish" else 0.5, cap=25.0)
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
        if run:
            os.write(master, b"\n")
            offered += _read_until(master, None, idle=1.5, cap=20.0)
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


def _posix(
    shell: str, work: Path, prog: str, line: str, load: str | None = None, tabs: int = 2, run: bool = False
) -> str:
    load = f"cd {work / _FILES}\n" + (load or f"source {work / f'{prog}.{shell}'}")
    setup = {
        # show-all-if-ambiguous: readline otherwise only inserts the common prefix on the first Tab and
        # lists on the second, which hides the candidates whenever they share one (`--drifting`/`--moored`).
        "bash": f"PS1='> '\nbind 'set show-all-if-ambiguous on'\n{load}",
        "zsh": f"PS1='> '\nautoload -Uz compinit && compinit -u\n{load}",
        "fish": f"function fish_prompt; printf '> '; end\n{load}",
    }[shell]
    binary = {"bash": ["bash", "--norc", "-i"], "zsh": ["zsh", "-f", "-i"], "fish": ["fish", "-i"]}[shell]
    return _tab(binary, setup, line, tabs, run)


def _powershell(work: Path, prog: str, line: str, load: str | None = None) -> str:
    load = load or f". '{work / f'{prog}.ps1'}'"
    driver = (
        f"Set-Location '{work / _FILES}'; {load}; "
        f"[System.Management.Automation.CommandCompletion]::CompleteInput('{line}', {len(line)}, $null)"
        ".CompletionMatches | ForEach-Object { $_.CompletionText }"
    )
    # check=True: a driver that failed prints nothing, and nothing is what a case may be waiting for
    return subprocess.run(["pwsh", "-NoProfile", "-Command", driver], capture_output=True, text=True, check=True).stdout


def _nushell(work: Path, prog: str, line: str, load: str | None = None) -> str:
    """nushell exposes its completion engine to code, so no pty: feed the line to `commandline complete`
    (nushell 0.114+). The module is `use`d by the file name the check writes it under."""
    script = work / f"{prog}-completions.nu"
    if load is not None:
        script = work / f"{prog}-asked.nu"
        subprocess.run(["nu", "-n", "-c", load.format(module=script)], check=True)
    driver = f'use {script} *; "{line}" | commandline complete | str join (char newline)'
    # cwd, not `cd`: nushell's own file completion reads the directory the process started in
    ran = subprocess.run(["nu", "-n", "-c", driver], capture_output=True, text=True, check=True, cwd=work / _FILES)
    return ran.stdout


_EXECUTABLE = {"bash": "bash", "zsh": "zsh", "fish": "fish", "powershell": "pwsh", "nushell": "nu"}


def _offers(offered: str, name: str) -> bool:
    """Whether the shell painted ``name`` as a candidate: whole, or the way fish's pager does when every
    candidate starts alike, with the shared start cut down to an ellipsis (`…rmat=jsonl`)."""
    whole = re.search(rf"(?<![\w=-]){re.escape(name)}(?![\w=-])", offered) is not None
    tails = (re.escape(name[cut:]) for cut in range(1, len(name) - 2))
    return whole or any(re.search(rf"…{tail}(?![\w=-])", offered) for tail in tails)


def _everything(prog: str) -> set[str]:
    """Every name a program can be offered at some point of some line: its commands, options and values."""
    doc, schema = _DOCS[prog], _SCHEMAS.get(prog)
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_usage(single_usage_section(doc)), options)
    names = {str(leaf.name) for leaf in pattern.flat(Command)}
    names |= {name for option in options for name in (option.long, option.short) if name}
    values = field_choices([schema]) if schema else {}
    names |= {value for texts in values.values() for value in texts}
    return names | {
        f"{option.long}={value}" for option in options if option.long for value in values.get(option.long[2:], [])
    }


def _report(label: str, expected: list[str], raw: str, absent: set[str]) -> int:
    """Hold what the shell offered against the grammar, both ways: every name it should offer is there, and
    none of ``absent`` is. On a miss, show the escapes it actually painted."""
    offered = _clean(raw)
    missing = [name for name in expected if not _offers(offered, name)]
    missing += [f"nothing, where it offered {name}" for name in sorted(absent) if _offers(offered, name)]
    print(f"{'ok  ' if not missing else 'FAIL'} {label} <TAB>", flush=True)
    if missing:
        print(f"       expected: {expected}", flush=True)
        print(f"       missing : {missing}", flush=True)
        print(f"       offered : {' '.join(offered.split())[:300]!r}", flush=True)
        print(f"       raw     : {raw[-400:]!r}", flush=True)  # the escapes: no guessing across terminals
    return bool(missing)


def _report_files(label: str, painted: list[str], never: list[str], raw: str) -> int:
    """Hold what the shell painted against names written by hand: each of ``painted`` is there, none of ``never``."""
    screen = _clean(raw)
    wrong = [f"no {name}" for name in painted if name not in screen] + [
        f"{name} is there" for name in never if name in screen
    ]
    print(f"{'ok  ' if not wrong else 'FAIL'} {label} <TAB>", flush=True)
    if wrong:
        print(f"       wrong  : {wrong}", flush=True)
        print(f"       painted: {' '.join(screen.split())[-300:]!r}", flush=True)
    return bool(wrong)


def _run(shell: str, work: Path, line: str) -> str:
    """What the program prints when ``line`` is run by ``shell`` in the directory of the files."""
    command = {"nushell": ["nu", "-n", "-c", line], "powershell": ["pwsh", "-NoProfile", "-Command", line]}[shell]
    ran = subprocess.run(command, capture_output=True, text=True, check=False, cwd=work / _FILES)
    return ran.stdout + ran.stderr


def _completed_and_run(shell: str, work: Path, line: str) -> str:
    """Complete ``line`` with one Tab and run what came of it: what the shell painted and the program printed."""
    if shell not in ("nushell", "powershell"):
        return _clean(_posix(shell, work, "filer", line, tabs=1, run=True))
    candidates = {"nushell": _nushell, "powershell": _powershell}[shell](work, "filer", line).splitlines()
    # the candidates are shown in a form `_handed` cannot take for what the program printed
    offered = "offered: " + " ; ".join(candidates) + "\n"
    return offered + "".join(_run(shell, work, f"filer {candidate}") for candidate in candidates)


def _handed(printed: str, name: str) -> bool:
    """Whether a run printed ``name`` as the one argument the program was given. PowerShell writes `.\name`."""
    return any(f"[{given!r}]" in printed for given in (name, f".\\{name}"))


def _odd_names(shell: str, work: Path) -> list[str]:
    """What is wrong with the odd file names in ``shell``, as lines to print."""
    wrong = []
    for line, name in _EXACT:
        if line in _NOT_EXACT.get(shell, ()):
            continue
        printed = _completed_and_run(shell, work, _AS_TYPED.get(shell, {}).get(line, line))
        if not _handed(printed, name):
            wrong.append(f"{line!r} did not hand the program {name!r}: {' '.join(printed.split())[-200:]!r}")
    # the command `go` beside the directory `go`: completed and run, the line must not have become the directory
    if shell in ("nushell", "powershell"):
        offered = {"nushell": _nushell, "powershell": _powershell}[shell](work, "filer", "filer g").splitlines()
        if _DIRECTORY not in offered:
            wrong.append(f"the command `go` is not offered as itself beside the directory: {offered}")
    else:
        if not _handed(printed := _completed_and_run(shell, work, "filer g"), _DIRECTORY):
            wrong.append(f"`filer g` did not stay the command `go`: {' '.join(printed.split())[-200:]!r}")
        printed = _completed_and_run(shell, work, "filer tw")
        wrong += [
            f"`filer tw` became {half!r}, half of a name" for half in _BROKEN_NAME.split() if _handed(printed, half)
        ]
    if shell == "nushell":  # where names are offered too, the script lists the files itself: each must come back exact
        listed = [word for word in _nushell(work, "filer", "filer ").splitlines() if not word.startswith(("-", "go"))]
        handed = "".join(_run(shell, work, f"filer {candidate}") for candidate in listed)
        names = (*_FILE_NAMES, *_ODD_NAMES)
        wrong += [
            f"listed beside names, {name!r} is not handed over exact" for name in names if not _handed(handed, name)
        ]
    return wrong


_USAGE = """Usage: shell_check.py [--only=<prog>] [<shell>...]

Options:
  --only=<prog>  Drive the cases of one program alone: naval, tool, deployer or filer.
"""


def main() -> int:
    asked = docopt(_USAGE)
    work = Path(tempfile.mkdtemp(prefix="docopt2-shells-"))
    bin_dir = work / "bin"
    bin_dir.mkdir()
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    for prog, doc in _DOCS.items():
        _install(bin_dir, prog, doc)

    # Git Bash on Windows is not a target: the program lands there as a `.cmd` shim a POSIX script cannot
    # invoke. bash/zsh/fish are driven on Linux, PowerShell on Windows.
    wanted = ["powershell"] if platform.system() == "Windows" else ["bash", "zsh", "fish", "nushell"]
    shells = [name for name in wanted if shutil.which(_EXECUTABLE[name]) and name in (asked["<shell>"] or wanted)]
    cases = [case for case in _CASES if asked["--only"] in (None, case[0])]
    if not shells:
        print("no shell available to drive - the check would pass vacuously", file=sys.stderr)
        return 1

    (work / _FILES).mkdir()
    for name in (*_FILE_NAMES, *_ODD_NAMES):
        (work / _FILES / name).write_text("", encoding="utf-8")
    (work / _FILES / _DIRECTORY).mkdir()
    if platform.system() != "Windows":  # which has no such file name
        (work / _FILES / _BROKEN_NAME).write_text("", encoding="utf-8")
    failures = counted = 0
    for shell in shells:
        for prog, doc in _DOCS.items():
            # nushell's module file must not be named `<prog>.nu` (a module cannot export an extern of its
            # own name), so it is saved under another name and `use`d by it.
            suffix = "ps1" if shell == "powershell" else shell
            name = f"{prog}-completions.nu" if shell == "nushell" else f"{prog}.{suffix}"
            (work / name).write_text(generate_completion(doc, prog=prog, shell=shell), encoding="utf-8", newline="\n")
        for prog, typed, cursor in cases:
            expected = complete(_DOCS[prog], [*typed, cursor], schema=_SCHEMAS.get(prog))
            if shell == "bash" and "=" in cursor:  # bash completes the word behind the `=` on its own
                expected = [name.rpartition("=")[2] for name in expected]
            line = " ".join([prog, *typed, cursor])  # the cursor word is typed with no space after it
            if shell == "powershell":
                raw = _powershell(work, prog, line)
            elif shell == "nushell":
                raw = _nushell(work, prog, line)
            else:
                raw = _posix(shell, work, prog, line)
            # not judged: the line's own words, and what bash and zsh put into it (a grown cursor word, a value)
            absent = _everything(prog) - set(expected) - set(line.split())
            absent -= {name.rpartition("=")[2] for name in expected}
            absent -= {name for name in absent if cursor and name.startswith(cursor)}
            failures += _report(f"{shell:11} {line}", expected, raw, absent)
        if shell == "zsh" and asked["--only"] in (None, "naval"):  # the documented $fpath install, on the FIRST Tab
            failures += _report(
                "zsh         naval mine (autoloaded from $fpath)",
                complete(_NAVAL, ["mine", ""]),
                _zsh_autoloaded(work, "naval", ["mine"]),
                _everything("naval") - set(complete(_NAVAL, ["mine", ""])) - {"naval", "mine"},
            )
        if asked["--only"] not in (None, "filer"):
            continue
        drive = {"powershell": _powershell, "nushell": _nushell}.get(shell) or functools.partial(_posix, shell)
        for line, painted, never in _FILE_CASES:
            if line in _OWN_FALLBACK.get(shell, ()):
                continue
            failures += _report_files(f"{shell:11} {line}", painted, never, drive(work, "filer", line))
            counted += 1
        wrong = _odd_names(shell, work)
        print(
            f"{'ok  ' if not wrong else 'FAIL'} {shell:11} odd file names, and a command named as a directory",
            flush=True,
        )
        for line in wrong:
            print(f"       {line}", flush=True)
        failures += bool(wrong)
        raw = drive(work, "filer", "filer zzz --mode ", _ASKED_FROM_THE_PROGRAM[shell])
        label = f"{shell:11} the script asked from the program"
        failures += _report_files(label, ["json", "yaml"], [*_FILE_NAMES], raw)
        counted += 2
    total = len(shells) * len(cases) + ("zsh" in shells and asked["--only"] in (None, "naval")) + counted
    print(f"\n{total - failures} passed, {failures} failed, over {', '.join(shells)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
