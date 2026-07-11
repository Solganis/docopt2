from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from pytest import importorskip

from docopt2 import DocoptLanguageError, generate_config_template

# Fuzz the two string-assembly points: a config-key segment (drives _toml_key quoting) and a
# default value (drives _toml_value quoting). Segments exclude "." (the separator) and "]" (which
# closes the annotation); defaults exclude "]" and newlines so the single Options line still parses.
_KEY_SEGMENT = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126, blacklist_characters=".]"),
    min_size=1,
    max_size=5,
)
_DEFAULT_TEXT = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126, blacklist_characters="]"),
    max_size=8,
)


@st.composite
def _config_doc(draw: st.DrawFn) -> str:
    """A usage doc whose Options each declare a unique, collision-free ``[config:]`` key.

    Each key is prefixed with a unique ``g{index}`` segment so no two keys collide and none is a
    prefix of another (a doc mapping both ``a`` and ``a.b`` is contradictory, not a rendering bug),
    isolating the property to the escaping/rendering logic rather than schema coherence.
    """
    count = draw(st.integers(min_value=1, max_value=5))
    lines = ["Usage: prog [options]", "", "Options:"]
    for index in range(count):
        extra = draw(st.lists(_KEY_SEGMENT, max_size=2))
        key = ".".join([f"g{index}", *extra])
        default = draw(st.none() | _DEFAULT_TEXT)
        default_part = "" if default is None else f" [default: {default}]"
        lines.append(f"  --opt{index}=<v{index}>  Desc{default_part} [config: {key}].")
    return "\n".join(lines) + "\n"


@given(doc=_config_doc())
def test_config_template_is_always_valid_round_trippable_toml(doc):
    # The template's whole contract is "valid TOML you can feed back as config=". Whatever keys and
    # defaults the usage declares, the output must parse - this guards _toml_key/_toml_value escaping.
    tomllib = importorskip("tomllib")  # stdlib on 3.11+
    try:
        out = generate_config_template(doc)
    except DocoptLanguageError:
        return  # a fuzzed default may inject a second "usage:"/section header - a malformed doc, rejected as such
    parsed = tomllib.loads(out)
    assert isinstance(parsed, dict)


# A pool small enough that duplicate and prefix collisions (`a` vs `a.b`) recur across draws.
_COLLIDING_KEY = st.sampled_from(["a", "a.b", "a.b.c", "x", "x.y", "srv", "srv.port", "srv.host"])


@st.composite
def _maybe_colliding_doc(draw: st.DrawFn) -> str:
    count = draw(st.integers(min_value=1, max_value=4))
    options = [f"  --opt{index}=<v{index}>  Desc [config: {draw(_COLLIDING_KEY)}]." for index in range(count)]
    return "\n".join(["Usage: prog [options]", "", "Options:", *options]) + "\n"


@given(doc=_maybe_colliding_doc())
def test_config_template_never_emits_silent_invalid_toml(doc):
    # The strong invariant that closes the collision hole: for ANY config keys, generate_config_template
    # either produces valid TOML or fails loudly with DocoptLanguageError - it never writes a broken file.
    tomllib = importorskip("tomllib")
    try:
        out = generate_config_template(doc)
    except DocoptLanguageError:
        return  # colliding/duplicate keys are rejected loudly - the acceptable failure mode
    tomllib.loads(out)  # anything actually emitted must parse
