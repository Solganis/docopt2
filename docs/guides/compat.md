# Compatibility checking

Your usage message *is* your command-line interface. Drop a flag or add a required argument, and every script,
CI job and muscle-memory invocation that calls your program breaks. It breaks on their next run, not on
yours, which is why it is easy to ship.

[`check_compat`](../reference/compat.md) (and the `docopt2 compat` CLI) compares two versions of a usage
message and reports the **backward-incompatible** changes: invocations the old usage accepts that the new one
would reject.

```python
from docopt2 import check_compat

old = "Usage: git push [--force] <remote>"
new = "Usage: git push <remote> <branch>"

check_compat(old, new)
# ['option `--force` removed',
#  '`push v1` no longer accepted']
```

Two changes broke the interface here. `--force` is gone, and a new required `<branch>` means `git push origin`
no longer parses.

The reverse is quiet on purpose. Adding an *optional* flag, a new usage line, or a new subcommand breaks
nothing, so none of it is reported.

## What it reports, and how far to trust it

Entries come most-reliable first, and every one is a **definite** break:

- **Structural, named:** a removed option or command (`option `--force` removed`). These are read straight
  off the two grammars.
- **Concrete counterexamples:** an argument vector the old usage accepts that the new one rejects
  (`` `push v1` no longer accepted``). These are found by sampling the old grammar's accepted set and
  replaying it against the new, so each one is a real invocation you can paste and confirm.

The counterexamples are deduplicated: many equivalent argvs collapse to one representative, and an argv that
a named break already explains is not repeated.

!!! warning "An empty result is 'no break found', not 'compatible'"
    The set of accepted invocations is infinite, and `check_compat` samples it.

    So an empty list means *no breaking change was detected*, the way a passing test means *no failure was
    observed*. It is never a proof of compatibility.

    `check_compat` never claims a change is safe. It only surfaces the breaks it can prove. Treat it as a fast
    guard against the common regressions, not a formal verifier.

## From the command line

`docopt2 compat <old-source> <new-source>` prints one break per line and exits non-zero if any are found, so
it drops into CI or a pre-release check like a linter.

Each `<source>` is a `.py` module docstring, a usage text file, or `-` for standard input.

<div class="docopt2-term"><span class="dt-fg">$ docopt2 compat old-usage.txt new-usage.txt</span>
<span class="dt-fg">option `--force` removed</span>
<span class="dt-fg">`push v1` no longer accepted</span></div>

It is silent and exits `0` when no break is found, so `docopt2 compat before.txt after.txt` in a release
gate fails the build precisely when a change would break a caller.

## See also

- [`check_compat`](../reference/compat.md) in the API reference.
- [Example generation](examples.md) - the accepted-set sampler `check_compat` replays against the new usage.
- [Usage linting](check.md) - the single-spec counterpart, checking one usage for defects.
