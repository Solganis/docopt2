# Exceptions

docopt2's own exception types: one for a failed parse of argv, one for a malformed usage. See the
[Diagnostics](../guides/diagnostics.md) guide for what they render.

Misuse of the API itself, an unsupported shell name or a program name with shell metacharacters, raises a
plain `ValueError` instead.

::: docopt2.DocoptExit
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.DocoptLanguageError
    options:
      show_root_heading: true
      show_root_toc_entry: true
