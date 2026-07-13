# Exceptions

docopt2's own exception types: one for a failed parse of argv, one for a malformed usage. (Misuse of the
API itself - an unsupported shell name, a program name with shell metacharacters - raises `ValueError`.)

::: docopt2.DocoptExit
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: docopt2.DocoptLanguageError
    options:
      show_root_heading: true
      show_root_toc_entry: true
