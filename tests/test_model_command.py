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


def test_handle_model_command_lists_only_current_provider_models(
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

    calls: list[str] = []

    def _discover(_config, spec):
        calls.append(spec.name)
        return ["gpt-4.1", "gpt-4o-mini"] if spec.name == "openai" else ["gemini-2.5-pro"]

    monkeypatch.setattr("nanobot.model_management.discover_models_for_provider", _discover)

    result = handle_model_command("/model")

    assert "Model Configuration" in result
    assert "Current provider: openai" in result
    assert "Current model: openai/gpt-4o" in result
    assert "/model gpt-4.1" in result
    assert "/model gpt-4o-mini" in result
    assert "gemini-2.5-pro" not in result
    assert calls == ["openai"]


def test_handle_model_command_updates_model_with_single_argument(
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
            },
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)

    result = handle_model_command("/model gpt-4.1")
    updated = load_config(config_path)

    assert "Saved model configuration." in result
    assert updated.agents.defaults.provider == "openai"
    assert updated.agents.defaults.model == "openai/gpt-4.1"


def test_handle_model_command_accepts_explicit_current_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_model_command

    config_path = tmp_path / "config.json"
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "ollama",
                    "model": "llama3.2",
                }
            },
            "providers": {
                "ollama": {"apiBase": "http://localhost:11434"},
            },
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)

    result = handle_model_command("/model ollama llama3.3")
    updated = load_config(config_path)

    assert "Saved model configuration." in result
    assert updated.agents.defaults.provider == "ollama"
    assert updated.agents.defaults.model == "llama3.3"


def test_handle_model_command_rejects_provider_switching(
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

    result = handle_model_command("/model gemini gemini-2.5-pro")
    updated = load_config(config_path)

    assert "Current provider is `openai`" in result
    assert updated.agents.defaults.provider == "openai"
    assert updated.agents.defaults.model == "openai/gpt-4o"


def test_handle_model_command_handles_invalid_shell_quoting(
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
            "providers": {"anthropic": {"apiKey": "ant-key"}},
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)

    result = handle_model_command('/model "')

    assert "Invalid command syntax." in result


def test_handle_provider_command_lists_available_providers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_provider_command

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
                "ollama": {"apiBase": "http://localhost:11434"},
            },
        }
    )
    _write_config(config_path, config)
    monkeypatch.setattr("nanobot.model_management.get_config_path", lambda: config_path)

    result = handle_provider_command("/provider")

    assert "Provider Configuration" in result
    assert "Current provider: openai" in result
    assert "/provider openai" in result
    assert "/provider gemini" in result
    assert "/provider ollama" in result


def test_handle_provider_command_switches_provider_and_sets_first_discovered_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_provider_command

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
        lambda _config, spec: ["gemini-2.5-pro", "gemini-2.0-flash"] if spec.name == "gemini" else ["gpt-4o"],
    )

    result = handle_provider_command("/provider gemini")
    updated = load_config(config_path)

    assert "Saved provider configuration." in result
    assert updated.agents.defaults.provider == "gemini"
    assert updated.agents.defaults.model == "gemini/gemini-2.5-pro"


def test_handle_provider_command_rejects_provider_without_discovered_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_provider_command

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
        lambda _config, spec: [] if spec.name == "gemini" else ["gpt-4o"],
    )

    result = handle_provider_command("/provider gemini")
    updated = load_config(config_path)

    assert "No models discovered for `gemini`" in result
    assert updated.agents.defaults.provider == "openai"
    assert updated.agents.defaults.model == "openai/gpt-4o"


def test_handle_provider_command_handles_invalid_shell_quoting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.model_management import handle_provider_command

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

    result = handle_provider_command('/provider "')

    assert "Invalid command syntax." in result


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
    assert "/model claude-sonnet-4-5" in response.content


@pytest.mark.asyncio
async def test_agent_loop_handles_provider_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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
        lambda _config, spec: ["gemini-2.5-pro"] if spec.name == "gemini" else ["gpt-4o"],
    )

    loop = _make_loop(tmp_path)
    msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/provider gemini")

    response = await loop._process_message(msg)

    assert response is not None
    assert "Saved provider configuration." in response.content
