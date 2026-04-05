from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from nanobot.providers.transcription import GroqTranscriptionProvider


@pytest.mark.asyncio
async def test_transcription_without_language() -> None:
    """Test transcription without language parameter."""
    provider = GroqTranscriptionProvider(api_key="test-key")

    mock_response = MagicMock()
    mock_response.json.return_value = {"text": "Hello world"}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.post = mock_post
        with patch("builtins.open", mock_open(read_data=b"audio data")):
            with patch.object(Path, "exists", return_value=True):
                result = await provider.transcribe("test.mp3")

    assert result == "Hello world"
    assert provider.language is None


@pytest.mark.asyncio
async def test_transcription_with_language() -> None:
    """Test transcription with language parameter."""
    provider = GroqTranscriptionProvider(api_key="test-key", language="zh")

    mock_response = MagicMock()
    mock_response.json.return_value = {"text": "你好世界"}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.post = mock_post
        with patch("builtins.open", mock_open(read_data=b"audio data")):
            with patch.object(Path, "exists", return_value=True):
                result = await provider.transcribe("test.mp3")

    assert result == "你好世界"
    assert provider.language == "zh"

    # Verify language was passed in the files parameter
    call_kwargs = mock_post.call_args[1]
    files = call_kwargs["files"]
    assert "language" in files
    assert files["language"] == (None, "zh")


@pytest.mark.asyncio
async def test_transcription_file_not_found() -> None:
    """Test transcription with non-existent file."""
    provider = GroqTranscriptionProvider(api_key="test-key")

    with patch.object(Path, "exists", return_value=False):
        result = await provider.transcribe("nonexistent.mp3")

    assert result == ""


@pytest.mark.asyncio
async def test_transcription_api_error() -> None:
    """Test transcription with API error."""
    provider = GroqTranscriptionProvider(api_key="test-key")

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(side_effect=Exception("API error"))
        with patch("builtins.open", mock_open(read_data=b"audio data")):
            with patch.object(Path, "exists", return_value=True):
                result = await provider.transcribe("test.mp3")

    assert result == ""
