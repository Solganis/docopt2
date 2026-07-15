import dataclasses
import os
import random
from pathlib import Path

import pytest
from assertpy2 import assert_that
from hypothesis import given, settings
from hypothesis import strategies as st
from pytest import raises
from tools import regolden  # the one definition of what the golden scripts are generated from

from docopt2 import (
    Argument,
    Arguments,
    Dispatch,
    DocoptExit,
    DocoptLanguageError,
    OneOrMore,
    _completion,
    complete,
    docopt,
    generate_completion,
)
from docopt2._completion import _describe, _frontier, reply_to_completion_request

_TREE_DOC = """Usage:
  tool user create <name>
  tool user delete <id>
  tool project deploy <env>
  tool status
"""


# --- Dispatch ------------------------------------------------------------------------------------


def test_dispatch_routes_to_the_matching_command_handler():
    app = Dispatch(_TREE_DOC)
    seen: list[str] = []

    @app.on("user", "create")
    def create(args):
        seen.append(f"create:{args['<name>']}")
        return "created"

    @app.on("project", "deploy")
    def deploy(args):
        seen.append(f"deploy:{args['<env>']}")
        return "deployed"

    assert_that(app.run("user create alice")).is_equal_to("created")
    assert_that(app.run("project deploy prod")).is_equal_to("deployed")
    assert_that(seen).is_equal_to(["create:alice", "deploy:prod"])


def test_dispatch_passes_a_bound_schema_when_one_is_registered():
    app = Dispatch(_TREE_DOC)

    @dataclasses.dataclass
    class CreateArgs:
        name: str

    captured: list[object] = []

    @app.on("user", "create", schema=CreateArgs)
    def create(args):
        captured.append(args)

    app.run("user create alice")
    assert_that(captured[0]).is_instance_of(CreateArgs)
    assert_that(captured[0].name).is_equal_to("alice")


def test_dispatch_hands_an_untyped_handler_the_arguments_mapping():
    app = Dispatch(_TREE_DOC)
    captured: list[object] = []

    @app.on("user", "delete")
    def delete(args):
        captured.append(args)

    app.run("user delete 42")
    assert_that(captured[0]).is_instance_of(Arguments)
    assert_that(captured[0]["<id>"]).is_equal_to("42")


def test_dispatch_prefers_the_most_specific_command_path():
    app = Dispatch(_TREE_DOC)
    hits: list[str] = []

    @app.on("user")
    def any_user(args):
        hits.append("user")

    @app.on("user", "create")
    def user_create(args):
        hits.append("create")

    app.run("user create alice")
    assert_that(hits).is_equal_to(["create"])


def test_dispatch_falls_back_to_the_empty_path_handler():
    app = Dispatch(_TREE_DOC)

    @app.on("user", "create")
    def create(args):
        return "create"

    @app.on()
    def fallback(args):
        return "fallback"

    assert_that(app.run("status")).is_equal_to("fallback")
    assert_that(app.run("user create alice")).is_equal_to("create")


def test_dispatch_without_a_matching_handler_raises():
    app = Dispatch("Usage:\n  t a\n  t b\n")

    @app.on("a")
    def only_a(args):
        return "a"

    with raises(DocoptExit) as exc_info:
        app.run("b")
    assert_that(str(exc_info.value)).contains("no handler")


def test_dispatch_forwards_docopt_options():
    # run() forwards keyword options to docopt: a bad command still fails, honoring exit_code.
    app = Dispatch("Usage:\n  t <a>\n")

    @app.on()
    def fallback(args):
        return args["<a>"]

    with raises(DocoptExit) as exc_info:
        app.run("", exit_code=3)
    assert_that(exc_info.value.code).is_equal_to(3)


def test_dispatch_on_returns_the_handler_unchanged():
    app = Dispatch(_TREE_DOC)

    def handler(args):
        return None

    assert_that(app.on("status")(handler)).is_same_as(handler)


