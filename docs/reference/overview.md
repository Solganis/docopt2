# Overview

This reference is generated from the source docstrings. It is grouped by API area, mirroring the
exported names in `docopt2.__all__`.

- [docopt & results](docopt.md) - the `docopt` entry point, the `Arguments` mapping, the `Source`
  provenance enum, and `parse_tree`.
- [Cli base class](cli.md) - the class-first `Cli.parse(...)` API.
- [Subcommand dispatch](dispatch.md) - `Dispatch`, routing a matched command path to a handler.
- [Schema stubs](stub.md) - `generate_stub`, codegen for a typed schema.
- [Usage linting](check.md) - `check`, the static usage-grammar linter.
- [Example generation](examples.md) - `generate_examples`, sampling accepted argument vectors.
- [Config templates](config-templates.md) - `generate_config_template`, scaffolding a TOML config file.
- [Shell completion](completion.md) - `complete` and `generate_completion`.
- [Exceptions](exceptions.md) - `DocoptExit` and `DocoptLanguageError`.
- [Usage grammar](grammar.md) - the pattern node classes and low-level `parse_*` primitives
  re-exported for drop-in compatibility with the original docopt.

For a task-oriented view, start from the [Guides](../guides/typed-results.md) instead.

<!-- TODO: keep this list in sync with docopt2.__all__ if the public surface changes. -->
