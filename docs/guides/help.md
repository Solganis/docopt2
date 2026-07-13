# Rich help

By default `--help` prints your usage message verbatim, exactly as docopt does - the help text you wrote
*is* what the user sees. Opt into `help_style="rich"` and docopt2 renders an aligned, colored help screen
that **documents where each value resolves from** and is **scoped to the command path** the user typed -
all from the same annotations docopt2 already reads.

```python
from docopt2 import docopt

docopt(doc, help_style="rich")   # -h/--help now renders the rich screen
```

## Value provenance

The differentiator: rich help pulls the `[env: ...]`, `[config: ...]`, and `[default: ...]` annotations
out of each option's description and renders them as a dimmed **resolution chain**, in the same precedence
order docopt2 resolves them - command-line argument, then environment, then config, then default. Given:

```text
Serve a directory over HTTP.

Usage:
  serve [--port=<n>] [--host=<h>] [--log=<lvl>] <root>

Options:
  --port=<n>  Port to bind [default: 8080] [env: PORT] [config: server.port].
  --host=<h>  Interface to bind [default: 127.0.0.1] [env: HOST].
  --log=<lvl>  Log verbosity [default: info] [config: logging.level].
```

`serve --help` renders each option's human description clean, with its sources spelled out beside it:

<div class="docopt2-term"><span class="dt-fg">Serve a directory over HTTP.</span>

<span class="dt-fg dt-b">Usage:</span>
<span class="dt-fg">  serve [--port=&lt;n&gt;] [--host=&lt;h&gt;] [--log=&lt;lvl&gt;] &lt;root&gt;</span>

<span class="dt-fg dt-b">Options:</span>
<span class="dt-fg">  </span><span class="dt-help">--port=&lt;n&gt; </span><span class="dt-fg">  Port to bind.</span><span class="dt-dim">  [env: PORT, config: server.port, default: 8080]</span>
<span class="dt-fg">  </span><span class="dt-help">--host=&lt;h&gt; </span><span class="dt-fg">  Interface to bind.</span><span class="dt-dim">  [env: HOST, default: 127.0.0.1]</span>
<span class="dt-fg">  </span><span class="dt-help">--log=&lt;lvl&gt;</span><span class="dt-fg">  Log verbosity.</span><span class="dt-dim">  [config: logging.level, default: info]</span></div>

No other CLI library surfaces the resolution chain in `--help`: their sources are wired imperatively and
scattered across the code. In docopt2 they live in the usage text, so the help documents itself, for free.
See [Layered value resolution](usage-dsl.md#environment-and-config-fallback) for how the chain resolves.

## Scoped to the subcommand

Rich help also narrows to the subcommand: `prog <sub> --help` shows only the usage lines for `<sub>` and
the options they use. For a `git`-shaped CLI, `git commit --help` drops `push` and `--force` entirely:

<div class="docopt2-term"><span class="dt-fg">Git.</span>

<span class="dt-fg dt-b">Usage:</span>
<span class="dt-fg">  git commit [--message=&lt;msg&gt;] [--amend]</span>

<span class="dt-fg dt-b">Options:</span>
<span class="dt-fg">  </span><span class="dt-help">--message=&lt;msg&gt;</span><span class="dt-fg">  Commit message to record.</span>
<span class="dt-fg">  </span><span class="dt-help">--amend        </span><span class="dt-fg">  Amend the last commit.</span></div>

The scope is every positional token in the argv that is a command literal in the usage (here, `commit`);
the usage narrows to the lines that carry all of them. Position does not matter - `--help commit` scopes
the same as `commit --help`. A path that matches no single line, or no path at all, shows the whole usage.

## Raw by default

`help_style` defaults to `"raw"`, so nothing changes unless you opt in: the usage message prints exactly
as written, preserving docopt's what-you-write-is-what-they-see contract. `"rich"` adds the color above
when the output is a terminal (and plain text when piped), and any other value raises `ValueError`.

!!! note "Zero dependencies"
    The rich screen is rendered by docopt2 itself, reusing the same ANSI styling as the
    [diagnostics](diagnostics.md) - no `rich`, no config, no new dependency.

## See also

- [`docopt`](../reference/docopt.md) and its `help_style` parameter.
- [Layered value resolution](usage-dsl.md#environment-and-config-fallback) - the sources the chain documents.
- [Subcommand dispatch](dispatch.md) - routing the command paths the help scopes to.
