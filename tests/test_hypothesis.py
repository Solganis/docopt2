from assertpy2 import assert_that
from hypothesis import given, settings

from docopt2 import DocoptLanguageError, docopt
from docopt2.hypothesis import _DrawChooser, argv_strategy

# One doc exercising every choice point the walk makes: an alternation of usage lines and an inline
# `(add | rm)` (choice), a `<name>...` repetition (integer), and `[--speed]`/`[--force]` optionals (boolean).
_DOC = (
    "Usage:\n"
    "  prog ship new <name>...\n"
    "  prog ship <name> move <x> <y> [--speed=<kn>]\n"
    "  prog (add | rm) <x> [--force]\n\n"
    "Options:\n  --speed=<kn>  Speed.\n  --force  Force.\n"
)


@given(argv=argv_strategy(_DOC))
@settings(max_examples=50, deadline=None)  # deadline off: first draw folds in import/compile time on CI
def test_every_drawn_argv_parses(argv):
    docopt(_DOC, argv, help=False, complete=False)  # raises DocoptExit if the strategy ever diverges


def test_argv_strategy_rejects_a_malformed_usage_at_construction():
    assert_that(argv_strategy).raises(DocoptLanguageError).when_called_with("usage: prog (a]")


def test_draw_chooser_routes_each_decision_through_the_draw():
    # Deterministic cover of all three chooser methods, independent of what Hypothesis happens to explore.
    seen = []
    chooser = _DrawChooser(lambda strategy: seen.append(strategy) or "drawn")
    assert_that(chooser.choice(["a", "b"])).is_equal_to("drawn")
    assert_that(chooser.integer(1, 2)).is_equal_to("drawn")
    assert_that(chooser.boolean()).is_equal_to("drawn")
    assert_that(seen).is_length(3)