def test_dispatch_coercion_failure_carries_the_usage_and_the_exit_code():
    # A schema coercion failure in run() raised a bare DocoptExit: str(exc) lost the Usage block and the
    # caller's exit_code was ignored (defaulted to 1). Both must be threaded, as docopt()'s own path does.
    @dataclasses.dataclass
    class Add:
        count: int

    app = Dispatch("Usage:\n  prog add <count>\n")
    app.on("add", schema=Add)(lambda a: a)
    with raises(DocoptExit) as exc_info:
        app.run(["add", "x"], exit_code=2)
    assert_that(exc_info.value.exit_code).is_equal_to(2)
    assert_that(str(exc_info.value)).contains("Usage:")


def test_dispatch_no_handler_honours_the_exit_code():
    app = Dispatch("Usage:\n  p a\n  p b\n")
    app.on("a")(lambda args: "a")
    with raises(DocoptExit) as exc_info:
        app.run(["b"], exit_code=3)
    assert_that(exc_info.value.exit_code).is_equal_to(3)
    assert_that(str(exc_info.value)).contains("no handler")


def test_dispatch_run_rejects_a_schema_it_cannot_route_on():
    # run() forwards its keywords to docopt(), and `schema=` would make docopt return an instance -
    # which dispatch then tried to route on, failing with `'Args' object has no attribute 'get'`.
    @dataclasses.dataclass
    class Args:
        add: bool
        x: str

    app = Dispatch("Usage: t add <x>")

    @app.on("add")
    def add(args):
        return args

    with raises(TypeError) as exc_info:
        app.run(["add", "a"], schema=Args)
    assert_that(str(exc_info.value)).contains("on(..., schema=...)")


# --- completion resolver (context-aware) --------------------------------------------------------

# The usage the golden scripts are generated from, so the two can never describe different CLIs.
_GIT_DOC = regolden.DOC

_PKG_DOC = """Usage:
  prog [options] push <remote>
  prog pull <remote>...

Options:
  -v --verbose  Verbose.
  -f --force    Force.
"""


def test_complete_at_the_start_offers_commands_and_floating_options():
    # At the root: the leading subcommands, plus every branch option - docopt options float, so
    # `git-tool --amend commit` is valid and `--amend` is a legal first token.
    assert_that(complete(_GIT_DOC, [""])).is_equal_to(["--amend", "--depth", "-m", "clone", "commit", "remote"])


def test_complete_with_no_words_completes_at_the_start():
    assert_that(complete(_GIT_DOC, [])).is_equal_to(["--amend", "--depth", "-m", "clone", "commit", "remote"])


def test_complete_narrows_to_the_next_step_of_the_matched_subcommand():
    assert_that(complete(_GIT_DOC, ["remote", ""])).is_equal_to(["add"])


def test_complete_offers_branch_options_including_ones_taking_arguments():
    assert_that(complete(_GIT_DOC, ["commit", ""])).is_equal_to(["--amend", "-m"])


def test_complete_offers_an_argument_bearing_option_after_a_positional():
    assert_that(complete(_GIT_DOC, ["clone", "x", ""])).is_equal_to(["--depth"])


def test_complete_suggests_nothing_for_a_positional_slot():
    # after `remote add` the next element is <name>: an arbitrary value, no keyword candidates
    assert_that(complete(_GIT_DOC, ["remote", "add", ""])).is_equal_to([])


def test_complete_filters_by_the_partial_word_under_the_cursor():
    assert_that(complete(_GIT_DOC, ["c"])).is_equal_to(["clone", "commit"])


def test_complete_returns_nothing_for_an_invalid_prefix():
    assert_that(complete(_GIT_DOC, ["bogus", ""])).is_equal_to([])


def test_complete_after_a_double_dash_offers_commands_but_not_options():
    # After the POSIX `--` separator, tokens are positional: a command still completes, an option
    # does not (nothing past `--` is parsed as an option).
    assert_that(complete("usage: prog [-v] cmd", ["--", ""])).is_equal_to(["cmd"])


