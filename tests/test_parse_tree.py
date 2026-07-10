import json

from assertpy2 import assert_that

from docopt2 import DocoptLanguageError, Pattern, parse_tree

DOC = """Usage: prog [-v] [--count=<n>] [options] <name> (add | rm) [<files>...]

Options:
  -v --verbose  Be verbose.
  --count=<n>  How many [default: 3].
"""


def _walk(node):
    yield node
    for child in node.get("children", []):
        yield from _walk(child)


def test_parse_tree_returns_typed_pattern():
    assert_that(parse_tree(DOC)).is_instance_of(Pattern)


def test_to_dict_minimal_shape():
    tree = parse_tree("Usage: prog <name>")
    assert_that(tree.to_dict()).is_equal_to(
        {"type": "Required", "children": [{"type": "Required", "children": [{"type": "Argument", "name": "<name>"}]}]}
    )


def test_to_dict_covers_every_node_kind_and_json_round_trips():
    node = parse_tree(DOC).to_dict()
    reloaded = json.loads(json.dumps(node))  # proves the tree serializes with only the stdlib
    kinds = {entry["type"] for entry in _walk(reloaded)}
    assert_that(kinds).contains(
        "Required", "Optional", "Either", "OneOrMore", "OptionsShortcut", "Argument", "Command", "Option"
    )


def test_options_shortcut_is_left_unexpanded():
    shortcuts = [entry for entry in _walk(parse_tree(DOC).to_dict()) if entry["type"] == "OptionsShortcut"]
    assert_that(shortcuts).is_length(1)
    assert_that(shortcuts[0]["children"]).is_empty()


def test_option_default_is_included_only_for_value_options():
    options = {entry["long"]: entry for entry in _walk(parse_tree(DOC).to_dict()) if entry["type"] == "Option"}
    assert_that(list(options["--verbose"])).does_not_contain("default")
    assert_that(options["--verbose"]["argcount"]).is_equal_to(0)
    assert_that(options["--count"]["argcount"]).is_equal_to(1)
    assert_that(options["--count"]["default"]).is_equal_to("3")


def test_parse_tree_requires_a_usage_section():
    assert_that(parse_tree).raises(DocoptLanguageError).when_called_with("no usage here")


def test_parse_tree_rejects_multiple_usage_sections():
    assert_that(parse_tree).raises(DocoptLanguageError).when_called_with("Usage: prog a\n\nUsage: prog b")


def test_parse_tree_rejects_a_usage_section_with_no_program():
    # formal_usage's empty-body path: a `Usage:` header with nothing after it names no program.
    assert_that(parse_tree).raises(DocoptLanguageError).when_called_with("Usage:")
