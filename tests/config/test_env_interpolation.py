import json

import pytest

from nanobot.config.loader import (
    _resolve_env_vars,
    load_config,
    resolve_config_env_vars,
    save_config,
)


class TestResolveEnvVars:
    def test_replaces_string_value(self, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "hunter2")
        assert _resolve_env_vars("${MY_SECRET}") == "hunter2"

    def test_partial_replacement(self, monkeypatch):
        monkeypatch.setenv("HOST", "example.com")
        assert _resolve_env_vars("https://${HOST}/api") == "https://example.com/api"

    def test_multiple_vars_in_one_string(self, monkeypatch):
        monkeypatch.setenv("USER", "alice")
        monkeypatch.setenv("PASS", "secret")
        assert _resolve_env_vars("${USER}:${PASS}") == "alice:secret"

    def test_nested_dicts(self, monkeypatch):
        monkeypatch.setenv("TOKEN", "abc123")
        data = {"channels": {"telegram": {"token": "${TOKEN}"}}}
        result = _resolve_env_vars(data)
        assert result["channels"]["telegram"]["token"] == "abc123"

    def test_lists(self, monkeypatch):
        monkeypatch.setenv("VAL", "x")
        assert _resolve_env_vars(["${VAL}", "plain"]) == ["x", "plain"]

    def test_ignores_non_strings(self):
        assert _resolve_env_vars(42) == 42
        assert _resolve_env_vars(True) is True
        assert _resolve_env_vars(None) is None
        assert _resolve_env_vars(3.14) == 3.14

    def test_plain_strings_unchanged(self):
        assert _resolve_env_vars("no vars here") == "no vars here"

    def test_missing_var_raises(self):
        with pytest.raises(ValueError, match="DOES_NOT_EXIST"):
            _resolve_env_vars("${DOES_NOT_EXIST}")


class TestResolveConfig:
    def test_resolves_env_vars_in_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "resolved-key")
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {"providers": {"groq": {"apiKey": "${TEST_API_KEY}"}}}
            ),
            encoding="utf-8",
        )

        raw = load_config(config_path)
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

        raw = load_config(config_path)
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

        config = load_config(config_path)
        config.agents.defaults.max_tokens = 1234
        save_config(config, config_path)

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["agents"]["defaults"]["dream"]["cron"] == "0 */4 * * *"

        reloaded = load_config(config_path)
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

        config = load_config(config_path)
        save_config(config, config_path)

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["agents"]["defaults"]["dream"]["cron"] == "0 */4 * * *"
        assert "openaiCodex" not in saved["providers"]
        assert "githubCopilot" not in saved["providers"]
        assert saved["providers"]["groq"]["apiKey"] == "groq-secret"

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

        raw = load_config(config_path)
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

        raw = load_config(config_path)
        resolved = resolve_config_env_vars(raw)

        assert resolved.providers.groq.api_key == "resolved-key"
        assert resolved.providers.openai_codex.api_key == "secret"
