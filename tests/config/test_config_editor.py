from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from nanobot.config.editor import (
    ConfigEditorError,
    config_editor_snapshot,
    update_config_editor,
)
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config, MCPServerConfig, ModelPresetConfig


def _secret(snapshot: dict[str, object], path: str) -> dict[str, object]:
    secrets = snapshot["secrets"]
    assert isinstance(secrets, list)
    return next(item for item in secrets if isinstance(item, dict) and item.get("path") == path)


def test_snapshot_is_complete_but_never_returns_stored_secrets(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = Config()
    config.providers.openai.api_key = "sk-provider-secret"
    config.api.api_key = "api-service-secret"
    config.channels.telegram = {
        "enabled": True,
        "token": "telegram-secret",
    }
    config.tools.mcp_servers["docs"] = MCPServerConfig(
        command="docs-mcp",
        env={"INTERNAL_VALUE": "mcp-env-secret"},
        headers={"X-Workspace": "mcp-header-secret"},
    )
    save_config(config, path)

    snapshot = config_editor_snapshot(config_path=path)
    serialized = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["version"] == 1
    assert len(str(snapshot["revision"])) == 64
    assert set(snapshot) == {"version", "revision", "config", "schema", "secrets", "presentation"}
    assert "sk-provider-secret" not in serialized
    assert "api-service-secret" not in serialized
    assert "telegram-secret" not in serialized
    assert "mcp-env-secret" not in serialized
    assert "mcp-header-secret" not in serialized
    assert _secret(snapshot, "/providers/openai/apiKey")["configured"] is True
    assert _secret(snapshot, "/api/apiKey")["configured"] is True
    assert _secret(snapshot, "/channels/telegram/token")["configured"] is True
    assert _secret(snapshot, "/tools/mcpServers/docs/env/INTERNAL_VALUE")["configured"] is True
    assert _secret(snapshot, "/tools/mcpServers/docs/headers/X-Workspace")["configured"] is True


def test_full_document_update_covers_every_top_level_config_domain(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = Config()
    config.providers.openai.api_key = "keep-me"
    save_config(config, path)
    snapshot = config_editor_snapshot(config_path=path)
    draft = deepcopy(snapshot["config"])
    assert isinstance(draft, dict)

    draft["agents"]["defaults"]["botName"] = "Mochi"
    draft["channels"]["sendProgress"] = False
    draft["channels"]["telegram"] = {"enabled": True, "token": "new-token"}
    draft["transcription"]["maxUploadMb"] = 40
    draft["providers"]["openai"]["apiBase"] = "https://api.example.test/v1"
    draft["api"]["port"] = 8911
    draft["gateway"]["heartbeat"]["keepRecentMessages"] = 12
    draft["tools"]["exec"]["timeout"] = 75
    draft["tools"]["mcpServers"] = {
        "docs": {
            "command": "docs-mcp",
            "env": {"DOCS_TOKEN": "new-mcp-token"},
        }
    }
    draft["modelPresets"] = {
        "fast": {
            "model": "openai/gpt-test",
            "provider": "openai",
            "maxTokens": 4096,
            "contextWindowTokens": 128000,
            "temperature": 0.2,
        }
    }

    updated = update_config_editor(
        {"revision": snapshot["revision"], "config": draft},
        config_path=path,
    )
    saved = load_config(path)

    assert saved.agents.defaults.bot_name == "Mochi"
    assert saved.channels.send_progress is False
    assert saved.channels.telegram["token"] == "new-token"
    assert saved.transcription.max_upload_mb == 40
    assert saved.providers.openai.api_key == "keep-me"
    assert saved.providers.openai.api_base == "https://api.example.test/v1"
    assert saved.api.port == 8911
    assert saved.gateway.heartbeat.keep_recent_messages == 12
    assert saved.tools.exec.timeout == 75
    assert saved.tools.mcp_servers["docs"].env["DOCS_TOKEN"] == "new-mcp-token"
    assert saved.model_presets["fast"] == ModelPresetConfig(
        model="openai/gpt-test",
        provider="openai",
        max_tokens=4096,
        context_window_tokens=128000,
        temperature=0.2,
    )
    assert _secret(updated, "/providers/openai/apiKey")["configured"] is True
    assert _secret(updated, "/channels/telegram/token")["configured"] is True


def test_redacted_secret_is_preserved_replaced_and_cleared_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = Config()
    config.providers.openai.api_key = "original"
    save_config(config, path)

    first = config_editor_snapshot(config_path=path)
    unchanged = update_config_editor(
        {"revision": first["revision"], "config": first["config"]},
        config_path=path,
    )
    assert load_config(path).providers.openai.api_key == "original"

    replacement = deepcopy(unchanged["config"])
    replacement["providers"]["openai"]["apiKey"] = "replacement"
    cleared = update_config_editor(
        {"revision": unchanged["revision"], "config": replacement},
        config_path=path,
    )
    assert load_config(path).providers.openai.api_key == "replacement"

    clear_draft = deepcopy(cleared["config"])
    clear_draft["providers"]["openai"]["apiKey"] = ""
    update_config_editor(
        {"revision": cleared["revision"], "config": clear_draft},
        config_path=path,
    )
    assert load_config(path).providers.openai.api_key == ""


def test_update_rejects_stale_and_invalid_drafts(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_config(Config(), path)
    snapshot = config_editor_snapshot(config_path=path)

    changed = load_config(path)
    changed.api.port = 8999
    save_config(changed, path)
    with pytest.raises(ConfigEditorError, match="changed on disk") as stale:
        update_config_editor(
            {"revision": snapshot["revision"], "config": snapshot["config"]},
            config_path=path,
        )
    assert stale.value.status == 409

    current = config_editor_snapshot(config_path=path)
    invalid = deepcopy(current["config"])
    invalid["api"]["port"] = "not-a-port"
    with pytest.raises(ConfigEditorError, match="invalid setting") as validation:
        update_config_editor(
            {"revision": current["revision"], "config": invalid},
            config_path=path,
        )
    assert validation.value.status == 400
    assert validation.value.issues
    assert validation.value.issues[0]["path"].endswith("/port")


def test_presentation_assigns_every_root_schema_domain_to_a_section(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    snapshot = config_editor_snapshot(config_path=path)
    schema = snapshot["schema"]
    presentation = snapshot["presentation"]
    assert isinstance(schema, dict)
    assert isinstance(presentation, dict)
    properties = schema["properties"]
    sections = presentation["sections"]
    assigned_roots = {
        prefix.split("/")[1]
        for section in sections
        for prefix in section["prefixes"]
        if prefix.count("/") == 1
    }

    assert set(properties) <= assigned_roots
