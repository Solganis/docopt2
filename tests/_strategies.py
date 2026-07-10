from hypothesis import strategies as st

_ATOMS = ["-a", "-b", "-v", "--foo", "--bar", "--opt=<x>", "<name>", "<path>", "NAME", "cmd", "add", "-"]

# A usage pattern built from a restricted but representative subset of the grammar.
_expr = st.recursive(
    st.sampled_from(_ATOMS),
    lambda kids: st.one_of(
        kids.map(lambda child: f"[{child}]"),
        kids.map(lambda child: f"({child})"),
        kids.map(lambda child: f"{child} ..."),
        st.tuples(kids, kids).map(lambda pair: f"{pair[0]} {pair[1]}"),
        st.tuples(kids, kids).map(lambda pair: f"{pair[0]} | {pair[1]}"),
    ),
    max_leaves=6,
)
doc_strategy = _expr.map(lambda body: f"usage: prog {body}")

# argv drawn from a vocabulary that overlaps the doc's, so some inputs actually match.
_ARGV_TOKENS = ["-a", "-b", "-v", "-ab", "--foo", "--bar", "--opt", "--opt=1", "--", "cmd", "add", "-", "x", "1", "-3"]
argv_strategy = st.lists(st.sampled_from(_ARGV_TOKENS), max_size=6)
