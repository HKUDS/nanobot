from unittest.mock import AsyncMock, Mock

import pytest

from nanobot.audio.transcription import resolve_transcription_config, transcribe_audio_file
from nanobot.audio.transcription_registry import TRANSCRIPTION_PROVIDERS
from nanobot.config.schema import Config


@pytest.mark.parametrize("spec", TRANSCRIPTION_PROVIDERS, ids=lambda spec: spec.name)
@pytest.mark.parametrize("proxy", [None, "${AUDIO_TEST_PROXY}"])
async def test_transcription_config_passes_selected_provider_proxy(monkeypatch, tmp_path, spec, proxy):
    monkeypatch.setenv("AUDIO_TEST_PROXY", "http://127.0.0.1:7890")
    config = Config()
    config.transcription.provider = spec.name
    selected = getattr(config.providers, spec.name)
    selected.api_key = "test-key"
    selected.proxy = proxy
    resolved = resolve_transcription_config(config)
    expected = "http://127.0.0.1:7890" if proxy else None
    assert resolved.proxy == expected
    adapter = Mock(return_value=Mock(transcribe=AsyncMock(return_value="recognized")))
    module, _, cls = spec.adapter.partition(":")
    monkeypatch.setattr(f"{module}.{cls}", adapter)
    path = tmp_path / "sample.wav"
    path.write_bytes(b"audio")
    assert await transcribe_audio_file(path, resolved) == "recognized"
    assert adapter.call_args.kwargs["proxy"] == expected
    adapter.return_value.transcribe.assert_awaited_once_with(path)
