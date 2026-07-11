from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version

from docopt2._completion import complete, generate_completion
from docopt2._core import Arguments, Cli, Dispatch, Source, docopt, parse_tree
from docopt2._errors import DocoptExit, DocoptLanguageError
from docopt2._format import format_argv
from docopt2._generate import generate_config_template, generate_examples
from docopt2._lint import check
from docopt2._parser import (
    Argument,
    BranchPattern,
    Command,
    Either,
    LeafPattern,
    OneOrMore,
    Option,
    Optional,
    OptionsShortcut,
    Pattern,
    Required,
    Tokens,
    formal_usage,
    parse_argv,
    parse_defaults,
    parse_pattern,
    parse_section,
    transform,
)
from docopt2._stub import generate_stub

# This module is the public facade: it only re-exports names; the runtime (docopt, Cli, Dispatch,
# Arguments, parse_tree) lives in _core, and the parser primitives (Tokens, formal_usage, parse_*,
# transform) are re-exported for drop-in compatibility with the original docopt module.
__all__ = [
    "Argument",
    "Arguments",
    "BranchPattern",
    "Cli",
    "Command",
    "Dispatch",
    "DocoptExit",
    "DocoptLanguageError",
    "Either",
    "LeafPattern",
    "OneOrMore",
    "Option",
    "Optional",
    "OptionsShortcut",
    "Pattern",
    "Required",
    "Source",
    "Tokens",
    "check",
    "complete",
    "docopt",
    "formal_usage",
    "format_argv",
    "generate_completion",
    "generate_config_template",
    "generate_examples",
    "generate_stub",
    "parse_argv",
    "parse_defaults",
    "parse_pattern",
    "parse_section",
    "parse_tree",
    "transform",
]

try:
    __version__ = _package_version("docopt2")
except PackageNotFoundError:  # pragma: no cover - only when imported from a source tree with no installed dist
    __version__ = "0.0.0"