def test_complete_returns_nothing_while_completing_an_option_value():
    # the prefix ends at an option that needs an argument; arbitrary values are not completed
    assert_that(complete(_GIT_DOC, ["commit", "-m", ""])).is_equal_to([])


def test_complete_returns_nothing_for_a_malformed_docstring():
    assert_that(complete("usage: prog (-a", [""])).is_equal_to([])


def test_complete_returns_nothing_for_a_pathologically_deep_pattern():
    # A doc that would blow the recursion limit must yield no candidates, not crash the shell.
    assert_that(complete("usage: prog " + "[" * 600 + "a" + "]" * 600, [""])).is_equal_to([])


def test_complete_returns_nothing_without_a_usage_section():
    assert_that(complete("Options:\n  -v  V.", [""])).is_equal_to([])


def test_complete_offers_floating_options_and_commands_at_the_start():
    assert_that(complete(_PKG_DOC, [""])).is_equal_to(["--force", "--verbose", "pull", "push"])


def test_complete_drops_an_option_already_given_and_keeps_the_rest_floating():
    assert_that(complete(_PKG_DOC, ["push", "--verbose", ""])).is_equal_to(["--force"])


def test_complete_handles_repetition_and_suggests_nothing_for_the_repeated_positional():
    assert_that(complete(_PKG_DOC, ["pull", "r1", ""])).is_equal_to([])


_BRANCH_DOC = "Usage:\n  tool db (up|down) <steps>\n  tool serve <port> [--reload]\n\nOptions:\n  --reload  Reload.\n"


def test_complete_does_not_offer_a_command_a_typed_option_has_ruled_out():
    # `--reload` belongs only to the `serve` line, so after it only `serve` can follow. Offering `db`
    # (from the other line) was a dead end docopt() then rejects - complete() must not suggest it.
    assert_that(complete(_BRANCH_DOC, ["--reload", ""])).is_equal_to(["serve"])
    assert_that(complete(_BRANCH_DOC, [""])).is_equal_to(["--reload", "db", "serve"])  # both lines open at the start


def test_complete_offers_nothing_when_an_option_and_command_are_exclusive_and_the_option_was_taken():
    # `(cmd | -a)`: taking `-a` commits to that branch, so `cmd` can no longer follow.
    assert_that(complete("Usage: prog (cmd | -a)\n\nOptions:\n  -a\n", ["-a", ""])).is_equal_to([])


def _exhaustively_walked(children, left, *, optional, block, in_repetition):
    """`_frontier_seq` with the skip-branch prune switched OFF: an optional child always forks in two.

    This is the reference the pruned walk must match. The prune drops a floated child's skip-branch, on
    the reasoning that the take-branch is a superset at the same remaining - but that fails inside a
    OneOrMore, where the skip-branch's empty frontier is what lets the repetition re-enter. The prune is
    therefore gated on `not in_repetition`; this reference never prunes, so the comparison catches any
    over-pruning. A hand-picked grammar list missed the `[-a <name>]...` case; the wide hypothesis
    profile caught it. The list below now carries it, and the property test guards the rest.
    """
    if not children:
        yield left, set(), False
        return
    head, rest = children[0], children[1:]
    for remaining, frontier, blocks in _frontier(head, left, block=block, in_repetition=in_repetition):
        if blocks:
            yield remaining, frontier, True
        else:
            for tail_remaining, tail_frontier, tail_blocks in _exhaustively_walked(
                rest, remaining, optional=optional, block=block, in_repetition=in_repetition
            ):
                yield tail_remaining, frontier | tail_frontier, tail_blocks
    if optional:
        yield from _exhaustively_walked(rest, left, optional=optional, block=block, in_repetition=in_repetition)


