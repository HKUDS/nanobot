import json

import pytest

from nanobot.config.errors import ConfigLoadError
from nanobot.config.loader import load_config
from nanobot.config.schema import ApiConfig


def test_load_config_missing_file_uses_defaults(tmp_path) -> None:
    config = load_config(tmp_path / "missing.json")

    assert config.agents.defaults.model


def test_load_config_reports_malformed_environment_safely(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "missing.json"
    invalid_value = "sensitive-not-json"
    monkeypatch.setenv("NANOBOT_PROVIDERS", invalid_value)

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_path)

    error = exc_info.value
    assert error.kind == "invalid_schema"
    assert error.path == config_path
    assert "complex NANOBOT_* values use valid JSON" in str(error)
    assert invalid_value not in str(error)


def test_load_config_invalid_json_fails_fast(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken json", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_path)

    error = exc_info.value
    assert error.kind == "invalid_json"
    assert "line 1, column 2" in str(error)


def test_load_config_invalid_schema_fails_fast(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"tools": {"exec": {"timeout": -1}}}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_path)

    error = exc_info.value
    message = str(error)
    assert error.kind == "invalid_schema"
    assert "tools.exec.timeout" in message
    assert "Must be greater than or equal to 0." in message
    assert "input_value" not in message
    assert "errors.pydantic.dev" not in message


@pytest.mark.parametrize(
    ("content", "root_type"),
    [("[]", "list"), ("null", "NoneType"), ('"value"', "str")],
)
def test_load_config_rejects_non_object_root(tmp_path, content: str, root_type: str) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_path)

    error = exc_info.value
    assert error.kind == "invalid_root"
    assert f"Expected an object, but found {root_type}." in str(error)


def test_load_config_error_does_not_expose_invalid_secret_value(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    secret = "should-never-appear"
    config_path.write_text(
        json.dumps({"providers": {"openrouter": {"apiKey": [secret]}}}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_path)

    assert secret not in str(exc_info.value)


def test_load_config_error_redacts_untrusted_location_parts(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    secret = "should-never-appear-in-location"
    server_name = f"https://user:{secret}@example.test"
    config_path.write_text(
        json.dumps(
            {
                "tools": {
                    "mcpServers": {
                        server_name: {"toolTimeout": "not-a-number"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_path)

    message = str(exc_info.value)
    assert "tools.mcpServers.<redacted>.toolTimeout" in message
    assert server_name not in message
    assert secret not in message


def test_load_config_error_does_not_trust_custom_validator_message(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    secret = "diagnostic-secret-should-not-print"
    config_path.write_text(
        json.dumps({"providers": {"openrouter": {"thinkingStyle": secret}}}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_path)

    message = str(exc_info.value)
    assert "providers.openrouter.thinkingStyle" in message
    assert "Value does not satisfy this setting's requirements." in message
    assert secret not in message


@pytest.mark.parametrize(
    "tools",
    [
        [],
        {"exec": []},
        {"my": 1, "myEnabled": True},
    ],
)
def test_load_config_malformed_legacy_sections_use_structured_error(
    tmp_path,
    tools: object,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"tools": tools}), encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_path)

    error = exc_info.value
    assert error.kind == "invalid_schema"
    assert "tools" in str(error)


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_api_config_requires_key_for_wildcard_hosts(host: str) -> None:
    with pytest.raises(ValueError, match="api_key is not set"):
        ApiConfig(host=host)


def test_api_config_allows_wildcard_host_with_key() -> None:
    config = ApiConfig(host="0.0.0.0", api_key="secret")

    assert config.host == "0.0.0.0"
    assert config.api_key == "secret"
