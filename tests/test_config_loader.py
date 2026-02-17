"""Tests for config schema-driven loading (alias_generator approach)."""

import json

from nanobot.config.loader import _migrate_config, load_config, save_config
from nanobot.config.schema import (
    Config,
    MCPServerConfig,
    ProviderConfig,
    ToolsConfig,
    _snake_to_camel,
)

# ---------------------------------------------------------------------------
# _snake_to_camel helper
# ---------------------------------------------------------------------------

class TestSnakeToCamel:
    """Tests for the alias_generator helper."""

    def test_simple(self):
        assert _snake_to_camel("snake_case") == "snakeCase"

    def test_multiple_words(self):
        assert _snake_to_camel("this_is_a_test") == "thisIsATest"

    def test_single_word(self):
        assert _snake_to_camel("word") == "word"

    def test_already_no_underscores(self):
        assert _snake_to_camel("alreadycamel") == "alreadycamel"

    def test_empty_string(self):
        assert _snake_to_camel("") == ""

    def test_field_names_from_schema(self):
        """Verify the helper produces correct aliases for real schema fields."""
        assert _snake_to_camel("mcp_servers") == "mcpServers"
        assert _snake_to_camel("extra_headers") == "extraHeaders"
        assert _snake_to_camel("restrict_to_workspace") == "restrictToWorkspace"
        assert _snake_to_camel("bridge_url") == "bridgeUrl"
        assert _snake_to_camel("api_key") == "apiKey"
        assert _snake_to_camel("max_tool_iterations") == "maxToolIterations"


# ---------------------------------------------------------------------------
# Model validation: loading camelCase JSON
# ---------------------------------------------------------------------------

class TestModelValidateFromCamelCase:
    """Config.model_validate should accept camelCase keys from JSON."""

    def test_loads_top_level_fields(self):
        data = {
            "agents": {"defaults": {"model": "gpt-4", "maxTokens": 4096}},
        }
        cfg = Config.model_validate(data)
        assert cfg.agents.defaults.model == "gpt-4"
        assert cfg.agents.defaults.max_tokens == 4096

    def test_loads_mcp_server(self):
        data = {
            "tools": {
                "mcpServers": {
                    "tavily": {
                        "command": "npx",
                        "args": ["-y", "@mcptools/mcp-tavily"],
                        "env": {"TAVILY_API_KEY": "tvly-secret"},
                    }
                }
            }
        }
        cfg = Config.model_validate(data)
        srv = cfg.tools.mcp_servers["tavily"]
        assert srv.command == "npx"
        assert srv.args == ["-y", "@mcptools/mcp-tavily"]
        assert srv.env == {"TAVILY_API_KEY": "tvly-secret"}

    def test_loads_provider_with_extra_headers(self):
        data = {
            "providers": {
                "openai": {
                    "apiKey": "sk-xxx",
                    "extraHeaders": {
                        "X-Custom-Header": "value",
                        "Authorization": "Bearer xyz",
                    },
                }
            }
        }
        cfg = Config.model_validate(data)
        assert cfg.providers.openai.api_key == "sk-xxx"
        assert cfg.providers.openai.extra_headers == {
            "X-Custom-Header": "value",
            "Authorization": "Bearer xyz",
        }

    def test_loads_snake_case_fields_too(self):
        """populate_by_name=True means snake_case field names also work."""
        data = {
            "tools": {
                "restrict_to_workspace": True,
                "mcp_servers": {
                    "test": {"command": "echo"},
                },
            }
        }
        cfg = Config.model_validate(data)
        assert cfg.tools.restrict_to_workspace is True
        assert "test" in cfg.tools.mcp_servers

    def test_defaults_when_empty(self):
        cfg = Config.model_validate({})
        assert cfg.agents.defaults.model == "anthropic/claude-opus-4-5"
        assert cfg.tools.mcp_servers == {}
        assert cfg.providers.openai.api_key == ""


# ---------------------------------------------------------------------------
# Env var / arbitrary dict key preservation
# ---------------------------------------------------------------------------

