from assertpy2 import assert_that

from docopt2 import docopt, parse_tree

# These pin the worked examples and Layer 4 behaviours documented in docs/grammar.md, so the
# grammar reference cannot silently drift from the parser.


def test_grammar_example_single_argument():
    assert_that(parse_tree("usage: prog <name>").to_dict()).is_equal_to(
        {"type": "Required", "children": [{"type": "Required", "children": [{"type": "Argument", "name": "<name>"}]}]}
    )


def test_grammar_example_flag_and_either_of_commands():
    assert_that(parse_tree("usage: prog [-v] (add | rm)").to_dict()).is_equal_to(
        {
            "type": "Required",
            "children": [
                {
                    "type": "Required",
                    "children": [
                        {
                            "type": "Optional",
                            "children": [{"type": "Option", "short": "-v", "long": None, "argcount": 0}],
                        },
                        {
                            "type": "Required",
                            "children": [
                                {
                                    "type": "Either",
                                    "children": [
                                        {"type": "Command", "name": "add"},
                                        {"type": "Command", "name": "rm"},
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )


def test_grammar_either_keeps_shortest_remainder():
    # Layer 4: Either keeps the branch that leaves the fewest argv leaves unmatched.
    assert_that(docopt("usage: prog (a | a b)", "a b", help=False)).is_equal_to({"a": True, "b": True})


def test_grammar_options_shortcut_excludes_options_named_elsewhere():
    # Layer 4: [options] pulls in only options not named anywhere else in the pattern.
    doc = "usage: prog --foo\n       prog [options]\n\noptions:\n  --foo\n  --bar\n"
    assert_that(docopt(doc, "--bar", help=False)).is_equal_to({"--foo": False, "--bar": True})


def test_grammar_repeatable_flag_counts():
    # Layer 4: a repeatable flag accumulates into an integer count.
    assert_that(docopt("usage: prog [-v]...", "-v -v -v", help=False)).is_equal_to({"-v": 3})
