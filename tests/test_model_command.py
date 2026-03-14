from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


def _write_config(config_path: Path, config: Config) -> None:
    save_config(config, config_path)


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, *args, **kwargs) -> _FakeResponse:
        return self._response


def test_discover_openai_compatible_models_parses_model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    from nanobot.model_management import _discover_openai_compatible_models

    monkeypatch.setattr(
        "nanobot.model_management.httpx.Client",
        lambda **kwargs: _FakeClient(
            _FakeResponse({"data": [{"id": "gpt-4o"}, {"id": "gpt-4.1"}, {"id": "gpt-4o"}]})
        ),
    )

    models = _discover_openai_compatible_models("https://api.example.com/v1", "key", {})

    assert models == ["gpt-4o", "gpt-4.1"]


def test_handle_model_command_lists_current_state_and_switchable_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_model_command

    config_path = tmp_path / "config.json"
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "anthropic",
                    "model": "anthropic/claude-sonnet-4-5",
                }
            },
            "providers": {
                "anthropic": {"apiKey": "ant-key"},
                "openai": {"apiKey": "oa-key"},
                "gemini": {"apiKey": "gm-key"},
            },
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "nanobot.model_management.discover_models_for_provider",
        lambda _config, spec: {
            "anthropic": ["claude-sonnet-4-5", "claude-opus-4-5"],
            "openai": ["gpt-4.1", "gpt-4o"],
            "gemini": ["gemini-2.0-flash", "gemini-2.5-pro"],
        }.get(spec.name, []),
    )

    result = handle_model_command("/model")

    assert "Model Configuration" in result
    assert str(config_path) in result
    assert "Current provider: anthropic" in result
    assert "Current model: anthropic/claude-sonnet-4-5" in result
    assert "/model anthropic claude-sonnet-4-5" in result
    assert "/model openai gpt-4.1" in result
    assert "/model openai gpt-4o" in result
    assert "/model gemini gemini-2.5-pro" in result
    assert "/model gemini gemini-2.0-flash" in result
    assert "/model openai/gpt-4o" in result
    assert "/model gemini/gemini-2.5-pro" in result


def test_handle_model_command_hides_unusable_providers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_model_command

    config_path = tmp_path / "config.json"
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "anthropic",
                    "model": "anthropic/claude-sonnet-4-5",
                }
            },
            "providers": {
                "anthropic": {"apiKey": "ant-key"},
                "openai": {"apiKey": ""},
                "gemini": {"apiKey": ""},
                "ollama": {"apiBase": "http://localhost:11434"},
            },
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "nanobot.model_management.discover_models_for_provider",
        lambda _config, spec: {
            "anthropic": ["claude-sonnet-4-5"],
            "openai": ["gpt-4o"],
            "gemini": ["gemini-2.5-pro"],
            "ollama": ["llama3.2"],
        }.get(spec.name, []),
    )

    result = handle_model_command("/model")

    assert "/model anthropic claude-sonnet-4-5" in result
    assert "/model ollama llama3.2" in result
    assert "/model openai gpt-4o" not in result
    assert "/model gemini gemini-2.5-pro" not in result


def test_handle_model_command_uses_dynamic_discovery_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_model_command

    config_path = tmp_path / "config.json"
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "openai",
                    "model": "openai/gpt-4o",
                }
            },
            "providers": {
                "openai": {"apiKey": "oa-key"},
                "gemini": {"apiKey": "gm-key"},
            },
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "nanobot.model_management.discover_models_for_provider",
        lambda _config, spec: {
            "openai": ["gpt-4.1-mini"],
            "gemini": [],
        }.get(spec.name, []),
    )

    result = handle_model_command("/model")

    assert "/model openai gpt-4.1-mini" in result
    assert "/model openai gpt-4o" in result
    assert "/model gemini " not in result


def test_handle_model_command_updates_config_from_provider_and_model_args(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_model_command

    config_path = tmp_path / "config.json"
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "anthropic",
                    "model": "anthropic/claude-sonnet-4-5",
                }
            },
            "providers": {
                "anthropic": {"apiKey": "ant-key"},
                "openai": {"apiKey": "oa-key"},
            },
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)

    result = handle_model_command("/model openai gpt-4o")
    updated = load_config(config_path)

    assert "Saved model configuration." in result
    assert "Restart nanobot to apply." in result
    assert updated.agents.defaults.provider == "openai"
    assert updated.agents.defaults.model == "openai/gpt-4o"


def test_handle_model_command_updates_config_from_full_model_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_model_command

    config_path = tmp_path / "config.json"
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "anthropic",
                    "model": "anthropic/claude-sonnet-4-5",
                }
            },
            "providers": {
                "anthropic": {"apiKey": "ant-key"},
                "openai": {"apiKey": "oa-key"},
            },
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)

    result = handle_model_command("/model openai/gpt-4o")
    updated = load_config(config_path)

    assert "Saved model configuration." in result
    assert updated.agents.defaults.provider == "openai"
    assert updated.agents.defaults.model == "openai/gpt-4o"


def test_handle_model_command_rejects_missing_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_model_command

    config_path = tmp_path / "config.json"
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "anthropic",
                    "model": "anthropic/claude-sonnet-4-5",
                }
            },
            "providers": {
                "anthropic": {"apiKey": "ant-key"},
                "openai": {"apiKey": ""},
            },
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)

    result = handle_model_command("/model openai gpt-4o")
    updated = load_config(config_path)

    assert "Cannot switch to `openai/gpt-4o`." in result
    assert "providers.openai.apiKey" in result
    assert str(config_path) in result
    assert updated.agents.defaults.provider == "anthropic"
    assert updated.agents.defaults.model == "anthropic/claude-sonnet-4-5"


def test_handle_model_command_normalizes_local_provider_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_model_command

    config_path = tmp_path / "config.json"
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "anthropic",
                    "model": "anthropic/claude-sonnet-4-5",
                }
            },
            "providers": {
                "anthropic": {"apiKey": "ant-key"},
                "ollama": {"apiBase": "http://localhost:11434"},
            },
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)

    result = handle_model_command("/model ollama llama3.2")
    updated = load_config(config_path)

    assert "Saved model configuration." in result
    assert updated.agents.defaults.provider == "ollama"
    assert updated.agents.defaults.model == "llama3.2"


@pytest.mark.asyncio
async def test_agent_loop_handles_model_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "anthropic",
                    "model": "anthropic/claude-sonnet-4-5",
                }
            },
            "providers": {"anthropic": {"apiKey": "ant-key"}},
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "nanobot.model_management.discover_models_for_provider",
        lambda _config, spec: ["claude-sonnet-4-5"] if spec.name == "anthropic" else [],
    )

    loop = _make_loop(tmp_path)
    msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/model")

    response = await loop._process_message(msg)

    assert response is not None
    assert "Model Configuration" in response.content
    assert "/model anthropic claude-sonnet-4-5" in response.content
