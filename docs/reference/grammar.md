# Usage grammar

The pattern node classes and low-level parser functions, exported because tools built on docopt reach into
them. The drop-in guarantee covers `docopt()` and the mapping it returns, not these names, which follow
docopt's unreleased master rather than the 0.6.2 spelling. Most programs never touch them; use
[`parse_tree`](docopt.md) for a friendlier entry point into the parse tree.

## Pattern nodes

::: docopt2.Pattern
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.LeafPattern
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.BranchPattern
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.Argument
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.Command
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.Option
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.Required
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.Optional
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.OptionsShortcut
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.Either
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.OneOrMore
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.Tokens
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Parser functions

::: docopt2.formal_usage
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.parse_section
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.parse_defaults
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.parse_pattern
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.parse_argv
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.transform
    options:
      show_root_heading: true
      show_root_toc_entry: true
