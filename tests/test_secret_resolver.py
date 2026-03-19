"""Tests for secret_resolver module."""

import pytest

from nanobot.config.secret_resolver import resolve_config, resolve_env_vars


class TestResolveEnvVars:
    """Tests for resolve_env_vars function."""

    def test_simple_replacement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR", "secret_value")
        assert resolve_env_vars("{env:TEST_VAR}") == "secret_value"

    def test_replacement_with_prefix_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "abc123")
        assert resolve_env_vars("prefix-{env:API_KEY}-suffix") == "prefix-abc123-suffix"

    def test_multiple_replacements(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("USER", "alice")
        monkeypatch.setenv("HOST", "example.com")
        assert resolve_env_vars("{env:USER}@{env:HOST}") == "alice@example.com"

    def test_unresolved_var_kept_unchanged(self) -> None:
        assert resolve_env_vars("{env:NONEXISTENT_VAR_XYZ}") == "{env:NONEXISTENT_VAR_XYZ}"

    def test_empty_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EMPTY_VAR", "")
        assert resolve_env_vars("{env:EMPTY_VAR}") == ""

    def test_no_env_refs_returns_unchanged(self) -> None:
        assert resolve_env_vars("plain string") == "plain string"
        assert resolve_env_vars("") == ""

    def test_invalid_var_name_format_ignored(self) -> None:
        # Lowercase should not match (env var names must be uppercase)
        assert resolve_env_vars("{env:lowercase}") == "{env:lowercase}"
        # Starting with number should not match
        assert resolve_env_vars("{env:123VAR}") == "{env:123VAR}"


class TestResolveConfig:
    """Tests for resolve_config function."""

    def test_resolve_dict_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "my_secret")
        config = {"api_key": "{env:SECRET_KEY}", "name": "test"}
        resolved = resolve_config(config)
        assert resolved["api_key"] == "my_secret"
        assert resolved["name"] == "test"

    def test_resolve_nested_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOT_TOKEN", "token123")
        config = {"telegram": {"token": "{env:BOT_TOKEN}", "enabled": True}}
        resolved = resolve_config(config)
        assert resolved["telegram"]["token"] == "token123"
        assert resolved["telegram"]["enabled"] is True

    def test_resolve_list_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KEY1", "val1")
        monkeypatch.setenv("KEY2", "val2")
        config = ["{env:KEY1}", "static", "{env:KEY2}"]
        resolved = resolve_config(config)
        assert resolved == ["val1", "static", "val2"]

    def test_resolve_nested_list_in_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "key123")
        config = {"allowed_keys": ["{env:API_KEY}", "default_key"]}
        resolved = resolve_config(config)
        assert resolved["allowed_keys"] == ["key123", "default_key"]

    def test_non_string_types_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NUM", "42")
        config = {"count": 42, "ratio": 3.14, "enabled": True, "name": None}
        resolved = resolve_config(config)
        assert resolved["count"] == 42
        assert resolved["ratio"] == 3.14
        assert resolved["enabled"] is True
        assert resolved["name"] is None

    def test_empty_structures(self) -> None:
        assert resolve_config({}) == {}
        assert resolve_config([]) == []

    def test_real_world_provider_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZHIPU_API_KEY", "zhipu_secret")
        monkeypatch.setenv("OPENAI_API_KEY", "openai_secret")
        config = {
            "providers": {
                "zhipu": {"apiKey": "{env:ZHIPU_API_KEY}", "apiBase": "https://api.zhipu.cn"},
                "openai": {"apiKey": "{env:OPENAI_API_KEY}", "apiBase": None},
            }
        }
        resolved = resolve_config(config)
        assert resolved["providers"]["zhipu"]["apiKey"] == "zhipu_secret"
        assert resolved["providers"]["openai"]["apiKey"] == "openai_secret"