class TestEnvKeyPreservation:
    """Env var keys must never be mangled by alias_generator."""

    def test_uppercase_env_keys_preserved(self):
        srv = MCPServerConfig.model_validate({
            "command": "npx",
            "env": {"TAVILY_API_KEY": "secret", "NODE_ENV": "production"},
        })
        assert srv.env == {"TAVILY_API_KEY": "secret", "NODE_ENV": "production"}

    def test_mixed_case_env_keys_preserved(self):
        srv = MCPServerConfig.model_validate({
            "command": "cmd",
            "env": {"myKey": "val", "UPPER": "1", "lower": "2"},
        })
        assert srv.env == {"myKey": "val", "UPPER": "1", "lower": "2"}

    def test_env_keys_with_special_chars(self):
        srv = MCPServerConfig.model_validate({
            "command": "cmd",
            "env": {"MY_VAR_123": "x", "PATH": "/usr/bin"},
        })
        assert srv.env["MY_VAR_123"] == "x"
        assert srv.env["PATH"] == "/usr/bin"

    def test_empty_env_dict(self):
        srv = MCPServerConfig.model_validate({"command": "cmd", "env": {}})
        assert srv.env == {}

    def test_extra_headers_preserved(self):
        prov = ProviderConfig.model_validate({
            "apiKey": "sk-xxx",
            "extraHeaders": {"X-Request-ID": "abc", "APP-Code": "hub123"},
        })
        assert prov.extra_headers == {"X-Request-ID": "abc", "APP-Code": "hub123"}

    def test_mcp_server_names_preserved(self):
        """MCP server names are dict keys and must not be converted."""
        data = {
            "mcpServers": {
                "my-custom-server": {"command": "cmd1"},
                "another_server": {"command": "cmd2"},
                "CamelServer": {"command": "cmd3"},
            }
        }
        cfg = ToolsConfig.model_validate(data)
        assert "my-custom-server" in cfg.mcp_servers
        assert "another_server" in cfg.mcp_servers
        assert "CamelServer" in cfg.mcp_servers


# ---------------------------------------------------------------------------
# model_dump(by_alias=True): saving to camelCase
# ---------------------------------------------------------------------------

class TestModelDumpByAlias:
    """model_dump(by_alias=True) should produce camelCase field names."""

    def test_simple_field_aliases(self):
        srv = MCPServerConfig(command="npx", args=["-y", "pkg"])
        d = srv.model_dump(by_alias=True)
        assert d["command"] == "npx"
        assert d["args"] == ["-y", "pkg"]

    def test_nested_config_aliases(self):
        cfg = Config()
        d = cfg.model_dump(by_alias=True)
        assert "agents" in d
        assert "tools" in d
        assert "providers" in d
        assert "maxTokens" in d["agents"]["defaults"]
        assert "mcpServers" in d["tools"]
        assert "restrictToWorkspace" in d["tools"]
        assert "extraHeaders" in d["providers"]["openai"]

    def test_env_keys_preserved_on_dump(self):
        srv = MCPServerConfig(
            command="npx",
            env={"TAVILY_API_KEY": "tvly-secret", "NODE_ENV": "production"},
        )
        d = srv.model_dump(by_alias=True)
        assert d["env"] == {"TAVILY_API_KEY": "tvly-secret", "NODE_ENV": "production"}

    def test_extra_headers_preserved_on_dump(self):
        prov = ProviderConfig(
            api_key="sk-xxx",
            extra_headers={"X-Custom": "val", "APP-Code": "abc"},
        )
        d = prov.model_dump(by_alias=True)
        assert d["extraHeaders"] == {"X-Custom": "val", "APP-Code": "abc"}
        assert d["apiKey"] == "sk-xxx"

    def test_mcp_server_names_preserved_on_dump(self):
        cfg = ToolsConfig(mcp_servers={
            "my-server": MCPServerConfig(command="cmd"),
            "UPPER_SERVER": MCPServerConfig(command="cmd2"),
        })
        d = cfg.model_dump(by_alias=True)
        assert "my-server" in d["mcpServers"]
        assert "UPPER_SERVER" in d["mcpServers"]


