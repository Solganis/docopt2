import ast

from assertpy2 import assert_that
from hypothesis import given
from pytest import raises

from _strategies import doc_strategy
from docopt2 import DocoptLanguageError, docopt, generate_stub


def _exec(source: str) -> type:
    namespace: dict[str, object] = {}
    exec(source, namespace)
    return namespace["Args"]  # ty: ignore[invalid-return-type] - the generated module always defines Args


def test_generate_stub_is_exported_from_the_package():
    assert_that(generate_stub).is_not_none()


def test_a_required_positional_is_a_plain_str():
    assert_that(generate_stub("Usage: prog <host>")).contains("host: str\n")


def test_an_optional_positional_is_str_or_none():
    assert_that(generate_stub("Usage: prog [<host>]")).contains("host: str | None")


def test_a_repeating_positional_is_a_list():
    assert_that(generate_stub("Usage: prog <src>...")).contains("src: list[str]")


def test_a_command_is_a_bool():
    assert_that(generate_stub("Usage: prog build")).contains("build: bool")


def test_a_repeating_flag_is_an_int_count():
    assert_that(generate_stub("Usage: prog [-v]...")).contains("v: int")


def test_an_option_with_a_default_is_a_plain_str():
    doc = "Usage: prog [--speed=<kn>]\n\nOptions:\n  --speed=<kn>  Speed [default: 10].\n"
    assert_that(generate_stub(doc)).contains("speed: str\n")


def test_an_optional_option_without_a_default_is_str_or_none():
    doc = "Usage: prog [--speed=<kn>]\n\nOptions:\n  --speed=<kn>  Speed.\n"
    assert_that(generate_stub(doc)).contains("speed: str | None")


def test_the_dataclass_style_is_the_default():
    source = generate_stub("Usage: prog <host>")
    assert_that(source).contains("import dataclasses").contains("@dataclasses.dataclass").contains("class Args:")


def test_the_typeddict_style_emits_a_typeddict():
    source = generate_stub("Usage: prog <host>", style="typeddict")
    assert_that(source).contains("from typing import TypedDict").contains("class Args(TypedDict):")


def test_the_cli_style_embeds_the_usage_so_parse_works_standalone():
    source = generate_stub("Usage: prog <host>", style="cli")
    assert_that(source).contains("from docopt2 import Cli").contains("class Args(Cli):").contains('__cli_doc__ = """')


def test_the_cli_style_falls_back_to_repr_when_the_doc_has_triple_quotes():
    source = generate_stub('Usage: prog <host>\n\n"""', style="cli")
    assert_that(source).contains("__cli_doc__ = 'Usage").does_not_contain('__cli_doc__ = """')


def test_a_custom_class_name_is_honoured():
    assert_that(generate_stub("Usage: prog <host>", name="Cmdline")).contains("class Cmdline:")


def test_two_usage_names_that_collapse_to_one_field_become_a_note_not_a_field():
    source = generate_stub("Usage: prog <name> --name")
    assert_that(source).contains("# note:").contains("`--name`").contains("`<name>`").contains("distinct names")
    assert_that(source).does_not_contain("name: ")


def test_a_positional_that_is_not_a_valid_identifier_becomes_a_note():
    source = generate_stub("Usage: prog <2>")
    assert_that(source).contains("# note:").contains("not a valid field name")


def test_a_command_that_is_a_python_keyword_becomes_a_note():
    source = generate_stub("Usage: prog class")
    assert_that(source).contains("# note:").contains("not a valid field name")


def test_a_usage_with_no_elements_yields_an_empty_dataclass_body():
    assert_that(generate_stub("Usage: prog")).contains("class Args:\n    pass\n")


def test_a_usage_with_no_elements_still_carries_the_doc_in_cli_style():
    source = generate_stub("Usage: prog", style="cli")
    assert_that(source).contains("__cli_doc__").does_not_contain("pass")


def test_a_malformed_usage_raises_the_same_error_docopt_would():
    with raises(DocoptLanguageError):
        generate_stub("usage: prog (a]")


def test_the_generated_dataclass_actually_parses_argv():
    doc = "Usage: prog <host> <port> [--verbose] [--retries=<n>]\n\nOptions:\n  --retries=<n>  [default: 3].\n"
    schema = _exec(generate_stub(doc, style="typeddict"))
    result = docopt(doc, "localhost 8080 --verbose", complete=False, schema=schema)
    assert_that(result).is_equal_to({"host": "localhost", "port": "8080", "verbose": True, "retries": "3"})


def test_the_generated_stub_round_trips_a_repeating_positional():
    schema = _exec(generate_stub("Usage: prog ship <name>...", style="typeddict"))
    result = docopt("Usage: prog ship <name>...", "ship a b c", complete=False, schema=schema)
    assert_that(result).is_equal_to({"ship": True, "name": ["a", "b", "c"]})


def test_the_generated_stub_round_trips_a_multiline_subcommand_grammar():
    doc = (
        "Usage:\n  prog ship <name> move <x> <y> [--speed=<kn>]\n  prog mine set <x> <y>\n\n"
        "Options:\n  --speed=<kn>  Speed [default: 10].\n"
    )
    schema = _exec(generate_stub(doc, style="typeddict"))
    result = docopt(doc, "ship titanic move 1 2", complete=False, schema=schema)
    assert_that(result["ship"]).is_true()
    assert_that(result["move"]).is_true()
    assert_that(result["x"]).is_equal_to("1")
    assert_that(result["speed"]).is_equal_to("10")
    assert_that(result["mine"]).is_false()


@given(doc=doc_strategy)
def test_generate_stub_is_total_and_emits_compilable_python(doc):
    # Whatever the grammar, the generator either declines a malformed doc (as docopt() would) or
    # emits valid Python in every style. Fuzzing this guards the doc-embedding and note paths.
    for style in ("dataclass", "typeddict", "cli"):
        try:
            source = generate_stub(doc, style=style)
        except DocoptLanguageError:
            continue
        compile(source, "<stub>", "exec")


@given(doc=doc_strategy)
def test_generated_field_names_are_unique(doc):
    # compile() proves the source runs, but a duplicate field name compiles fine while silently breaking
    # the schema binding. Read the field names back with ast, independently of the generator, and assert
    # they are unique: two usage names that collapse to one field must be reported, not emitted twice.
    for style in ("dataclass", "typeddict", "cli"):
        try:
            source = generate_stub(doc, style=style)
        except DocoptLanguageError:
            continue
        class_def = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef))
        fields = [
            stmt.target.id
            for stmt in class_def.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        ]
        assert len(fields) == len(set(fields)), f"duplicate field in {style} style: {fields}"
