# Long-option typo suggestions via Levenshtein edit distance; a ported improvement, see NOTICE.
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from docopt2._parser import Option

# Normalized edit distance below which a mistyped option is treated as a likely typo.
_SIMILARITY_THRESHOLD = 0.34


def _levenshtein(source: str, target: str) -> int:
    """Optimal string-alignment (Damerau) edit distance; a ported improvement (see NOTICE).

    Counts an adjacent transposition as one edit, so a common typo like ``inof`` for ``info`` stays close.
    """
    source_range = range(len(source) + 1)
    target_range = range(len(target) + 1)
    matrix = [[(row if column == 0 else column) for column in target_range] for row in source_range]
    for row in source_range[1:]:
        for column in target_range[1:]:
            substitution = 0 if source[row - 1] == target[column - 1] else 1
            matrix[row][column] = min(
                matrix[row - 1][column] + 1,
                matrix[row][column - 1] + 1,
                matrix[row - 1][column - 1] + substitution,
            )
            if (
                row > 1
                and column > 1
                and source[row - 1] == target[column - 2]
                and source[row - 2] == target[column - 1]
            ):
                matrix[row][column] = min(matrix[row][column], matrix[row - 2][column - 2] + 1)  # transposition
    return matrix[len(source)][len(target)]


def _closest(name: str, known: Iterable[str]) -> str | None:
    """Return the known option most similar to ``name``, if within the threshold."""
    ranked = sorted((_levenshtein(name, candidate) / max(len(name), len(candidate)), candidate) for candidate in known)
    if ranked and ranked[0][0] < _SIMILARITY_THRESHOLD:
        return ranked[0][1]
    return None


def suggest_option(tokens: Sequence[str], options: list[Option], allow_abbrev: bool = True) -> tuple[str, str] | None:
    """Find the first unrecognized long option in ``tokens`` and its closest known match, or None.

    A token is recognized if it is an exact known long option or, with ``allow_abbrev``, a prefix of
    one, so this fires only on genuine typos.
    """
    known = [long for option in options if (long := option.long) is not None]
    for token in tokens:
        if not token.startswith("--") or token == "--":
            continue
        name = token.split("=", 1)[0]
        prefixed = [candidate for candidate in known if candidate.startswith(name)]
        if name in known or (allow_abbrev and prefixed):
            continue
        # With abbreviations off, an unambiguous prefix is the option the user meant to abbreviate.
        if not allow_abbrev and len(prefixed) == 1:
            return name, prefixed[0]
        suggestion = _closest(name, known)
        if suggestion is not None:
            return name, suggestion
    return None
