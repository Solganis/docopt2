import ast
import contextlib
import io
from pathlib import Path

from assertpy2 import assert_that
from hypothesis import given, settings
from pytest import raises

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


_NAVAL = ast.get_docstring(ast.parse(Path(__file__).parent.parent.joinpath("examples/naval_fate.py").read_text()))


@given(argv=argv_strategy(_NAVAL))
@settings(max_examples=200, deadline=None)
def test_the_documented_recipe_runs_on_the_canonical_naval_fate(argv):
    # `argv_strategy`'s docstring ships this recipe. Without `help=False` it draws `['--help']` on any usage
    # declaring `-h`/`--help` - naval-fate does - and docopt answers by printing the doc and exiting the
    # process. Inside a property test that is a SystemExit, and it aborts the whole pytest run.
    docopt(_NAVAL, argv, help=False, complete=False)


def test_the_recipe_needs_help_false_because_the_strategy_can_draw_help():
    # Why the docstring insists on `help=False`: naval-fate declares `-h | --help`, so `--help` is an argv
    # the usage accepts and the strategy will draw it - and docopt answers it by exiting the process.
    with contextlib.redirect_stdout(io.StringIO()), raises(SystemExit):
        docopt(_NAVAL, ["--help"], complete=False)
