import os
from unittest.mock import patch

from nanobot.providers.claude_code_auth import get_claude_code_token, is_oauth_token


def test_get_token_returns_env_var():
    with patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-test123"}):
        assert get_claude_code_token() == "sk-ant-oat01-test123"


def test_get_token_returns_none_when_unset():
    with patch.dict(os.environ, {}, clear=True):
        assert get_claude_code_token() is None


def test_get_token_returns_none_for_empty_string():
    with patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": ""}):
        assert get_claude_code_token() is None


def test_is_oauth_token_true():
    assert is_oauth_token("sk-ant-oat01-abc") is True


def test_is_oauth_token_false():
    assert is_oauth_token("sk-ant-api03-abc") is False
    assert is_oauth_token("") is False
