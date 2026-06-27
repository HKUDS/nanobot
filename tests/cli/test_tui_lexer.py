from prompt_toolkit.document import Document

from nanobot.cli.tui.commands import (
    SlashCommandLexer,
    is_palette_prefix,
    known_commands,
)
from nanobot.command.builtin import BUILTIN_COMMAND_SPECS


def _line_fragments(text: str):
    return SlashCommandLexer().lex_document(Document(text, len(text)))(0)


def test_known_commands_includes_builtins():
    known = known_commands()
    assert "/new" in known
    assert "/diff" in known


def test_known_commands_match_builtin_specs():
    assert known_commands() == {spec.command for spec in BUILTIN_COMMAND_SPECS}


def test_lexer_colors_recognized_command_whole():
    frags = _line_fragments("/new")
    assert frags == [("class:slash-command", "/new")]


def test_lexer_colors_command_but_not_arguments():
    frags = _line_fragments("/model gpt")
    assert frags[0] == ("class:slash-command", "/model")
    assert frags[-1] == ("", " gpt")


def test_lexer_leaves_partial_or_unknown_uncolored():
    assert _line_fragments("/ne") == [("", "/ne")]
    assert _line_fragments("/zzznope") == [("", "/zzznope")]
    assert _line_fragments("hello world") == [("", "hello world")]


def test_is_palette_prefix_matches_bare_slash_token_only():
    assert is_palette_prefix("/dia") is True
    assert is_palette_prefix("  /diff") is True
    assert is_palette_prefix("/diff now") is False
    assert is_palette_prefix("hello") is False
    assert is_palette_prefix("") is False
