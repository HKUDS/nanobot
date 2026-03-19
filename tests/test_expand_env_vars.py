import os
from unittest.mock import patch
from nanobot.config.loader import _expand_env_vars


def test_expand_env_vars_string():
    with patch.dict(os.environ, {"GROQ_API_KEY": "my-secret-key"}):
        result = _expand_env_vars("$GROQ_API_KEY")
        assert result == "my-secret-key"


def test_expand_env_vars_dict():
    with patch.dict(os.environ, {"GROQ_API_KEY": "my-secret-key"}):
        result = _expand_env_vars({"api_key": "$GROQ_API_KEY"})
        assert result == {"api_key": "my-secret-key"}


def test_expand_env_vars_missing_var():
    result = _expand_env_vars("$NON_EXISTENT_VAR")
    assert result == "$NON_EXISTENT_VAR"  # lascia invariato se non esiste


def test_expand_env_vars_nested():
    with patch.dict(os.environ, {"GROQ_API_KEY": "my-secret-key"}):
        result = _expand_env_vars({"llm": {"api_key": "$GROQ_API_KEY"}})
        assert result == {"llm": {"api_key": "my-secret-key"}}