_FRONTIER_GRAMMARS = [
    "usage: prog [options] <x>\n\nOptions:\n  -v --verbose  V.\n  -f --force  F.\n  --opt=<n>  O.\n",
    _TREE_DOC,
    "usage: prog (a | b) [--x] [--y] <z>\n\nOptions:\n  --x  X.\n  --y  Y.\n",
    "usage: prog [--a] [--b] [--c] [<p>] [<q>]\n\nOptions:\n  --a  A.\n  --b  B.\n  --c  C.\n",
    "usage: prog [-v]... <f>...\n\nOptions:\n  -v  Verbosity.\n",
    "usage: prog cmd [options] [--] <rest>...\n\nOptions:\n  --one  1.\n  --two  2.\n",
    "usage: prog [<a>] <b> [<c>]",
    # A floating option INSIDE a repetition: skipping `-a` is what lets the repeat consume a second
    # `<name>` and then offer `-a` again. The prune must NOT fire here. (Regression: wide hypothesis.)
    "usage: prog [-a <name>] ...",
    "usage: prog ([--x] <p>)... <q>\n\nOptions:\n  --x  X.\n",
]
_FRONTIER_WORDS = ["", "-", "--", "a", "b", "user", "create", "status", "cmd", "x", "--v", "-f", "-a", "name"]


@pytest.mark.parametrize("doc", _FRONTIER_GRAMMARS)
def test_the_pruned_frontier_walk_offers_what_the_exhaustive_one_did(doc, monkeypatch):
    pruned = _completion._frontier_seq
    rng = random.Random(11)
    for _ in range(150):
        words = [rng.choice(_FRONTIER_WORDS) for _ in range(rng.randint(0, 4))]
        monkeypatch.setattr(_completion, "_frontier_seq", _exhaustively_walked)
        exhaustive = complete(doc, words)
        monkeypatch.setattr(_completion, "_frontier_seq", pruned)
        assert_that(complete(doc, words)).described_as(f"words={words}").is_equal_to(exhaustive)


def test_frontier_repetition_guard_terminates():
    # OneOrMore's "made progress?" guard prevents an infinite loop on a non-consuming (frontier)
    # match. Materializing the generator exercises both arcs directly, past the any() short-circuit
    # that _is_prefix would otherwise take.
    no_input = list(_frontier(OneOrMore(Argument("<x>")), [], block=True))
    assert_that(no_input).is_length(1)  # guard False (no progress): only the frontier path
    assert_that(no_input[0][0]).is_equal_to([])  # remaining is empty (a valid prefix)
    one_token = list(_frontier(OneOrMore(Argument("<x>")), [Argument(None, "a")], block=True))
    assert_that([remaining for remaining, _frontier_set, _blocks in one_token]).contains([])  # consumed, may repeat


# --- completion request protocol (env-driven, answered inside docopt) ---------------------------


def test_reply_returns_none_without_a_request(monkeypatch):
    monkeypatch.delenv("_DOCOPT2_COMPLETE", raising=False)
    assert_that(reply_to_completion_request(_GIT_DOC)).is_none()


def test_reply_does_not_raise_into_the_shell_on_a_malformed_options_section(monkeypatch):
    # A run-together Options line (arg words > flags) must degrade to an empty reply on Tab, not dump
    # a DocoptLanguageError traceback into the user's shell.
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.setenv("_DOCOPT2_WORDS", "")
    doc = "Usage: prog [options] <x>\n\nOptions:\n  --foo ARG1 ARG2  desc"
    assert_that(reply_to_completion_request(doc)).is_equal_to("")


def test_reply_answers_a_completion_request(monkeypatch):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.setenv("_DOCOPT2_WORDS", "remote")  # completed tokens; the reply lists every next token
    assert_that(reply_to_completion_request(_GIT_DOC)).is_equal_to("add\t")  # `add` is a command: no description


