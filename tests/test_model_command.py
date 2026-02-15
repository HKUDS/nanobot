"""Tests for /model command functionality."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.loop import _list_models, _set_model
from nanobot.config.schema import Config


@pytest.fixture
def temp_config():
    """Create a temporary config file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        config_path = Path(f.name)
    
    yield config_path
    
    # Cleanup
    if config_path.exists():
        config_path.unlink()


def make_test_config(model: str = "anthropic/claude-opus-4-5", providers: dict = None) -> Config:
    """Create a test config."""
    return Config(
        agents={"defaults": {"model": model, "max_tokens": 8192, "temperature": 0.7, 
                           "max_tool_iterations": 20, "memory_window": 50, "workspace": "~/.nanobot/workspace"}},
        providers=providers or {"anthropic": {"api_key": "sk-test-key"}}
    )


class TestListModels:
    """Tests for _list_models helper."""

    def test_list_models_shows_current(self):
        """Should display current model."""
        config = make_test_config(model="minimax/MiniMax-M2.5")
        
        result = _list_models(config)
        
        assert "Current: minimax/MiniMax-M2.5" in result

    def test_list_models_shows_available_providers(self):
        """Should list providers with API keys."""
        config = make_test_config(providers={
            "anthropic": {"api_key": "sk-ant-key"},
            "minimax": {"api_key": "sk-mini-key"},
        })
        
        result = _list_models(config)
        
        assert "Anthropic" in result
        assert "MiniMax" in result

    def test_list_models_excludes_unconfigured(self):
        """Should not show providers without API keys."""
        config = make_test_config(providers={
            "anthropic": {"api_key": "sk-ant-key"},
            "openai": {"api_key": ""},
        })
        
        result = _list_models(config)
        
        assert "Anthropic" in result
        assert "OpenAI" not in result


class TestSetModel:
    """Tests for _set_model helper."""

    @patch("nanobot.config.loader.load_config")
    @patch("nanobot.config.loader.save_config")
    def test_set_model_updates_config(self, mock_save, mock_load):
        """Should update model in config."""
        config = make_test_config(model="old-model")
        mock_load.return_value = config
        
        result = _set_model("new-model")
        
        assert config.agents.defaults.model == "new-model"
        mock_save.assert_called_once()

    @patch("nanobot.config.loader.load_config")
    @patch("nanobot.config.loader.save_config")
    def test_set_model_returns_confirmation(self, mock_save, mock_load):
        """Should return confirmation message with old and new model."""
        config = make_test_config(model="old-model")
        mock_load.return_value = config
        
        result = _set_model("new-model")
        
        assert "old-model" in result
        assert "new-model" in result
        assert "✅" in result

    @patch("nanobot.config.loader.load_config")
    @patch("nanobot.config.loader.save_config")
    def test_set_model_with_path(self, mock_save, mock_load, temp_config):
        """Should use provided config path."""
        config = make_test_config(model="old-model")
        mock_load.return_value = config
        
        _set_model("new-model", temp_config)
        
        mock_save.assert_called_once_with(config, temp_config)


class TestModelCommandParsing:
    """Tests for command parsing in agent loop."""

    def test_parse_model_list_command(self):
        """Parse /model without args."""
        content = "/model"
        parts = content.strip().split()
        
        assert len(parts) == 1

    def test_parse_model_set_session(self):
        """Parse /model <name>."""
        content = "/model minimax/MiniMax-M2.5"
        parts = content.strip().split()
        
        assert "-g" not in parts
        assert parts[1] == "minimax/MiniMax-M2.5"

    def test_parse_model_set_global(self):
        """Parse /model <name> -g."""
        content = "/model minimax/MiniMax-M2.5 -g"
        parts = content.strip().split()
        
        assert "-g" in parts
        parts.remove("-g")
        model = " ".join(parts[1:]).strip()
        
        assert model == "minimax/MiniMax-M2.5"

    def test_parse_model_with_spaces_in_name(self):
        """Parse model name with spaces."""
        content = "/model anthropic/claude-sonnet-4-5 -g"
        parts = content.strip().split()
        
        global_flag = "-g" in parts
        if global_flag:
            parts.remove("-g")
        model = " ".join(parts[1:]).strip()
        
        assert model == "anthropic/claude-sonnet-4-5"
        assert global_flag is True
