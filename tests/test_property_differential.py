from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

from hypothesis import given

from _strategies import argv_strategy, doc_strategy
from docopt2 import DocoptExit, DocoptLanguageError, docopt

# Load the vendored original docopt as a differential oracle.
_oracle_path = Path(__file__).parent / "_vendor" / "docopt_original.py"
_spec = importlib.util.spec_from_file_location("docopt_original", _oracle_path)
assert _spec is not None and _spec.loader is not None
_vanilla = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_vanilla)


# docopt2 keeps one deliberate, documented deviation from vanilla docopt: vanilla leaks a
# repeated option's accumulated values across usage alternatives (`--to a --to b` yields
# ['a', 'b', 'b']), and docopt2 fixes it. We apply the identical fix to the oracle here so
# this test reads "docopt2 == vanilla docopt EXCEPT that one fix" instead of false-alarming on
# our intended improvement. Other intentional divergences live in tests/test_divergences.py.
def _oracle_option_single_match(self, left):
    for index, pattern in enumerate(left):
        if self.name == pattern.name:
            value = pattern.value.copy() if isinstance(pattern.value, list) else pattern.value
            return index, _vanilla.Option(pattern.short, pattern.long, pattern.argcount, value)
    return None, None


_vanilla.Option.single_match = _oracle_option_single_match


# Second documented deviation: docopt2 treats a `--` in argv as the POSIX option/argument
# separator even when the usage pattern does not declare a `--`, dropping it rather than
# leaking it in as a positional value. The oracle grammar never declares a `--` command, so
# mirror docopt2 by dropping that separator token from the oracle's parsed argv too.
_oracle_parse_argv = _vanilla.parse_argv


def _oracle_parse_argv_drop_separator(*args, **kwargs):
    result = _oracle_parse_argv(*args, **kwargs)
    for index, leaf in enumerate(result):
        if type(leaf) is _vanilla.Argument and leaf.value == "--":
            del result[index]
            break
    return result


_vanilla.parse_argv = _oracle_parse_argv_drop_separator  # ty: ignore[unresolved-attribute] - dynamic oracle module


def _outcome(fn, exit_exc, lang_exc, doc, argv):
    try:
        return ("ok", dict(fn(doc, argv=argv, help=False)))
    except exit_exc:
        return ("user-error", None)
    except lang_exc:
        return ("lang-error", None)


def _assigned_tokens(result_map: dict[str, object]) -> list[str]:
    """The argv-derived string values a result assigns (list items and scalar strings)."""
    tokens: list[str] = []
    for value in result_map.values():
        if isinstance(value, list):
            tokens.extend(value)
        elif isinstance(value, str):
            tokens.append(value)
    return tokens


def _value_compatible(got_value: object, want_value: object) -> bool:
    if got_value == want_value:
        return True
    # docopt2's backtracking matcher does not reproduce vanilla's value-duplication (the same
    # family as the option fix): it assigns each argv token to a single leaf, so a token vanilla
    # double-counts - a repeated element, or one that vanilla puts in both a command and an
    # adjacent `<name>` across an Either - lands in only one of docopt2's lists. Its per-key list
    # is therefore a subset of vanilla's, never longer and never with a value vanilla lacks.
    if isinstance(got_value, list) and isinstance(want_value, list):
        return set(got_value) <= set(want_value) and len(got_value) <= len(want_value)
    # a repeated flag is counted, not over-counted (`type is int` excludes bool flags)
    if type(got_value) is int and type(want_value) is int:
        return 0 < got_value <= want_value
    return False


@given(doc=doc_strategy, argv=argv_strategy)
def test_docopt2_matches_vanilla_docopt(doc, argv):
    got = _outcome(docopt, DocoptExit, DocoptLanguageError, doc, argv)
    want = _outcome(_vanilla.docopt, _vanilla.DocoptExit, _vanilla.DocoptLanguageError, doc, argv)
    if want[0] == "user-error":
        # docopt2 is a compatible superset of vanilla (the backtracking matcher): it may
        # resolve some argv that vanilla rejects (e.g. `<a>... <b>`). It must still never turn a
        # rejected argv into a docstring (language) error.
        assert got[0] in ("user-error", "ok"), (
            f"docopt2 raised a language error where vanilla only rejected the argv:\n"
            f" doc={doc!r}\n argv={argv}\n docopt2={got}"
        )
        return
    if want[0] == "lang-error":
        assert got == want, f"docstring-error divergence:\n doc={doc!r}\n argv={argv}\n docopt2={got}\n vanilla={want}"
        return
    # Both succeed: docopt2 must produce the same keys and, per value, either vanilla's value or a
    # de-duplicated form of it (never more, never a value vanilla lacks).
    context = f" doc={doc!r}\n argv={argv}\n docopt2={got}\n vanilla={want}"
    assert got[0] == "ok", f"docopt2 rejected argv that vanilla accepted:\n{context}"
    got_map, want_map = got[1], want[1]
    assert got_map.keys() == want_map.keys(), f"key set diverged:\n{context}"
    if all(_value_compatible(got_map[key], want_map[key]) for key in want_map):
        return
    # Per-key values diverged. That is legitimate when the grammar is ambiguous, or when docopt2's
    # backtracking matches a branch vanilla could not (`([<name>] <name>) | <path>` on one token):
    # docopt2 then distributes the SAME argv tokens to different keys. Accept iff docopt2 fabricated
    # no value vanilla lacks - its assigned-token multiset is within vanilla's.
    surplus = Counter(_assigned_tokens(got_map)) - Counter(_assigned_tokens(want_map))
    assert not surplus, f"docopt2 assigned a value vanilla did not:\n{context}"