def test_reply_with_no_words_completes_at_the_start(monkeypatch):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.delenv("_DOCOPT2_WORDS", raising=False)
    assert_that(reply_to_completion_request(_GIT_DOC)).is_equal_to(
        "--amend\tAmend commit\n--depth\tClone depth\n-m\tMessage\nclone\t\ncommit\t\nremote\t"
    )


def test_docopt_answers_a_completion_request_by_default(monkeypatch, capsys):
    # Completion is on by default: with a request in the environment, docopt replies and exits.
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.setenv("_DOCOPT2_WORDS", "commit")
    with raises(SystemExit):
        docopt(_GIT_DOC, [])
    lines = capsys.readouterr().out.splitlines()
    assert_that([line.split("\t")[0] for line in lines]).is_equal_to(["--amend", "-m"])
    assert_that(lines).contains("--amend\tAmend commit")  # the description column travels with the name


def test_completion_can_be_opted_out(monkeypatch):
    # complete=False: even with a request in the environment, argv is parsed normally.
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.setenv("_DOCOPT2_WORDS", "commit")
    assert_that(docopt(_GIT_DOC, "commit --amend", complete=False)["--amend"]).is_true()


def test_docopt_parses_normally_when_no_request_is_present(monkeypatch):
    # On by default, but with no request in the environment it falls through to a normal parse.
    monkeypatch.delenv("_DOCOPT2_COMPLETE", raising=False)
    assert_that(docopt(_GIT_DOC, "commit --amend")["--amend"]).is_true()


# --- option descriptions (the tooltip column) ---------------------------------------------------


def test_describe_maps_option_names_to_help_text_keeping_the_default():
    doc = "Usage: p [options] <x>\n\nOptions:\n  -v, --verbose  Say more.\n  --port=<n>     Port [default: 80].\n"
    described = _describe(doc)
    assert_that(described["--verbose"]).is_equal_to("Say more")  # both forms map to the same text
    assert_that(described["-v"]).is_equal_to("Say more")
    assert_that(described["--port"]).is_equal_to("Port [default: 80]")  # the default is kept in the tooltip


def test_describe_is_empty_without_an_options_section():
    assert_that(_describe("Usage: p <x>")).is_empty()


# Adversarial help text: quotes, command substitution, backticks, variable expansion, the zsh
# `_describe` colon delimiter, pipes, brackets, and literal tabs. No `-` (would parse as an option)
# and no newline - the wrapped continuation line supplies that structurally.
_DESC_TEXT = st.text(st.sampled_from([*"abc XYZ 012 $`'\":|;%()[]{}&=", "\t"]), max_size=40)


@given(first=_DESC_TEXT, wrapped=_DESC_TEXT)
@settings(max_examples=200, deadline=None)  # deadline off: first draw folds in import/compile on CI
def test_describe_value_is_always_single_line(first, wrapped):
    # A wrapped, special-char description must collapse to one line: a newline or tab in the value
    # would split the `name\tdescription` reply and inject a bogus completion candidate.
    doc = f"Usage: prog [--opt]\n\nOptions:\n  --opt  {first}\n          {wrapped}\n"
    for value in _describe(doc).values():
        assert "\n" not in value
        assert "\t" not in value


@given(first=_DESC_TEXT, wrapped=_DESC_TEXT)
@settings(max_examples=200, deadline=None)
def test_completion_reply_name_column_is_never_corrupted(first, wrapped):
    # End to end: every reply line has exactly one tab, and the name before it is a real candidate,
    # never a leaked fragment of the description.
    doc = f"Usage: prog [--opt]\n\nOptions:\n  --opt  {first}\n          {wrapped}\n"
    os.environ["_DOCOPT2_COMPLETE"] = "1"
    os.environ["_DOCOPT2_WORDS"] = ""
    try:
        reply = reply_to_completion_request(doc)
    finally:
        os.environ.pop("_DOCOPT2_COMPLETE", None)
        os.environ.pop("_DOCOPT2_WORDS", None)
    assert reply is not None
    candidates = set(complete(doc, [""]))
    for line in reply.split("\n"):
        assert line.count("\t") == 1
        assert line.split("\t", 1)[0] in candidates


