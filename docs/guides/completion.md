# Shell completion

Tab completion usually means a second description of your CLI, hand-written in shell, drifting from the real
one the day you add a flag.

docopt2 has no second description. `generate_completion` emits a script for bash, zsh, fish, PowerShell or
nushell that carries **no grammar of its own**. Every Tab is handed back to your program, whose
[`docopt`](../reference/docopt.md) call resolves the candidates from the usage you already wrote.

Suggestions therefore narrow to the matched subcommand instead of offering a flat global list, and they
cannot go stale.

## Generate a script

```python
from docopt2 import generate_completion

script = generate_completion(doc, prog="naval", shell="bash")
```

The signature is `generate_completion(doc, prog, shell="bash") -> str`:

- `shell` is one of `"bash"`, `"zsh"`, `"fish"`, `"powershell"` or `"nushell"`. Any other value raises
  `ValueError`.
- `prog` must be a plain command name: letters, digits, `.`, `_`, `-`. Anything else raises `ValueError`.
- A malformed `doc` fails here, loudly, rather than silently at Tab time.

The script itself is a thin callback. At each Tab it re-invokes your program with a completion request in the
environment, and that program's `docopt` call resolves the tokens legal at the cursor.

So the emitted script depends only on `prog` and `shell`, never on the usage text. For `prog="naval"`, the
bash script is:

```bash
_naval_completion() {
    local -a typed=()
    local index part
    for (( index = 1; index < COMP_CWORD; index++ )); do
        part=${COMP_WORDS[index]}
        if [[ ${#typed[@]} -gt 0 && ( $part == [:=] || ${COMP_WORDS[index-1]} == [:=] ) ]]; then
            typed[$(( ${#typed[@]} - 1 ))]+=$part
        else
            typed+=("$part")
        fi
    done
    local IFS=$'\n'
    local words="${typed[*]}"
    local reply; reply="$(_DOCOPT2_COMPLETE=1 _DOCOPT2_WORDS="$words" "${COMP_WORDS[0]}" 2>/dev/null | cut -f1)"
    COMPREPLY=( $(compgen -W "$reply" -- "${COMP_WORDS[COMP_CWORD]}") )
}
complete -F _naval_completion naval
```

It invokes the command the user typed (`${COMP_WORDS[0]}`), so `naval` must be on `PATH` under the name
you passed as `prog`.

The loop is not decoration. `COMP_WORDBREAKS` contains `=` and `:`, so bash shatters a word at those
characters before the completion function ever sees it:

| the user typed | what bash hands the function |
| --- | --- |
| `--port=8080` | `--port`, `=`, `8080` |
| `host:port` | `host`, `:`, `port` |

Passing those shards to the program would destroy the parse context and silently return no candidates for the
rest of the line. And `--opt=<value>` is exactly the form the usage DSL teaches, so this is the common case,
not an edge one.

bash emits the separator as its own word, so the loop can glue the shards back together unambiguously.

### Installing it

`generate_completion` returns text, and how it reaches the shell is up to you.

Write it to a file you ship, or have the program print it. Then load it with the shell's standard mechanism:

| Shell | `shell=` | Install |
| --- | --- | --- |
| bash | `"bash"` | `source` the file from `~/.bashrc`, or drop it in a `bash-completion` completions directory. |
| zsh | `"zsh"` | `source` it from `~/.zshrc`, or save it as `_naval` on your `$fpath`. |
| fish | `"fish"` | Save it as `~/.config/fish/completions/naval.fish`. |
| PowerShell | `"powershell"` | Dot-source it from your `$PROFILE`. |
| nushell | `"nushell"` | Save it under a name that is **not** `naval.nu` (a module cannot export a command of its own name), then `use naval-completions.nu *` from your config, or drop it in a `$nu.vendor-autoload-dirs` directory. Needs nushell 0.108+. |

!!! note
    Each Tab is a full launch of your program, so its startup cost (imports and so on) *is* the completion
    latency.

    `docopt()` answers the request and exits before returning. Keep heavy work after the `docopt()` call and
    it never runs during completion.

## Answering requests

A docopt program answers the completion script's requests by default. When completion fires:

1. The script puts a trigger variable, and the newline-joined tokens before the cursor, in the environment.
2. It re-invokes your program.
3. Your `docopt()` call detects the trigger, prints the candidates, and exits before returning to your code.

A normal run costs a single environment lookup and is otherwise unaffected.

A program that does not want this opts out with `docopt(..., complete=False)`, which skips the check entirely
and always parses `argv` normally.

## Computing candidates directly

`complete(doc, words)` returns the completion candidates for the last (cursor) word. It is the primitive the
generated scripts call.

Earlier tokens are consumed against the usage pattern, then the command literals and option names that could
legally come next are returned, filtered to the partial word. Positional values are never suggested.

A malformed doc, or a prefix ending mid-option-argument, yields no candidates rather than raising into the
shell.

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

Each call narrows to what the usage actually allows at that point:

- **After `ship`**, only that branch's continuations are offered: the `new` and `shoot` commands, plus the
  floating `--speed`. `move` is absent, because it sits behind the `<name>` positional, and `<name>` itself is
  never suggested.
- **After the two coordinates of `mine set`**, only its remaining flags are left.

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
