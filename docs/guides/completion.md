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
    local current=${COMP_WORDS[COMP_CWORD]}
    local last=$(( ${#typed[@]} - 1 ))
    if [[ $current == = ]]; then
        current=
    elif [[ $last -ge 0 && ${COMP_WORDS[COMP_CWORD-1]} == = ]]; then
        typed[$last]=${typed[$last]%=}
    fi
    local IFS=$'\n'
    local words="${typed[*]}"
    local reply; reply="$(_DOCOPT2_COMPLETE=2 _DOCOPT2_WORDS="$words" "${COMP_WORDS[0]}" 2>/dev/null)"
    COMPREPLY=( $(compgen -W "$(cut -f1 <<< "$reply")" -- "$current") )
    if [[ $reply == $'\t'* ]]; then
        local -a files=()
        local file
        while IFS= read -r file; do
            [[ -e ${file/#\~\//$HOME/} || -L $file ]] && files+=("$file")
        done <<< "$(compgen -f -- "$current")"
        if [[ ${#COMPREPLY[@]} -eq 0 ]]; then
            type compopt &>/dev/null && compopt -o filenames
            COMPREPLY=( "${files[@]}" )
        else
            for file in "${files[@]}"; do
                [[ -d $file ]] && file+=/
                COMPREPLY+=( "$(printf '%q' "$file")" )
            done
        fi
    fi
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

The lines after the loop are for a cursor that stands in the value of `--opt=`. bash completes what
stands behind the `=` on its own, so the program is asked as if `--opt` were waiting for its argument,
and the value alone is the word to complete.

The last lines are for file names. A reply that opens with a tab asks for them, and the script adds what
`compgen -f` finds. [Completing file names](#completing-file-names) says where that is.

- The names are read a line at a time, since an unquoted `$(compgen -f)` would expand `[x].txt` as a
  pattern. A line that is no file is dropped: it is a piece of a name that holds a newline.
- Where files are all there is, `compopt -o filenames` lets bash quote them and mark directories. Beside
  names the script does that itself: the option would put a slash after a command that is named as a
  directory.

### Installing it

A program that calls `docopt()` prints its own script, with no line of code for it. Set
`_DOCOPT2_COMPLETE` to the name of a shell and run the program:

| Shell | Load the script into the running shell |
| --- | --- |
| bash | `eval "$(_DOCOPT2_COMPLETE=bash naval)"` |
| zsh | `eval "$(_DOCOPT2_COMPLETE=zsh naval)"` |
| fish | `_DOCOPT2_COMPLETE=fish naval \| source` |
| PowerShell | `$env:_DOCOPT2_COMPLETE = 'powershell'; naval \| Out-String \| Invoke-Expression; Remove-Item Env:_DOCOPT2_COMPLETE` |
| nushell | `_DOCOPT2_COMPLETE=nushell naval \| save -f naval-completions.nu`, then `use naval-completions.nu *` |

The script is written for the program the usage names: the first word after `Usage:`, without its
directory. A program installed under another name calls `generate_completion(doc, prog=...)` itself.
A `Dispatch` table answers the same request. `docopt(..., complete=False)` does not.

To keep the script, save that output to a file, or call `generate_completion` and write the text where you
ship it. Then load it with the shell's standard mechanism:

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

The trigger also says what the script can read. A script asks with the value `2`, and where a file name may
come next the reply then opens with one more line: a tab and the word `files`. A script written by an older
docopt2 asks with `1` and is never sent that line. A program on an older docopt2 never sends it either. So
either half can be updated alone.

A normal run costs a single environment lookup and is otherwise unaffected.

A program that does not want this opts out with `docopt(..., complete=False)`, which skips the check entirely
and always parses `argv` normally.

## Computing candidates directly

`complete(doc, words)` returns the completion candidates for the last (cursor) word. It is the primitive the
generated scripts call.

Earlier tokens are consumed against the usage pattern, then the command literals and option names that could
legally come next are returned, filtered to the partial word. A value is suggested only with a schema, as
[Completing values](#completing-values) shows.

A malformed doc yields no candidates rather than raising into the shell. So does a prefix that ends on an
option waiting for its argument, unless a schema gives that option a closed set of values.

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
  floating `--speed`. `move` is absent, because it sits behind the `<name>` positional, and `<name>` takes any
  text, so there is nothing to suggest for it.
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

## Completing values

Commands and option names come from the usage. A value can be completed too, where a
[schema](typed-results.md) says which values there are: a field typed as a `Literal` or an `Enum`.

```python
import dataclasses
from typing import Literal
from docopt2 import complete

@dataclasses.dataclass
class Args:
    env: Literal["dev", "staging", "prod"]
    format: Literal["json", "yaml"] | None

doc = "Usage: app <env> [--format=<f>]\n\nOptions:\n  --format=<f>  Output format."

complete(doc, [""], schema=Args)
# ['--format', '--format=json', '--format=yaml', 'dev', 'prod', 'staging']

complete(doc, ["prod", "--format", ""], schema=Args)
# ['json', 'yaml']

complete(doc, ["prod", "--format=y"], schema=Args)
# ['--format=yaml']
```

Such a field completes in three places: as the next positional, as the argument the last option is waiting
for, and as `--option=value` beside the option's own name.

The next positional is the one the parser would give the next word to. With `Usage: app [<name>] [<mode>]`
a word typed first is a `<name>`, whatever it says. So the modes are offered once a name stands, and not
before it.

A program gets this with no extra call. `docopt(doc, schema=Args)`, a `Cli` subclass and a `Dispatch`
table with a schema per handler all answer the script's request with these values in the reply. A table
completes a line by the schema of the handler that the typed words leave to be run, as its guide
[shows](dispatch.md#completing-values).

Only a value that the field's own coercion accepts, and that is one plain word, is offered: letters,
digits and `_ . / @ % + , -`, not led by a dash. That leaves out what a shell would expand or split,
what bash breaks a word at, and what an argv reads as an option. A field of any other type, a `str` or
an `int`, completes nothing. A `Path` completes [file names](#completing-file-names).

A dataclass, a `TypedDict` or a `Cli` subclass reads the words already typed too. After a positional or an
option value that its field does not take, nothing is offered: no argv that starts that way can be bound.

A pydantic model does not judge what is typed: it binds by rules of its own, validators included. For
the same reason it completes its closed sets of strings only: it refuses the text `1` for `Literal[1, 2]`.

A `Dispatch` table judges the typed words by the schema of the one handler they leave to be run. While
they leave several, a positional is completed by the handler that is run for the line as it would be
finished. Its guide [shows](dispatch.md#completing-values) both.

## Completing file names

Once a completion script is loaded, the shell stops offering file names for that program: every Tab is
answered by the program, and the usage does not say which argument is a file. A schema does. A field typed
as a `Path` gets the shell's own file names.

```python
import dataclasses
import pathlib
from typing import Literal

@dataclasses.dataclass
class Args:
    go: bool
    file: pathlib.Path
    out: pathlib.Path | None
    mode: Literal["json", "yaml"] | None
    name: str | None

doc = "Usage: filer [go] <file> [--out=<path>] [--mode=<m>] [--name=<n>]"
```

In a directory that holds `notes.txt` and `other.log`:

| typed, then Tab | offered |
| --- | --- |
| `filer no` | `notes.txt` |
| `filer ` | `go`, the options, `notes.txt`, `other.log` |
| `filer notes.txt --out ot` | `other.log` |
| `filer notes.txt --mode ` | `json`, `yaml` |
| `filer notes.txt --name ` | nothing |

- A field is a path where its annotation is `pathlib.Path`: alone, in `Annotated`, as a member of a union,
  or as the element of a list.
- Where a command or an option may come next too, names and file names are offered together. A command
  that is also the name of a directory stays a command: both are offered.
- A `Dispatch` table asks for file names where the handler that the typed words leave to be run types the
  field as a `Path`. Where they leave several, a positional is a path where the handler run for the finished
  line types it so, and the argument of an option where each of them that declares the field does.
- In bash, zsh, fish and nushell a field of any other type gets no file names, and neither does a program
  with no schema.

Three things differ between shells:

- PowerShell offers file names by itself wherever a completer returns nothing. So there a `str` field, a
  program with no schema and a line that nothing can follow get file names too, as they did before.
- Behind `--out=`, with no space, only bash completes a file name. In zsh, fish, PowerShell and nushell,
  write `--out`, a space, and the name.
- The names are the shell's own, with its quoting. Beside names bash and nushell cannot mix their own list
  in, so there the script lists the files and quotes them: bash with `printf %q`, nushell as it writes any
  string. PowerShell's names lose the escapes it adds for its own providers, which a program would be handed
  as text. A name that holds a newline is left out by bash and fish.

`complete()` returns names only. File names never appear in its result.

## See also

- [`complete` and `generate_completion`](../reference/completion.md) in the API reference.
- The `complete=` flag on [`docopt`](../reference/docopt.md).
- [Usage DSL](usage-dsl.md) - the grammar the candidates are resolved from.
