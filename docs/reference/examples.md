# Example generation

Sample argument vectors from the usage grammar: concrete invocations your usage accepts, as data you
can diff, replay, or fuzz against. See the [Example generation](../guides/examples.md) guide.

::: docopt2.generate_examples
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Hypothesis strategy

`argv_strategy` lives in `docopt2.hypothesis` and needs the optional `docopt2[hypothesis]` extra.

::: docopt2.hypothesis.argv_strategy
    options:
      show_root_heading: true
      show_root_toc_entry: true
