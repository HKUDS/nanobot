import json

import pytest

from nanobot.config.loader import load_config
from nanobot.config.schema import ApiConfig


def test_load_config_missing_file_uses_defaults(tmp_path) -> None:
    config = load_config(tmp_path / "missing.json")

    assert config.agents.defaults.model


def test_load_config_invalid_json_fails_fast(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken json", encoding="utf-8")

    with pytest.raises(ValueError, match="Failed to load config"):
        load_config(config_path)


def test_load_config_invalid_schema_fails_fast(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"tools": {"exec": {"timeout": -1}}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Failed to load config"):
        load_config(config_path)


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_api_config_requires_key_for_wildcard_hosts(host: str) -> None:
    with pytest.raises(ValueError, match="api_key is not set"):
        ApiConfig(host=host)


def test_api_config_allows_wildcard_host_with_key() -> None:
    config = ApiConfig(host="0.0.0.0", api_key="secret")

    assert config.host == "0.0.0.0"
    assert config.api_key == "secret"


def test_api_config_local_unauthenticated_mode_defaults_to_disabled() -> None:
    assert ApiConfig().allow_unauthenticated_local is False


def test_api_config_wildcard_rejects_unauthenticated_local_exemption() -> None:
    with pytest.raises(ValueError, match="api_key is not set"):
        ApiConfig(host="0.0.0.0", allow_unauthenticated_local=True)
