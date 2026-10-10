from __future__ import annotations

import sys

import pytest
from assertpy2 import assert_that
from hypothesis import given
from hypothesis import strategies as st
from pytest import importorskip

from docopt2 import DocoptLanguageError, docopt, generate_config_template

# tomllib is stdlib from 3.11; on the 3.10 floor the dev group installs tomli, so these properties
# hold on every supported version instead of quietly skipping on the oldest one.
_TOML = "tomllib" if sys.version_info >= (3, 11) else "tomli"

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
    tomllib = importorskip(_TOML)
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
    tomllib = importorskip(_TOML)
    try:
        out = generate_config_template(doc)
    except DocoptLanguageError:
        return  # colliding/duplicate keys are rejected loudly - the acceptable failure mode
    tomllib.loads(out)  # anything actually emitted must parse


def _resolves_to_its_declared_defaults(doc: str) -> bool:
    """Whether the template of ``doc``, fed back as ``config=``, resolves every option to its default."""
    tomllib = importorskip(_TOML)
    template = generate_config_template(doc)
    return docopt(doc, "", config=tomllib.loads(template), complete=False) == docopt(doc, "", complete=False)


@pytest.mark.parametrize("default", ["true", "True", "TRUE", "false", "FALSE", "1.10", "007", "9" * 19, " x ", "a b"])
def test_a_default_reads_back_unchanged_through_the_template(default):
    doc = f"Usage: prog [options]\n\nOptions:\n  --opt0=<v0>  Desc [default: {default}] [config: g0].\n"
    assert_that(docopt(doc, "", complete=False)["--opt0"]).is_equal_to(default)  # the usage itself is read as meant
    assert_that(_resolves_to_its_declared_defaults(doc)).is_true()


def test_an_integer_default_past_the_digit_limit_is_quoted_instead_of_raising():
    # the limit is set here, since the ambient one can be raised or switched off (PYTHONINTMAXSTRDIGITS)
    doc = "Usage: prog [options]\n\nOptions:\n  --opt0=<v0>  Desc [default: " + "9" * 700 + "] [config: g0].\n"
    ambient = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(640)
    try:
        assert_that(_resolves_to_its_declared_defaults(doc)).is_true()
    finally:
        sys.set_int_max_str_digits(ambient)


def test_the_template_fed_back_as_config_resolves_every_option_to_its_declared_default():
    drawn: list[str] = []
    well_formed: list[str] = []

    tomllib = importorskip(_TOML)

    @given(doc=_config_doc())
    def check(doc):
        drawn.append(doc)
        try:
            declared = docopt(doc, "", complete=False)
        except DocoptLanguageError:
            return  # a fuzzed default injected a second "usage:" or a section header
        well_formed.append(doc)
        try:
            template = generate_config_template(doc)
        except DocoptLanguageError as refusal:
            raise AssertionError(f"a usage docopt reads was refused a template: {refusal}") from refusal
        assert docopt(doc, "", config=tomllib.loads(template), complete=False) == declared

    check()
    # a refusal is the rare case, so a run that refused most of what it drew proved nothing about the rest
    assert_that(len(well_formed)).is_greater_than(len(drawn) * 0.9)
