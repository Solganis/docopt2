# Shell completion

`generate_completion` emits a context-aware completion script for the CLI described by your usage, for
bash, zsh, fish, and PowerShell - the same four Click and Typer support. The script carries no grammar of
its own: it delegates every Tab back to your program, whose [`docopt`](../reference/docopt.md) call
resolves the candidates from the usage. This guide covers generating and installing that script, and
computing the candidates directly with `complete()`.

## Generate a script

```python
from docopt2 import generate_completion

script = generate_completion(doc, prog="naval", shell="bash")
```

The signature is `generate_completion(doc, prog, shell="bash") -> str`. `shell` is one of `"bash"`,
`"zsh"`, `"fish"`, or `"powershell"`; any other value raises `ValueError`, as does a `prog` that is not a
plain command name (letters, digits, `.`, `_`, `-`). A malformed `doc` fails here, loudly, rather than
silently at Tab time.

The script is a thin callback: at each Tab it re-invokes the program with a completion request in the
environment, and the program's [`docopt`](../reference/docopt.md) call resolves the tokens legal at the
cursor from the usage grammar. Suggestions therefore narrow to the matched subcommand's options and
arguments, not a flat global list.

Because the grammar lives in the program, the emitted script depends only on `prog` and `shell`, never on
the usage text. For `prog="naval"`, the bash script is:

```bash
_naval_completion() {
    local IFS=$'\n'
    local words="${COMP_WORDS[*]:1:COMP_CWORD-1}"
    local reply; reply="$(_DOCOPT2_COMPLETE=1 _DOCOPT2_WORDS="$words" "${COMP_WORDS[0]}")"
    COMPREPLY=( $(compgen -W "$reply" -- "${COMP_WORDS[COMP_CWORD]}") )
}
complete -F _naval_completion naval
```

It invokes the command the user typed (`${COMP_WORDS[0]}`), so `naval` must be on `PATH` under the name
you passed as `prog`.

### Installing it

`generate_completion` returns text; how it reaches the shell is up to you. Write it to a file you ship, or
have the program print it, then load it with the shell's standard mechanism:

| Shell | `shell=` | Install |
| --- | --- | --- |
| bash | `"bash"` | `source` the file from `~/.bashrc`, or drop it in a `bash-completion` completions directory. |
| zsh | `"zsh"` | `source` it from `~/.zshrc`, or save it as `_naval` on your `$fpath`. |
| fish | `"fish"` | Save it as `~/.config/fish/completions/naval.fish`. |
| PowerShell | `"powershell"` | Dot-source it from your `$PROFILE`. |

!!! note
    Each Tab is a full launch of your program, so its startup cost (imports and so on) is the completion
    latency. `docopt()` answers the request and exits before returning, so keep heavy work after the
    `docopt()` call and it never runs during completion.

## Answering requests

A docopt program answers the completion script's requests by default. When completion fires, the script
sets a trigger variable and the newline-joined tokens before the cursor in the environment and re-invokes
the program; your `docopt()` call detects the trigger, prints the candidates, and exits before returning
to your code. A normal run costs a single environment lookup and is otherwise unaffected.

A program that does not want this opts out with `docopt(..., complete=False)`, which skips the check
entirely and always parses `argv` normally.

## Computing candidates directly

`complete(doc, words)` returns the completion candidates for the last (cursor) word - the primitive the
generated scripts call. Earlier tokens are consumed against the usage pattern, then the command literals
and option names that could legally come next are returned, filtered to the partial word. Positional
values are never suggested. A malformed doc, or a prefix ending mid-option-argument, yields no candidates
rather than raising into the shell.

```python
from docopt2 import complete

doc = """Usage:
  naval ship new <name>...
  naval ship <name> move <x> <y> [--speed=<kn>]
  naval ship shoot <x> <y>
  naval mine (set|remove) <x> <y> [--moored|--drifting]
  naval --help
  naval --version

Options:
  --speed=<kn>  Speed in knots [default: 10].
  --moored      Moored (anchored) mine.
  --drifting    Drifting mine."""

complete(doc, [""])
# ['--drifting', '--help', '--moored', '--speed', '--version', 'mine', 'ship']

complete(doc, ["ship", ""])
# ['--speed', 'new', 'shoot']

complete(doc, ["mine", ""])
# ['--drifting', '--moored', 'remove', 'set']

complete(doc, ["mine", "set", "1", "2", ""])
# ['--drifting', '--moored']
```

After `ship`, only that branch's continuations are offered: the `new` and `shoot` commands, plus the
floating `--speed`. The `move` command is not, because it sits behind the `<name>` positional, and
`<name>` itself is never suggested. After the two coordinates of `mine set`, only its remaining flags are
left.

The last word filters the candidates by prefix, exactly as the shell would:

```python
complete(doc, ["s"])     # ['ship']
complete(doc, ["--m"])   # ['--moored']
```

And the never-raise guarantee, so a broken usage can never break the user's shell:

```python
complete("not a usage message", [""])                   # []
complete("Usage: prog --speed=<kn>", ["--speed", ""])   # []
```

## See also

- [`complete` and `generate_completion`](../reference/completion.md) in the API reference.
- The `complete=` flag on [`docopt`](../reference/docopt.md).
- [Usage DSL](usage-dsl.md) - the grammar the candidates are resolved from.
