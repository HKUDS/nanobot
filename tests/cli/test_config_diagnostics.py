import json

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app

runner = CliRunner()


def _write_ready_config(config_path, *, channels: dict | None = None) -> None:
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "model": "ollama/llama3.2",
                        "provider": "ollama",
                    }
                },
                "providers": {
                    "ollama": {
                        "apiBase": "http://localhost:11434/v1",
                    }
                },
                "channels": channels or {},
            }
        ),
        encoding="utf-8",
    )


def test_doctor_reports_ready_provider_and_next_step(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    _write_ready_config(config_path)

    result = runner.invoke(app, ["doctor", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Agent provider/model setup is ready" in result.stdout
    assert "Provider: ollama" in result.stdout
    assert "Model: ollama/llama3.2" in result.stdout
    assert 'nanobot agent -m "Hello!"' in result.stdout
    assert "No model request was sent" in result.stdout


def test_doctor_reports_missing_provider_with_shortest_setup_routes(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["doctor", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Agent is not ready" in result.stdout
    assert "No provider is configured for model" in result.stdout
    assert "Settings → Models" in result.stdout
    assert "nanobot onboard --wizard" in result.stdout
    assert "nanobot doctor --config" in result.stdout


def test_doctor_does_not_validate_channel_configuration(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    _write_ready_config(
        config_path,
        channels={"websocket": {"enabled": False, "path": "missing-slash"}},
    )

    result = runner.invoke(app, ["doctor", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Agent provider/model setup is ready" in result.stdout
    assert "channels.websocket" not in result.stdout


def test_doctor_reports_json_location_without_traceback(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken", encoding="utf-8")

    result = runner.invoke(app, ["doctor", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Invalid configuration" in result.stdout
    assert "JSON syntax error at line 1, column 2" in result.stdout
    assert "Traceback" not in result.stdout


def test_doctor_reports_field_without_exposing_secret(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    secret = "should-never-appear"
    config_path.write_text(
        json.dumps({"providers": {"openrouter": {"apiKey": [secret]}}}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["doctor", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "providers.openrouter.apiKey" in result.stdout
    assert secret not in result.stdout
    assert "input_value" not in result.stdout
    assert "errors.pydantic.dev" not in result.stdout


def test_doctor_reports_missing_env_var_at_field(tmp_path, monkeypatch) -> None:
    name = "NANOBOT_TEST_DOCTOR_MISSING"
    monkeypatch.delenv(name, raising=False)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"providers": {"openrouter": {"apiKey": f"${{{name}}}"}}}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["doctor", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "providers.openrouter.apiKey" in result.stdout
    assert name in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["webui", "--yes", "--no-open"],
        ["agent", "--message", "hello"],
    ],
)
def test_agent_entrypoints_point_invalid_config_to_doctor(tmp_path, args: list[str]) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken", encoding="utf-8")

    result = runner.invoke(app, [*args, "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Invalid configuration" in result.stdout
    assert "nanobot doctor --config" in result.stdout
    assert "Traceback" not in result.stdout


def test_agent_provider_setup_failure_points_to_shortest_routes(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"workspace": str(workspace)}}}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["agent", "--message", "hello", "--config", str(config_path)],
    )

    assert result.exit_code == 1
    assert "Agent cannot start: No provider is configured for model" in result.stdout
    assert "Settings → Models" in result.stdout
    assert "nanobot onboard --wizard" in result.stdout
    assert "nanobot doctor --config" in result.stdout
    assert "Traceback" not in result.stdout
    assert not workspace.exists()


def test_doctor_missing_file_points_to_setup(tmp_path) -> None:
    config_path = tmp_path / "missing.json"

    result = runner.invoke(app, ["doctor", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "configuration file not found" in result.stdout
    assert "nanobot webui" in result.stdout
    assert "nanobot onboard --wizard" in result.stdout
