from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

from hypothesis import strategies as st

from docopt2._generate import _sample, _usage_pattern

if TYPE_CHECKING:
    from hypothesis.strategies import DrawFn, SearchStrategy

    from docopt2._parser import Pattern


class _DrawChooser:
    """Drives the pattern walk from a Hypothesis draw, so every choice shrinks on its own.

    Because each branch pick, repeat count, and coin flip is a separate draw, Hypothesis can shrink a
    failing argv toward a minimal one: drop optionals, take first alternatives, fewest repeats.
    """

    def __init__(self, draw: DrawFn) -> None:
        self._draw = draw

    def choice(self, options: list[Pattern]) -> Pattern:
        return self._draw(st.sampled_from(options))

    def integer(self, low: int, high: int) -> int:
        return self._draw(st.integers(min_value=low, max_value=high))

    def boolean(self) -> bool:
        return self._draw(st.booleans())


def argv_strategy(doc: str) -> SearchStrategy[list[str]]:
    """A Hypothesis strategy of argument vectors the usage message accepts.

    Every drawn argv is one :func:`docopt2.docopt` parses, so you can property-test a program against
    its own usage without hand-writing inputs. Map the strategy through ``docopt`` to drive downstream
    code with parsed results::

        from hypothesis import given
        from docopt2 import docopt
        from docopt2.hypothesis import argv_strategy

        @given(argv_strategy(DOC))
        def test_never_crashes(argv):
            run(docopt(DOC, argv))

    Requires the ``docopt2[hypothesis]`` extra. Raises :class:`~docopt2.DocoptLanguageError` at once
    on a malformed usage, before any example is drawn.
    """
    pattern = _usage_pattern(doc)  # eager, so a malformed usage fails here, not mid-draw

    @st.composite
    def _build(draw: DrawFn) -> list[str]:
        return _sample(pattern, _DrawChooser(draw), itertools.count(1))

    return _build()
