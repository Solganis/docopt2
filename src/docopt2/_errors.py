from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
        collected: list[Pattern] | None = None,
        left: list[Pattern] | None = None,
        usage: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """Build the exit; ``collected``/``left`` expose the partial parse (a ported improvement; see NOTICE),
        ``usage``/``exit_code`` default to the class attributes when omitted."""
        self.collected: list[Pattern] = collected if collected is not None else []
        self.left: list[Pattern] = left if left is not None else []
        if usage is not None:
            self.usage = usage
        if exit_code is not None:
            self.exit_code = exit_code
        self._message: str = (message + "\n" + self.usage).strip()
        # exit_code 1 passes the message as SystemExit's code (uncaught -> prints it, exits 1). A custom
        # code exits with that status; SystemExit auto-prints only a string, so the message rides on str(exc).
        super().__init__(self._message if self.exit_code == 1 else self.exit_code)

    def __str__(self) -> str:
        return self._message
