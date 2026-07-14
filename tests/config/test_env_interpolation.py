import json

import pytest

from nanobot.config.loader import load_raw_config, save_config
from nanobot.config.repository import resolve_config_env_vars
from nanobot.config.schema import Config


class TestResolveConfig:
    def test_resolves_multiple_refs_inside_a_value(self, monkeypatch):
        monkeypatch.setenv("TEST_USER", "alice")
        monkeypatch.setenv("TEST_PASSWORD", "secret")
        config = Config.model_validate(
            {"providers": {"groq": {"apiKey": "${TEST_USER}:${TEST_PASSWORD}"}}}
        )

        resolved = resolve_config_env_vars(config)

        assert resolved.providers.groq.api_key == "alice:secret"

    def test_missing_var_raises(self):
        config = Config.model_validate(
            {"providers": {"groq": {"apiKey": "${DOES_NOT_EXIST}"}}}
        )

        with pytest.raises(ValueError, match="DOES_NOT_EXIST"):
            resolve_config_env_vars(config)

    def test_resolves_env_vars_in_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "resolved-key")
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {"providers": {"groq": {"apiKey": "${TEST_API_KEY}"}}}
            ),
            encoding="utf-8",
        )

        raw = load_raw_config(config_path)
        assert raw.providers.groq.api_key == "${TEST_API_KEY}"

        resolved = resolve_config_env_vars(raw)
        assert resolved.providers.groq.api_key == "resolved-key"

    def test_save_preserves_templates(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "real-token")
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {"channels": {"telegram": {"token": "${MY_TOKEN}"}}}
            ),
            encoding="utf-8",
        )

        raw = load_raw_config(config_path)
        save_config(raw, config_path)

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["channels"]["telegram"]["token"] == "${MY_TOKEN}"

    def test_save_preserves_dream_legacy_cron(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {"agents": {"defaults": {"dream": {"cron": "0 */4 * * *"}}}}
            ),
            encoding="utf-8",
        )

        config = load_raw_config(config_path)
        config.agents.defaults.max_tokens = 1234
        save_config(config, config_path)

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["agents"]["defaults"]["dream"]["cron"] == "0 */4 * * *"

        reloaded = load_raw_config(config_path)
        schedule = reloaded.agents.defaults.dream.build_schedule("UTC")
        assert schedule.kind == "cron"
        assert schedule.expr == "0 */4 * * *"

    def test_save_keeps_oauth_provider_configs_excluded(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "agents": {"defaults": {"dream": {"cron": "0 */4 * * *"}}},
                    "providers": {
                        "openaiCodex": {"apiKey": "codex-secret"},
                        "githubCopilot": {"apiKey": "copilot-secret"},
                        "groq": {"apiKey": "groq-secret"},
                    },
                }
            ),
            encoding="utf-8",
        )

        config = load_raw_config(config_path)
        save_config(config, config_path)

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["agents"]["defaults"]["dream"]["cron"] == "0 */4 * * *"
        assert "openaiCodex" not in saved["providers"]
        assert "githubCopilot" not in saved["providers"]
        assert saved["providers"]["groq"]["apiKey"] == "groq-secret"

    def test_save_preserves_openai_codex_proxy_config(self, tmp_path):
        config_path = tmp_path / "config.json"
        proxy = "http://127.0.0.1:23458"
        config = Config.model_validate(
            {
                "providers": {
                    "openaiCodex": {
                        "apiKey": "codex-secret",
                        "proxy": proxy,
                    },
                    "groq": {"apiKey": "groq-secret"},
                }
            }
        )

        save_config(config, config_path)

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["providers"]["openaiCodex"] == {"proxy": proxy}
        assert saved["providers"]["groq"]["apiKey"] == "groq-secret"

        reloaded = load_raw_config(config_path)
        assert reloaded.providers.openai_codex.proxy == proxy
        assert reloaded.providers.openai_codex.api_key is None

    def test_preserves_excluded_fields_when_no_env_refs(self, tmp_path):
        """Regression: fields with ``exclude=True`` (e.g. ProviderConfig.openai_codex)
        must survive ``resolve_config_env_vars`` when the config has no
        ``${VAR}`` references. Previously the unconditional dump→revalidate
        roundtrip silently dropped them."""
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {"providers": {"openaiCodex": {"apiKey": "secret"}}}
            ),
            encoding="utf-8",
        )

        raw = load_raw_config(config_path)
        assert raw.providers.openai_codex.api_key == "secret"

        resolved = resolve_config_env_vars(raw)
        assert resolved.providers.openai_codex.api_key == "secret"

    def test_preserves_excluded_fields_with_env_refs(self, tmp_path, monkeypatch):
        """Excluded fields must also survive when the config contains
        ``${VAR}`` refs elsewhere. An in-place walk preserves the excluded
        field even as unrelated string fields are substituted."""
        monkeypatch.setenv("TEST_API_KEY", "resolved-key")
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "providers": {
                        "openaiCodex": {"apiKey": "secret"},
                        "groq": {"apiKey": "${TEST_API_KEY}"},
                    }
                }
            ),
            encoding="utf-8",
        )

        raw = load_raw_config(config_path)
        resolved = resolve_config_env_vars(raw)

        assert resolved.providers.groq.api_key == "resolved-key"
        assert resolved.providers.openai_codex.api_key == "secret"
