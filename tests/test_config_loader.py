import json
import os

from nanobot.config.loader import load_config


def _clear_nanobot_env(monkeypatch) -> None:
    for key in list(os.environ):
        if key.startswith("NANOBOT_"):
            monkeypatch.delenv(key, raising=False)


def test_load_config_applies_env_overrides_on_top_of_file(monkeypatch, tmp_path) -> None:
    _clear_nanobot_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "deepseek": {
                        "apiKey": "",
                        "apiBase": "https://file.example",
                    }
                },
                "agents": {
                    "defaults": {
                        "model": "file-model",
                        "workspace": "~/file-workspace",
                    }
                },
            }
        )
    )

    monkeypatch.setenv("NANOBOT_PROVIDERS__DEEPSEEK__API_KEY", "env-secret")
    monkeypatch.setenv("NANOBOT_AGENTS__DEFAULTS__WORKSPACE", "~/env-workspace")

    config = load_config(config_path)

    assert config.providers.deepseek.api_key == "env-secret"
    assert config.providers.deepseek.api_base == "https://file.example"
    assert config.agents.defaults.workspace == "~/env-workspace"
    assert config.agents.defaults.model == "file-model"


def test_load_config_parses_scalar_env_values(monkeypatch, tmp_path) -> None:
    _clear_nanobot_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"gateway": {"port": 18790}}))

    monkeypatch.setenv("NANOBOT_GATEWAY__PORT", "18791")

    config = load_config(config_path)

    assert config.gateway.port == 18791


def test_load_config_falls_back_to_env_defaults_for_non_object_json(
    monkeypatch, tmp_path, capsys
) -> None:
    _clear_nanobot_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(["not", "an", "object"]))

    monkeypatch.setenv("NANOBOT_GATEWAY__PORT", "18791")

    config = load_config(config_path)
    captured = capsys.readouterr()

    assert "Failed to load config" in captured.out
    assert config.gateway.port == 18791
