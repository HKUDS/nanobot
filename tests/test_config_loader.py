import json

from nanobot.config.loader import load_config


def test_load_config_applies_env_overrides_on_top_of_file(monkeypatch, tmp_path) -> None:
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
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"gateway": {"port": 18790}}))

    monkeypatch.setenv("NANOBOT_GATEWAY__PORT", "18791")

    config = load_config(config_path)

    assert config.gateway.port == 18791
