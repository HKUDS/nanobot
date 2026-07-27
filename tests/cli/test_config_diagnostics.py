import json

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app

runner = CliRunner()


def test_config_check_accepts_valid_file(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["config", "check", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Configuration is valid" in result.stdout


def test_config_check_reports_json_location_without_traceback(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken", encoding="utf-8")

    result = runner.invoke(app, ["config", "check", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Invalid configuration" in result.stdout
    assert "JSON syntax error at line 1, column 2" in result.stdout
    assert "Traceback" not in result.stdout


def test_config_check_reports_field_without_exposing_secret(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    secret = "should-never-appear"
    config_path.write_text(
        json.dumps({"providers": {"openrouter": {"apiKey": [secret]}}}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "check", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "providers.openrouter.apiKey" in result.stdout
    assert secret not in result.stdout
    assert "input_value" not in result.stdout
    assert "errors.pydantic.dev" not in result.stdout


def test_config_check_reports_missing_env_var_at_field(tmp_path, monkeypatch) -> None:
    name = "NANOBOT_TEST_CONFIG_CHECK_MISSING"
    monkeypatch.delenv(name, raising=False)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"providers": {"openrouter": {"apiKey": f"${{{name}}}"}}}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "check", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "providers.openrouter.apiKey" in result.stdout
    assert name in result.stdout


def test_config_check_validates_channel_schema_before_it_is_enabled(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {"channels": {"websocket": {"enabled": False, "path": "missing-slash"}}}
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "check", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "channels.websocket.path" in result.stdout
    assert 'Path must start with "/"' in result.stdout
    assert "Traceback" not in result.stdout


def test_config_check_validates_channel_without_optional_dependencies(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "channels": {
                    "matrix": {
                        "enabled": True,
                        "groupPolicy": "not-a-policy",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "check", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "channels.matrix.groupPolicy" in result.stdout
    assert "open" in result.stdout
    assert "Traceback" not in result.stdout


def test_gateway_reports_websocket_config_error_without_exposing_secret(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    secret = "should-never-appear"
    config_path.write_text(
        json.dumps(
            {
                "channels": {
                    "websocket": {
                        "enabled": True,
                        "path": "missing-slash",
                        "token": [secret],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_path)])
    output = result.stdout

    assert result.exit_code == 1
    assert "channels.websocket.path" in output
    assert "channels.websocket.token" in output
    assert "nanobot config check" in output
    assert secret not in output
    assert "input_value" not in output
    assert "errors.pydantic.dev" not in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    "args",
    [
        ["onboard", "--refresh"],
        ["plugins", "list"],
        ["gateway"],
        ["agent", "--message", "hello"],
    ],
)
def test_config_consumers_exit_cleanly_on_invalid_file(tmp_path, args: list[str]) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken", encoding="utf-8")

    result = runner.invoke(app, [*args, "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Invalid configuration" in result.stdout
    assert "nanobot config check" in result.stdout
    assert "Traceback" not in result.stdout


def test_config_check_missing_file_points_to_onboard(tmp_path) -> None:
    config_path = tmp_path / "missing.json"

    result = runner.invoke(app, ["config", "check", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Configuration file not found" in result.stdout
    assert "nanobot onboard" in result.stdout
