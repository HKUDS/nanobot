import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.formatted_text import HTML

from nanobot.cli import commands


@pytest.fixture
def mock_prompt_session():
    """Mock the global prompt session."""
    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock()
    with patch("nanobot.cli.commands._PROMPT_SESSION", mock_session):
        yield mock_session


@pytest.mark.asyncio
async def test_read_interactive_input_async_returns_input(mock_prompt_session):
    """Test that _read_interactive_input_async returns the user input from prompt_session."""
    mock_prompt_session.prompt_async.return_value = "hello world"

    result = await commands._read_interactive_input_async()
    
    assert result == "hello world"
    mock_prompt_session.prompt_async.assert_called_once()
    args, _ = mock_prompt_session.prompt_async.call_args
    assert isinstance(args[0], HTML)  # Verify HTML prompt is used


@pytest.mark.asyncio
async def test_read_interactive_input_async_handles_eof(mock_prompt_session):
    """Test that EOFError converts to KeyboardInterrupt."""
    mock_prompt_session.prompt_async.side_effect = EOFError()

    with pytest.raises(KeyboardInterrupt):
        await commands._read_interactive_input_async()


def test_init_prompt_session_creates_session():
    """Test that _init_prompt_session initializes the global session."""
    # Ensure global is None before test
    commands._PROMPT_SESSION = None
    
    with patch("nanobot.cli.commands.PromptSession") as MockSession, \
         patch("nanobot.cli.commands.FileHistory") as MockHistory, \
         patch("pathlib.Path.home") as mock_home:
        
        mock_home.return_value = MagicMock()
        
        commands._init_prompt_session()
        
        assert commands._PROMPT_SESSION is not None
        MockSession.assert_called_once()
        _, kwargs = MockSession.call_args
        assert kwargs["multiline"] is False
        assert kwargs["enable_open_in_editor"] is False


def test_fetch_ollama_cloud_models_from_tags() -> None:
    """Should parse model names from Ollama native /api/tags response."""
    response = MagicMock()
    response.json.return_value = {
        "models": [
            {"name": "kimi-k2.5:cloud"},
            {"name": "qwen3-coder-next:cloud"},
        ]
    }
    response.raise_for_status.return_value = None

    with patch("nanobot.cli.commands.httpx.get", return_value=response) as mock_get:
        models, error = commands._fetch_ollama_cloud_models(
            api_base="https://ollama.com/api",
            api_key="test_key",
        )

    assert error is None
    assert "kimi-k2.5:cloud" in models
    assert "qwen3-coder-next:cloud" in models
    assert mock_get.call_count == 1


def test_fetch_ollama_cloud_models_fallback_to_v1_models() -> None:
    """Should fallback to /v1/models when /api/tags fails."""
    first_response = MagicMock()
    first_response.raise_for_status.side_effect = RuntimeError("boom")

    second_response = MagicMock()
    second_response.raise_for_status.return_value = None
    second_response.json.return_value = {
        "data": [
            {"id": "gpt-oss:20b-cloud"},
            {"id": "glm-5"},
        ]
    }

    with patch("nanobot.cli.commands.httpx.get", side_effect=[first_response, second_response]) as mock_get:
        models, error = commands._fetch_ollama_cloud_models(
            api_base="https://ollama.com",
            api_key="test_key",
        )

    assert error is None
    assert models == ["glm-5", "gpt-oss:20b-cloud"]
    assert mock_get.call_count == 2
