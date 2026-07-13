from hypothesis import given
from hypothesis import strategies as st

from docopt2 import Command, Option, complete, docopt, parse_defaults, parse_pattern
from docopt2._core import formal_tokens
from docopt2._errors import DocoptExit
from docopt2._parser import single_usage_section
from docopt2.hypothesis import argv_strategy

# Checking the shells against `complete()` only proves the scripts relay it faithfully - `complete()` is
# itself the product, so a hole in the resolver stays invisible. The ground truth is `docopt()`: a
# candidate is right only if some argv that begins with the typed tokens plus that candidate parses.

_DOCS = [
    "Usage:\n  git push [--force] <remote>\n  git commit --message=<msg>\n  git add <path>...\n\n"
    "Options:\n  --force          Force.\n  --message=<msg>  Message.\n",
    "Usage:\n  git remote add <name> <url>\n  git remote rm <name>\n  git push <remote>\n",
    "Usage:\n  tool db (up|down) <steps>\n  tool serve <port> [--reload]\n\nOptions:\n  --reload  Reload.\n",
    "Usage:\n  tool build <target>\n  tool test [--fast]\n  tool deploy <env> <version>\n\nOptions:\n  --fast  Fast.\n",
]


def _literals(doc):
    """Every command and option the usage writes down: the tokens completion is allowed to offer."""
    pattern = parse_pattern(formal_tokens(single_usage_section(doc)), parse_defaults(doc))
    return {leaf.name for leaf in pattern.flat() if isinstance(leaf, Command | Option) and leaf.name}


@given(data=st.data())
def test_completion_offers_every_literal_a_valid_argv_uses_next(data):
    # Completeness against the grammar, not against ourselves: walk a VALID argv, and wherever its next
    # token is a literal, completion must offer that literal. A resolver that silently drops a reachable
    # command or option cannot survive this, however faithfully the shell scripts relay it.
    doc = data.draw(st.sampled_from(_DOCS))
    full = data.draw(argv_strategy(doc))
    literals = _literals(doc)
    for cut in range(len(full)):
        name = full[cut].split("=")[0]
        if name not in literals:
            continue  # a positional VALUE: never suggested, by design
        offered = complete(doc, [*full[:cut], ""])
        assert name in offered, f"after {full[:cut]} a valid argv uses {name!r}, but completion offered {offered}"


def _parses(doc, argv):
    try:
        docopt(doc, argv, help=False, complete=False)
    except DocoptExit:
        return False
    return True


def _extendable(doc, typed, depth=3):
    """Whether some valid argv still begins with ``typed``. docopt() rules on it, never complete().

    The search may append the doc's own literals as well as a placeholder positional value, because docopt
    lets an option precede the command it belongs to (`git --force push origin` parses): a candidate that
    still needs a command after it is a live prefix, not a dead end.
    """
    tokens = [*sorted(_literals(doc)), "x"]
    frontier = [list(typed)]
    for _ in range(depth + 1):
        if any(_parses(doc, argv) for argv in frontier):
            return True
        frontier = [[*argv, token] for argv in frontier for token in tokens]
    return False


@given(data=st.data())
def test_every_candidate_offered_can_actually_be_typed_next(data):
    # Soundness against the grammar: a candidate must be a real continuation, never a dead end the user is
    # walked into. `docopt()` rules on it, so a resolver that invents a token cannot hide behind complete().
    doc = data.draw(st.sampled_from(_DOCS))
    full = data.draw(argv_strategy(doc))
    cut = data.draw(st.integers(min_value=0, max_value=len(full)))
    typed = full[:cut]
    for candidate in complete(doc, [*typed, ""]):
        extended = [*typed, candidate]
        assert _extendable(doc, extended), f"offered {candidate!r} after {typed}, but {extended} is a dead end"
