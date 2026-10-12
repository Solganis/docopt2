from assertpy2 import assert_that
from hypothesis import given, settings
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


_PIECES = st.sampled_from(["a", "b", "<x>", "-f", "--o=<v>"])
_USAGES = st.recursive(
    _PIECES,
    lambda inner: st.one_of(
        st.tuples(inner, inner).map(" ".join),
        inner.map("[{}]".format),
        st.tuples(inner, inner).map(lambda pair: f"({pair[0]} | {pair[1]})"),
        inner.map("({})...".format),
    ),
    max_leaves=4,
)


def _read_as_the_command(doc, full, cut):
    """Whether the parse reads the word at ``cut`` as the command it names: with another word in its place the
    argv is refused, or the command is given fewer times."""
    try:
        without = docopt(doc, [*full[:cut], "zz", *full[cut + 1 :]], help=False, complete=False)
    except DocoptExit:
        return True
    return without[full[cut]] != docopt(doc, full, help=False, complete=False)[full[cut]]


def test_a_word_that_may_be_a_command_or_the_value_of_a_positional_is_read_and_offered_as_the_command():
    doc = "Usage: prog (a | <x>)"
    assert_that(dict(docopt(doc, ["a"], help=False, complete=False))).is_equal_to({"a": True, "<x>": None})
    assert_that(_read_as_the_command(doc, ["a"], 0)).is_true()
    assert_that(complete(doc, [""])).is_equal_to(["a"])
    # the second `a` is the value of `<x>`: another word in its place changes nothing else
    assert_that([_read_as_the_command("Usage: prog a <x>", ["a", "a"], cut) for cut in (0, 1)]).is_equal_to(
        [True, False]
    )


@settings(max_examples=200)  # 3 ms an example
@given(lines=st.lists(_USAGES, min_size=1, max_size=2), data=st.data())
def test_completion_offers_every_literal_an_argv_of_a_generated_usage_has_next(lines, data):
    doc = "Usage:\n" + "".join(f"  prog {line}\n" for line in lines)
    # an option is read wherever it stands: behind the positionals, a round of a repetition leaves its own for later
    behind = data.draw(st.sampled_from([None, True, False]))
    full = sorted(
        data.draw(argv_strategy(doc)), key=lambda token: behind is not None and token.startswith("-") is behind
    )
    for cut, token in enumerate(full):
        name = token.split("=")[0]
        if name in ("-f", "--o") or (name in ("a", "b") and _read_as_the_command(doc, full, cut)):
            offered = complete(doc, [*full[:cut], ""])
            assert name in offered, f"{doc}after {full[:cut]} the argv {full} has {name!r}, and {offered} was offered"
