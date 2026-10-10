import pytest
from assertpy2 import assert_that

from docopt2._parser import (
    MATCH_LIMIT,
    Argument,
    Command,
    MatchBudget,
    OneOrMore,
    Option,
    Optional,
    Required,
    _leaf_with_value,
    _match_budget,
)


def test_flat_lists_the_leaves_in_usage_order_and_stops_at_a_node_of_a_type_it_was_asked_for():
    host, port, verbose = Argument("<host>"), Argument("<port>"), Option("-v", None)
    inner = Optional(port, verbose)
    tree = Required(host, OneOrMore(inner))
    assert_that(tree.flat()).is_equal_to([host, port, verbose])
    assert_that(
        [leaf is expected for leaf, expected in zip(tree.flat(), [host, port, verbose], strict=True)]
    ).does_not_contain(False)
    assert_that(tree.flat(Option)).is_equal_to([verbose])
    assert_that(tree.flat(Optional)).is_equal_to([inner])  # the node itself, not what is under it
    assert_that(Required().flat()).is_empty()


@pytest.mark.parametrize(
    "leaf",
    [Argument("<files>", ["a"]), Command("add", True), Option("-p", "--port", 1, "80", "PORT", "server.port")],
    ids=["argument", "command", "option"],
)
def test_a_leaf_copied_with_a_value_is_a_new_leaf_of_its_kind_that_carries_everything_but_the_value(leaf):
    leaf.span = (3, 9)
    before = repr(leaf)  # also fills the cached repr, which the copy must not inherit
    clone = _leaf_with_value(leaf, "new")
    assert_that(clone is leaf).is_false()
    assert_that(type(clone)).is_equal_to(type(leaf))
    assert_that(clone.value).is_equal_to("new")
    carried = {name: value for name, value in vars(clone).items() if name not in {"_value", "_cached_repr"}}
    assert_that(carried).is_equal_to(
        {name: value for name, value in vars(leaf).items() if name not in {"_value", "_cached_repr"}}
    )
    assert_that(carried).contains_entry({"span": (3, 9)})
    assert_that(repr(clone)).is_equal_to(before.replace(repr(leaf.value), "'new'"))
    assert_that(repr(leaf)).is_equal_to(before)  # the original is left as it was


def test_the_budget_is_set_inside_the_block_and_taken_back_after_it_however_the_block_ends():
    budget = _match_budget
    assert_that(budget.get()).is_none()
    with MatchBudget(7):
        assert_that(budget.get()).is_equal_to([7])
        with MatchBudget():
            assert_that(budget.get()).is_equal_to([MATCH_LIMIT])
        assert_that(budget.get()).is_equal_to([7])  # the inner block took back only its own
    assert_that(budget.get()).is_none()
    try:
        with MatchBudget(7):
            raise LookupError
    except LookupError:
        pass
    assert_that(budget.get()).is_none()


class _Marked(Argument):
    __slots__ = ("mark",)

    def single_match(self, left):
        for index, pattern in enumerate(left):
            if type(pattern) is Argument:
                found = _Marked(self.name, pattern.value)
                found.mark = "kept"
                return index, found
        return None, None


def test_a_leaf_class_of_the_callers_own_is_copied_the_way_copy_does_it():
    # its slot is no part of `__dict__`, so only the copy protocol carries it over a repeated match
    leaf = _Marked("<x>", [])
    _, collected = next(leaf.matches([Argument(None, "a")], []))
    _, collected = next(leaf.matches([Argument(None, "b")], collected))
    (merged,) = collected
    assert_that(type(merged)).is_equal_to(_Marked)
    assert_that(merged.value).is_equal_to(["a", "b"])
    assert_that(getattr(merged, "mark", "lost")).is_equal_to("kept")
