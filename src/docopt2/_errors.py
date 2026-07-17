from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from docopt2._diagnostics import use_color

if TYPE_CHECKING:
    from docopt2._diagnostics import Diagnostic
    from docopt2._parser import Pattern


class DocoptLanguageError(Exception):
    """Error in the construction of the usage message by the developer."""


class DocoptExit(SystemExit):
    """Exit because the user invoked the program with incorrect arguments."""

    # Class-level defaults; docopt() passes the real usage/exit_code per instance (no shared-state race).
    usage: str = ""
    exit_code: int = 1

    def __init__(
        self,
        message: str = "",
        *,
        diagnostic: Diagnostic | None = None,
        collected: list[Pattern] | None = None,
        left: list[Pattern] | None = None,
        usage: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """Build the exit.

        ``str(exc)`` stays plain, while the copy the interpreter auto-prints carries color.

        Args:
            message: The plain-text message, used when no ``diagnostic`` is given.
            diagnostic: A rendered ``Diagnostic``. When given, it supplies the message.
            collected: The elements matched before the parse failed, exposing the partial parse.
            left: The argv elements still unconsumed when the parse failed.
            usage: The usage message appended beneath the error. Defaults to the class attribute.
            exit_code: The process status to exit with. Defaults to the class attribute.
        """
        # collected/left are a ported improvement, see NOTICE.
        self.collected: list[Pattern] = collected if collected is not None else []
        self.left: list[Pattern] = left if left is not None else []
        if usage is not None:
            self.usage = usage
        if exit_code is not None:
            self.exit_code = exit_code
        plain = diagnostic.render() if diagnostic is not None else message
        self._message: str = (plain + "\n" + self.usage).strip()
        # exit_code 1 passes a message as SystemExit's code (uncaught -> the interpreter prints str(code) and
        # exits 1). That printed copy is colored when stderr is a terminal; str(exc) keeps the plain text.
        display = diagnostic.render(color=use_color(sys.stderr)) if diagnostic is not None else message
        printable = (display + "\n" + self.usage).strip()
        super().__init__(printable if self.exit_code == 1 else self.exit_code)

    def __str__(self) -> str:
        return self._message