# --- generated callback scripts (bash/pwsh validated end-to-end; zsh/fish generated to spec) ----


def test_bash_script_is_a_callback_that_re_invokes_the_program():
    script = generate_completion(_GIT_DOC, "git-tool", "bash")
    assert_that(script).contains("_git_tool_completion()").contains("complete -F _git_tool_completion git-tool")
    assert_that(script).contains("_DOCOPT2_COMPLETE=1").contains("COMP_WORDS")


_COMPLETION_GUIDE = (Path(__file__).parent.parent / "docs" / "guides" / "completion.md").read_text(encoding="utf-8")


def test_the_completion_guide_prints_the_script_the_tool_really_emits():
    # The guide shows the bash script verbatim, and a stale script in the docs is a script people paste.
    # Nothing else guards the guides, which is how this one came to show a script no longer generated.
    assert_that(_COMPLETION_GUIDE).contains(generate_completion(_GIT_DOC, "naval", "bash").strip())


def test_bash_script_glues_back_the_words_bash_split_at_a_wordbreak():
    # COMP_WORDBREAKS holds `=` and `:`, so bash hands us `--opt=value` as three words (`--opt`, `=`,
    # `value`). Forwarding those shards destroys the parse context and silently kills every completion
    # after them - and `--opt=value` is the very form the usage DSL teaches. bash emits the separator as
    # its own word, so the shards glue back unambiguously.
    script = generate_completion(_GIT_DOC, "git-tool", "bash")
    assert_that(script).contains("$part == [:=]").contains("${COMP_WORDS[index-1]} == [:=]")
    assert_that(script).contains("typed[$(( ${#typed[@]} - 1 ))]+=$part")


def test_bash_is_the_default_shell():
    assert_that(generate_completion(_GIT_DOC, "git-tool")).contains("COMPREPLY")


def test_zsh_script_has_a_compdef_header_and_a_sanitized_name():
    script = generate_completion(_GIT_DOC, "my-tool", "zsh")
    assert_that(script).starts_with("#compdef my-tool")
    # a non-identifier char in the program name becomes an underscore in the function name
    assert_that(script).contains("_my_tool_completion").contains("compdef _my_tool_completion my-tool")


def test_zsh_script_completes_when_autoloaded_and_registers_when_sourced():
    # Saved as `_prog` on $fpath - the install the docs recommend - zsh runs the file's BODY as the
    # completion function. A body that only defines the function and calls compdef therefore adds no
    # candidates at all on the first Tab. `CURRENT` is set only while the completion system is running, so
    # it tells the two installs apart.
    script = generate_completion(_GIT_DOC, "my-tool", "zsh")
    assert_that(script).contains("if (( ${+CURRENT} )); then")
    assert_that(script).contains('_my_tool_completion "$@"')
    assert_that(script).contains("compdef _my_tool_completion my-tool")


def test_zsh_script_adds_undescribed_candidates_with_compadd_not_describe():
    # Commands reply with an empty description; feeding that to _describe makes zsh print a dangling
    # `--`, so only described names go there and bare ones are added with compadd.
    script = generate_completion(_GIT_DOC, "my-tool", "zsh")
    assert_that(script).contains("if [[ -n $desc ]]").contains("compadd -a bare")
    assert_that(script).contains("_describe -t candidates candidate described")


def test_powershell_script_reads_only_up_to_the_cursor_and_unquotes_the_tokens():
    # PowerShell hands the completer the WHOLE line, so a Tab pressed mid-line would feed the tokens to the
    # RIGHT of the cursor to the program as if they had been typed, and a quoted token arrives with its
    # quotes attached. The partial word is a literal prefix, so it is matched with StartsWith, never `-like`
    # (which would read a `*` or `[` in it as a wildcard).
    script = generate_completion(_GIT_DOC, "git-tool", "powershell")
    assert_that(script).contains("$_.Extent.EndOffset -le $cursorPosition")
    assert_that(script).contains("StringConstantExpressionAst")
    assert_that(script).contains("$name.StartsWith($wordToComplete")
    assert_that(script).does_not_contain("-like")


