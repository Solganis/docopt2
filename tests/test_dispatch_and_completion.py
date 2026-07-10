import dataclasses

from assertpy2 import assert_that
from pytest import raises

from docopt2 import (
    Argument,
    Arguments,
    Dispatch,
    DocoptExit,
    DocoptLanguageError,
    OneOrMore,
    complete,
    docopt,
    generate_completion,
)
from docopt2._completion import _frontier, reply_to_completion_request

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


# --- completion resolver (context-aware) --------------------------------------------------------

_GIT_DOC = """Usage:
  git-tool clone <url> [--depth=<n>]
  git-tool commit [-m <msg>] [--amend]
  git-tool remote add <name> <url>

Options:
  --depth=<n>  Clone depth.
  -m <msg>     Message.
  --amend      Amend commit.
"""

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
    # the prefix ends at an option that needs an argument; we do not complete arbitrary values
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


def test_reply_answers_a_completion_request(monkeypatch):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.setenv("_DOCOPT2_WORDS", "remote")  # completed tokens; the reply lists every next token
    assert_that(reply_to_completion_request(_GIT_DOC)).is_equal_to("add")


def test_reply_with_no_words_completes_at_the_start(monkeypatch):
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.delenv("_DOCOPT2_WORDS", raising=False)
    assert_that(reply_to_completion_request(_GIT_DOC)).is_equal_to("--amend\n--depth\n-m\nclone\ncommit\nremote")


def test_docopt_answers_a_completion_request_by_default(monkeypatch, capsys):
    # Completion is on by default: with a request in the environment, docopt replies and exits.
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.setenv("_DOCOPT2_WORDS", "commit")
    with raises(SystemExit):
        docopt(_GIT_DOC, [])
    assert_that(capsys.readouterr().out.split()).is_equal_to(["--amend", "-m"])


def test_completion_can_be_opted_out(monkeypatch):
    # complete=False: even with a request in the environment, argv is parsed normally.
    monkeypatch.setenv("_DOCOPT2_COMPLETE", "1")
    monkeypatch.setenv("_DOCOPT2_WORDS", "commit")
    assert_that(docopt(_GIT_DOC, "commit --amend", complete=False)["--amend"]).is_true()


def test_docopt_parses_normally_when_no_request_is_present(monkeypatch):
    # On by default, but with no request in the environment it falls through to a normal parse.
    monkeypatch.delenv("_DOCOPT2_COMPLETE", raising=False)
    assert_that(docopt(_GIT_DOC, "commit --amend")["--amend"]).is_true()


# --- generated callback scripts (bash/pwsh validated end-to-end; zsh/fish generated to spec) ----


def test_bash_script_is_a_callback_that_re_invokes_the_program():
    script = generate_completion(_GIT_DOC, "git-tool", "bash")
    assert_that(script).contains("_git_tool_completion()").contains("complete -F _git_tool_completion git-tool")
    assert_that(script).contains("_DOCOPT2_COMPLETE=1").contains("COMP_WORDS")


def test_bash_is_the_default_shell():
    assert_that(generate_completion(_GIT_DOC, "git-tool")).contains("COMPREPLY")


def test_zsh_script_has_a_compdef_header_and_a_sanitized_name():
    script = generate_completion(_GIT_DOC, "my-tool", "zsh")
    assert_that(script).starts_with("#compdef my-tool")
    # a non-identifier char in the program name becomes an underscore in the function name
    assert_that(script).contains("_my_tool_completion").contains("compdef _my_tool_completion my-tool")


def test_fish_script_registers_a_callback_completion():
    script = generate_completion(_GIT_DOC, "git-tool", "fish")
    assert_that(script).contains("function _git_tool_completion").contains("commandline -opc")
    assert_that(script).contains("complete -c git-tool -f -a '(_git_tool_completion)'")


def test_powershell_script_registers_a_native_argument_completer():
    script = generate_completion(_GIT_DOC, "git-tool", "powershell")
    assert_that(script).contains("Register-ArgumentCompleter -Native -CommandName git-tool")
    assert_that(script).contains("_DOCOPT2_COMPLETE").contains("CompletionResult")
    # the program is invoked through the command AST (a defined variable) - guards against a
    # regression that referenced an undefined `$elements`, which silently yielded no completions
    assert_that(script).contains("& $commandAst.CommandElements[0]")


def test_unsupported_shell_lists_the_supported_ones():
    with raises(ValueError) as exc_info:
        generate_completion(_GIT_DOC, "tool", "tcsh")
    message = str(exc_info.value)
    assert_that(message).contains("bash").contains("zsh").contains("fish").contains("powershell")


def test_generate_completion_without_a_usage_section_raises_language_error():
    assert_that(generate_completion).raises(DocoptLanguageError).when_called_with("Options:\n  -v  V.", "tool")


def test_generate_completion_rejects_a_prog_with_shell_metacharacters():
    # `prog` is interpolated into sourced shell scripts, so a name that could inject is refused.
    assert_that(generate_completion).raises(ValueError).when_called_with("usage: prog cmd", "foo; rm -rf ~")