# ---------------------------------------------------------------------------
# Round-trip: load camelCase JSON → model_validate → model_dump → same JSON
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """Config should round-trip through model_validate + model_dump(by_alias=True)."""

    def test_mcp_config_round_trip(self):
        original = {
            "tools": {
                "mcpServers": {
                    "tavily": {
                        "command": "npx",
                        "args": ["-y", "@mcptools/mcp-tavily"],
                        "env": {"TAVILY_API_KEY": "tvly-secret-key"},
                    }
                }
            }
        }
        cfg = Config.model_validate(original)
        dumped = cfg.model_dump(by_alias=True)

        tavily = dumped["tools"]["mcpServers"]["tavily"]
        assert tavily["command"] == "npx"
        assert tavily["args"] == ["-y", "@mcptools/mcp-tavily"]
        assert tavily["env"]["TAVILY_API_KEY"] == "tvly-secret-key"

    def test_full_config_round_trip(self):
        original = {
            "tools": {
                "mcpServers": {
                    "server1": {
                        "command": "cmd",
                        "env": {"API_KEY": "key1", "DEBUG_MODE": "true"},
                    }
                },
                "restrictToWorkspace": True,
            },
            "providers": {
                "openai": {
                    "apiKey": "sk-xxx",
                    "extraHeaders": {"X-Request-ID": "123"},
                }
            },
            "agents": {
                "defaults": {
                    "model": "gpt-4",
                    "maxTokens": 4096,
                    "maxToolIterations": 30,
                }
            },
        }
        cfg = Config.model_validate(original)
        dumped = cfg.model_dump(by_alias=True)

        # Env keys preserved
        assert dumped["tools"]["mcpServers"]["server1"]["env"]["API_KEY"] == "key1"
        assert dumped["tools"]["mcpServers"]["server1"]["env"]["DEBUG_MODE"] == "true"
        # Header keys preserved
        assert dumped["providers"]["openai"]["extraHeaders"]["X-Request-ID"] == "123"
        # camelCase field names used
        assert dumped["providers"]["openai"]["apiKey"] == "sk-xxx"
        assert dumped["tools"]["restrictToWorkspace"] is True
        assert dumped["agents"]["defaults"]["maxTokens"] == 4096
        assert dumped["agents"]["defaults"]["maxToolIterations"] == 30

    def test_multiple_mcp_servers_round_trip(self):
        original = {
            "tools": {
                "mcpServers": {
                    "tavily": {
                        "command": "npx",
                        "env": {"TAVILY_API_KEY": "key1"},
                    },
                    "github": {
                        "command": "gh-mcp",
                        "env": {"GITHUB_TOKEN": "ghp_xxx"},
                    },
                }
            }
        }
        cfg = Config.model_validate(original)
        dumped = cfg.model_dump(by_alias=True)
        servers = dumped["tools"]["mcpServers"]
        assert servers["tavily"]["env"]["TAVILY_API_KEY"] == "key1"
        assert servers["github"]["env"]["GITHUB_TOKEN"] == "ghp_xxx"


# ---------------------------------------------------------------------------
# load_config / save_config integration
# ---------------------------------------------------------------------------