def test_fish_script_registers_a_callback_completion():
    script = generate_completion(_GIT_DOC, "git-tool", "fish")
    assert_that(script).contains("function _git_tool_completion").contains("commandline -opc")
    assert_that(script).contains("complete -c git-tool -f -a '(_git_tool_completion)'")


def test_fish_script_joins_the_words_explicitly_rather_than_relying_on_no_resplit():
    # fish documents that a command substitution splits its output on newlines. Inside a completion function
    # it does not, which is why the words survive without this - but that is undocumented, and a script that
    # works only by relying on it is one fish release away from silently dropping every token but the last.
    # `string collect` states the intent instead of depending on the accident.
    script = generate_completion(_GIT_DOC, "git-tool", "fish")
    assert_that(script).contains("| string collect)")


def test_powershell_script_registers_a_native_argument_completer():
    script = generate_completion(_GIT_DOC, "git-tool", "powershell")
    assert_that(script).contains("Register-ArgumentCompleter -Native -CommandName git-tool")
    assert_that(script).contains("_DOCOPT2_COMPLETE").contains("CompletionResult")
    # the program is invoked through the command AST (a defined variable) - guards against a
    # regression that referenced an undefined `$elements`, which silently yielded no completions
    assert_that(script).contains("& $commandAst.CommandElements[0]")


def test_nushell_script_uses_an_at_complete_whole_command_completer():
    script = generate_completion(_GIT_DOC, "git-tool", "nushell")
    # nushell's `@complete` fires for commands AND flags and does not filter, so the completer filters by
    # the partial word (the last of `spans`); `export extern` declares only `...rest`, no typed flags, or
    # the program would be rejected at parse time when run with a flag.
    assert_that(script).contains('@complete "_git_tool_completion"')
    assert_that(script).contains('export extern "git-tool" [ ...rest: string ]')
    assert_that(script).contains("[spans: list<string>]").contains("_DOCOPT2_COMPLETE")
    assert_that(script).contains("str starts-with $partial")
    assert_that(script).does_not_contain(": int")  # typing a flag would break a working invocation


def test_unsupported_shell_lists_the_supported_ones():
    with raises(ValueError) as exc_info:
        generate_completion(_GIT_DOC, "tool", "tcsh")
    message = str(exc_info.value)
    assert_that(message).contains("bash").contains("zsh").contains("fish").contains("powershell").contains("nushell")


def test_generate_completion_without_a_usage_section_raises_language_error():
    assert_that(generate_completion).raises(DocoptLanguageError).when_called_with("Options:\n  -v  V.", "tool")


def test_generate_completion_rejects_a_prog_with_shell_metacharacters():
    # `prog` is interpolated into sourced shell scripts, so a name that could inject is refused.
    assert_that(generate_completion).raises(ValueError).when_called_with("usage: prog cmd", "foo; rm -rf ~")


@pytest.mark.parametrize("shell", regolden.SHELLS)
def test_the_generated_script_matches_its_golden_copy(shell):
    """A shell script is an artifact a user sources and their shell then EXECUTES.

    The assertions above pin the lines that once carried bugs; they say nothing about the rest of the
    template, so a stray character anywhere else yields a script that does not run and no test objects.
    zsh and PowerShell cannot be driven in CI, which leaves a byte-for-byte copy as the only guard.
    After an intentional change to a template: `uv run python tools/regolden.py`.
    """
    script = generate_completion(_GIT_DOC, regolden.PROG, shell)
    golden = (Path(__file__).parent / "golden" / f"completion_{shell}.txt").read_text(encoding="utf-8")
    assert_that(script).is_equal_to(golden)
