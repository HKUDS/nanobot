import shlex
import sys
from pathlib import Path

import pytest

from nanobot.config.secret_refs import SecretRefError, resolve_config_value


def test_resolve_file_ref_absolute_path(tmp_path: Path) -> None:
    secret = tmp_path / "openai-key.txt"
    secret.write_text("sk-test-123\n", encoding="utf-8")

    value = resolve_config_value(
        f"{{file:{secret}}}",
        field_path="providers.openai.api_key",
    )

    assert value == "sk-test-123"


def test_resolve_inline_refs(tmp_path: Path) -> None:
    token = tmp_path / "token.txt"
    token.write_text("abc", encoding="utf-8")

    value = resolve_config_value(
        f"Bearer {{file:{token}}}",
        field_path="tools.mcp_servers.demo.headers.Authorization",
    )

    assert value == "Bearer abc"


def test_resolve_recursive_dict_and_list(tmp_path: Path) -> None:
    secret = tmp_path / "key.txt"
    secret.write_text("demo-key", encoding="utf-8")

    payload = {
        "headers": {
            "Authorization": f"Bearer {{file:{secret}}}",
        },
        "args": ["--token", f"{{file:{secret}}}"],
        "enabled": True,
    }

    resolved = resolve_config_value(
        payload,
        field_path="tools.mcp_servers.demo",
    )

    assert resolved["headers"]["Authorization"] == "Bearer demo-key"
    assert resolved["args"][1] == "demo-key"
    assert resolved["enabled"] is True


def test_relative_file_ref_uses_active_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = tmp_path / "instance-a"
    instance.mkdir(parents=True)
    config_path = instance / "config.json"
    secret = instance / "mcp-token.txt"
    secret.write_text("token-xyz\n", encoding="utf-8")

    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: config_path)

    value = resolve_config_value(
        "{file:mcp-token.txt}",
        field_path="tools.mcp_servers.demo.headers.Authorization",
    )

    assert value == "token-xyz"


def test_resolve_exec_ref(tmp_path: Path) -> None:
    cmd = f"{shlex.quote(sys.executable)} -c \"print('cmd-secret')\""

    value = resolve_config_value(
        f"{{exec:{cmd}}}",
        field_path="providers.openrouter.api_key",
        base_dir=tmp_path,
    )

    assert value == "cmd-secret"


def test_exec_ref_rejects_empty_output(tmp_path: Path) -> None:
    cmd = f'{shlex.quote(sys.executable)} -c "pass"'

    with pytest.raises(SecretRefError, match="empty output"):
        resolve_config_value(
            f"{{exec:{cmd}}}",
            field_path="providers.openrouter.api_key",
            base_dir=tmp_path,
        )


def test_malformed_ref_raises_error() -> None:
    with pytest.raises(SecretRefError, match="malformed secret ref"):
        resolve_config_value(
            "Bearer {file:/tmp/not-closed",
            field_path="tools.mcp_servers.demo.headers.Authorization",
        )