class TestLoadSaveConfig:
    """Integration tests using actual file I/O."""

    def test_load_config_from_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "tools": {
                "mcpServers": {
                    "tavily": {
                        "command": "npx",
                        "args": ["-y", "@mcptools/mcp-tavily"],
                        "env": {"TAVILY_API_KEY": "tvly-secret"},
                    }
                }
            },
            "agents": {"defaults": {"maxTokens": 2048}},
        }))
        cfg = load_config(config_file)
        assert cfg.tools.mcp_servers["tavily"].env["TAVILY_API_KEY"] == "tvly-secret"
        assert cfg.agents.defaults.max_tokens == 2048

    def test_load_config_missing_file_returns_default(self, tmp_path):
        cfg = load_config(tmp_path / "nonexistent.json")
        assert cfg.agents.defaults.model == "anthropic/claude-opus-4-5"
        assert cfg.tools.mcp_servers == {}

    def test_load_config_invalid_json_returns_default(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json{{{")
        cfg = load_config(config_file)
        assert cfg.agents.defaults.model == "anthropic/claude-opus-4-5"

    def test_save_config_creates_file(self, tmp_path):
        cfg = Config()
        config_file = tmp_path / "subdir" / "config.json"
        save_config(cfg, config_file)
        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert "agents" in data
        assert "mcpServers" in data["tools"]

    def test_save_and_reload_preserves_env_keys(self, tmp_path):
        """The critical test: save → reload must preserve env var keys."""
        config_file = tmp_path / "config.json"

        cfg = Config.model_validate({
            "tools": {
                "mcpServers": {
                    "tavily": {
                        "command": "npx",
                        "env": {"TAVILY_API_KEY": "tvly-roundtrip"},
                    }
                }
            }
        })
        save_config(cfg, config_file)

        # Reload from file
        reloaded = load_config(config_file)
        assert reloaded.tools.mcp_servers["tavily"].env["TAVILY_API_KEY"] == "tvly-roundtrip"

    def test_save_and_reload_preserves_extra_headers(self, tmp_path):
        config_file = tmp_path / "config.json"

        cfg = Config.model_validate({
            "providers": {
                "aihubmix": {
                    "apiKey": "sk-hub",
                    "extraHeaders": {"APP-Code": "my-code"},
                }
            }
        })
        save_config(cfg, config_file)

        reloaded = load_config(config_file)
        assert reloaded.providers.aihubmix.extra_headers["APP-Code"] == "my-code"

    def test_saved_json_uses_camel_case(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = Config.model_validate({
            "tools": {"restrictToWorkspace": True},
            "agents": {"defaults": {"maxTokens": 1024}},
        })
        save_config(cfg, config_file)
        raw = json.loads(config_file.read_text())
        assert "restrictToWorkspace" in raw["tools"]
        assert "maxTokens" in raw["agents"]["defaults"]
        # snake_case keys should NOT appear in saved JSON
        assert "restrict_to_workspace" not in raw["tools"]
        assert "max_tokens" not in raw["agents"]["defaults"]


# ---------------------------------------------------------------------------
# _migrate_config
# ---------------------------------------------------------------------------

class TestMigrateConfig:
    """Tests for the config migration function."""

    def test_migrates_restrict_to_workspace(self):
        data = {
            "tools": {
                "exec": {"restrictToWorkspace": True, "timeout": 60},
            }
        }
        result = _migrate_config(data)
        assert result["tools"]["restrictToWorkspace"] is True
        assert "restrictToWorkspace" not in result["tools"]["exec"]

    def test_no_migration_needed(self):
        data = {"tools": {"restrictToWorkspace": False}}
        result = _migrate_config(data)
        assert result["tools"]["restrictToWorkspace"] is False

    def test_does_not_overwrite_existing(self):
        data = {
            "tools": {
                "restrictToWorkspace": False,
                "exec": {"restrictToWorkspace": True},
            }
        }
        result = _migrate_config(data)
        # Existing top-level value should not be overwritten
        assert result["tools"]["restrictToWorkspace"] is False

    def test_empty_config(self):
        assert _migrate_config({}) == {}


# ---------------------------------------------------------------------------
# _Base model behavior
# ---------------------------------------------------------------------------

class TestBaseModel:
    """Tests for the _Base model's alias_generator behavior."""

    def test_alias_generator_only_affects_field_names(self):
        """alias_generator should not touch dict values or dict keys inside fields."""
        srv = MCPServerConfig.model_validate({
            "command": "test_command",
            "env": {"SOME_KEY": "some_value"},
        })
        assert srv.command == "test_command"
        assert "SOME_KEY" in srv.env

    def test_inherits_config_from_base(self):
        """All schema models should inherit alias_generator from _Base."""
        d = MCPServerConfig(command="test").model_dump(by_alias=True)
        assert "command" in d

        d = ProviderConfig(api_key="k").model_dump(by_alias=True)
        assert "apiKey" in d
        assert "extraHeaders" in d
