from __future__ import annotations

from typing import TYPE_CHECKING

from docopt2._completion import complete, generate_completion
from docopt2._core import Arguments, Cli, Dispatch, Source, docopt, parse_tree
from docopt2._errors import DocoptExit, DocoptLanguageError
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

if TYPE_CHECKING:  # real types for the lazily-loaded tooling below, at zero runtime import cost
    from docopt2._compat import check_compat
    from docopt2._fmt import format_usage
    from docopt2._format import format_argv
    from docopt2._generate import generate_config_template, generate_examples
    from docopt2._lint import check
    from docopt2._stub import generate_stub

    __version__: str

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
    "check_compat",
    "complete",
    "docopt",
    "formal_usage",
    "format_argv",
    "format_usage",
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

# Tooling a plain docopt() call never needs loads on first access, so `import docopt2` stays lean.
_LAZY_MODULES = {
    "check": "docopt2._lint",
    "check_compat": "docopt2._compat",
    "format_argv": "docopt2._format",
    "format_usage": "docopt2._fmt",
    "generate_config_template": "docopt2._generate",
    "generate_examples": "docopt2._generate",
    "generate_stub": "docopt2._stub",
}


def __getattr__(name: str) -> object:
    """Resolve deferred names (PEP 562): the version and the tooling functions, imported only when asked."""
    if name == "__version__":
        # importlib.metadata drags in ~22ms of stdlib (email, zipfile, inspect) the parser never needs.
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("docopt2")
        except PackageNotFoundError:  # pragma: no cover - only from a source tree with no installed dist
            return "0.0.0"
    module_name = _LAZY_MODULES.get(name)
    if module_name is not None:
        from importlib import import_module

        value = getattr(import_module(module_name), name)
        globals()[name] = value  # cache: later lookups find it directly and skip __getattr__
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
