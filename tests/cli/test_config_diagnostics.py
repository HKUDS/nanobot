import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.gateway import GatewayRuntime, GatewayStartOptions, GatewayStatus, RuntimeResult

runner = CliRunner()

_ANTHROPIC_BACKEND_CASES = (
    ("anthropic", "anthropic", "claude-sonnet-4-5", "ANTHROPIC_API_KEY", "Anthropic"),
    ("kimi_coding", "kimiCoding", "kimi-for-coding", "KIMI_CODING_API_KEY", "Kimi Coding"),
    (
        "minimax_anthropic",
        "minimaxAnthropic",
        "MiniMax-M2.7-highspeed",
        "MINIMAX_API_KEY",
        "MiniMax (Anthropic)",
    ),
)


def _without_rendered_line_breaks(output: str) -> str:
    return "".join(output.splitlines())


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


def test_status_reports_ready_provider_and_next_step(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    _write_ready_config(config_path)

    result = runner.invoke(app, ["status", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Agent: ✓ provider/model configuration is ready" in result.stdout
    assert "Ollama:" in result.stdout
    assert "Model: ollama/llama3.2" in result.stdout
    assert 'nanobot agent -m "Hello!"' in result.stdout
    assert "Status does not call the model" in result.stdout


def test_status_validates_bedrock_without_constructing_provider(
    tmp_path,
    monkeypatch,
) -> None:
    from nanobot.providers.bedrock_provider import BedrockProvider

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "model": "bedrock/amazon.nova-lite-v1:0",
                        "provider": "bedrock",
                    }
                },
                "providers": {"bedrock": {"region": "us-east-1"}},
            }
        ),
        encoding="utf-8",
    )

    def _unexpected_init(*_args, **_kwargs) -> None:
        pytest.fail("status must not construct a provider client")

    monkeypatch.setattr(BedrockProvider, "__init__", _unexpected_init)

    result = runner.invoke(app, ["status", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Agent: ✓ provider/model configuration is ready" in result.stdout
    assert "Status does not call the model or verify network access" in result.stdout


@pytest.mark.parametrize(
    ("provider", "provider_key", "model", "env_name", "label"),
    _ANTHROPIC_BACKEND_CASES,
)
def test_status_reports_missing_key_for_anthropic_backends(
    tmp_path,
    monkeypatch,
    provider: str,
    provider_key: str,
    model: str,
    env_name: str,
    label: str,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv(env_name, raising=False)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"model": model, "provider": provider}},
                "providers": {provider_key: {}},
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["status", "--config", str(config_path)])
    output = _without_rendered_line_breaks(result.stdout)

    assert result.exit_code == 0
    assert f"Agent: ✗ No API key configured for provider '{provider}'." in output
    assert f"{label}: not set" in output
    assert "provider/model configuration is ready" not in output
    assert 'Next: nanobot agent -m "Hello!"' not in output
    assert "Settings → Models" in output


@pytest.mark.parametrize(
    ("provider", "provider_key", "model", "env_name", "label"),
    _ANTHROPIC_BACKEND_CASES,
)
def test_status_accepts_resolved_key_for_anthropic_backends(
    tmp_path,
    monkeypatch,
    provider: str,
    provider_key: str,
    model: str,
    env_name: str,
    label: str,
) -> None:
    monkeypatch.setenv(env_name, "test-api-key")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"model": model, "provider": provider}},
                "providers": {provider_key: {"apiKey": f"${{{env_name}}}"}},
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["status", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Agent: ✓ provider/model configuration is ready" in result.stdout
    assert f"{label}: ✓" in result.stdout
    assert 'nanobot agent -m "Hello!"' in result.stdout


def test_status_reports_missing_provider_with_shortest_setup_routes(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["status", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Agent: ✗" in result.stdout
    assert "No provider is configured for model" in result.stdout
    assert "Settings → Models" in _without_rendered_line_breaks(result.stdout)
    assert "nanobot onboard --wizard" in result.stdout
    assert "nanobot status --config" in result.stdout


def test_status_readiness_does_not_validate_channel_configuration(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    _write_ready_config(
        config_path,
        channels={"websocket": {"enabled": False, "path": "missing-slash"}},
    )

    result = runner.invoke(app, ["status", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Agent: ✓ provider/model configuration is ready" in result.stdout
    assert "channels.websocket" not in result.stdout


def test_status_reports_json_location_without_traceback(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken", encoding="utf-8")

    result = runner.invoke(app, ["status", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Invalid configuration" in result.stdout
    assert "JSON syntax error at line 1, column 2" in result.stdout
    assert "Traceback" not in result.stdout


def test_status_reports_field_without_exposing_secret(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    secret = "should-never-appear"
    config_path.write_text(
        json.dumps({"providers": {"openrouter": {"apiKey": [secret]}}}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["status", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "providers.openrouter.apiKey" in result.stdout
    assert secret not in result.stdout
    assert "input_value" not in result.stdout
    assert "errors.pydantic.dev" not in result.stdout


def test_status_reports_missing_env_var_at_field(tmp_path, monkeypatch) -> None:
    name = "NANOBOT_TEST_STATUS_MISSING"
    monkeypatch.delenv(name, raising=False)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"providers": {"openrouter": {"apiKey": f"${{{name}}}"}}}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["status", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "providers.openrouter.apiKey" in result.stdout
    assert name in result.stdout
    assert "OpenRouter: not set" in result.stdout
    assert "OpenRouter: ✓" not in result.stdout


def test_webui_reports_malformed_environment_config_without_traceback(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "missing.json"
    invalid_value = "sensitive-not-json"
    monkeypatch.setenv("NANOBOT_PROVIDERS", invalid_value)

    result = runner.invoke(
        app,
        ["webui", "--config", str(config_path), "--yes", "--no-open"],
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "Environment-based configuration could not be parsed" in result.stdout
    assert "nanobot status --config" in result.stdout
    assert invalid_value not in result.stdout
    assert not config_path.exists()


@pytest.mark.parametrize(
    "args",
    [
        ["webui", "--yes", "--no-open"],
        ["agent", "--message", "hello"],
    ],
)
def test_agent_entrypoints_point_invalid_config_to_status(tmp_path, args: list[str]) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken", encoding="utf-8")

    result = runner.invoke(app, [*args, "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Invalid configuration" in result.stdout
    assert "nanobot status --config" in result.stdout
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
    output = _without_rendered_line_breaks(result.stdout)

    assert result.exit_code == 1
    assert "Agent cannot start: No provider is configured for model" in output
    assert "Settings → Models" in output
    assert "nanobot onboard --wizard" in output
    assert "nanobot status --config" in output
    assert "Traceback" not in output
    assert not workspace.exists()


@pytest.mark.parametrize(
    "args",
    [
        ["gateway"],
        ["gateway", "--background"],
        ["gateway", "restart"],
    ],
)
def test_gateway_provider_setup_failure_points_to_shortest_routes_when_webui_disabled(
    tmp_path,
    monkeypatch,
    args: list[str],
) -> None:
    config_path = tmp_path / "explicit-gateway-config.json"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"workspace": str(workspace)}},
                "channels": {"websocket": {"enabled": False}},
            }
        ),
        encoding="utf-8",
    )

    def unexpected_managed_start(*_args, **_kwargs) -> RuntimeResult:
        pytest.fail("provider validation must fail before a managed gateway start")

    monkeypatch.setattr(GatewayRuntime, "start_background", unexpected_managed_start)
    monkeypatch.setattr(GatewayRuntime, "restart", unexpected_managed_start)

    result = runner.invoke(app, [*args, "--config", str(config_path)])
    output = _without_rendered_line_breaks(result.stdout)

    assert result.exit_code == 1
    assert "Gateway cannot start: No provider is configured for model" in output
    assert "Settings → Models" in output
    assert "nanobot onboard --wizard" in output
    assert "nanobot status --config" in output
    assert config_path.name in output
    assert "Traceback" not in output
    assert not workspace.exists()


@pytest.mark.parametrize(
    ("args", "start_mode"),
    [
        (["gateway", "--background"], "background"),
        (["gateway", "restart"], "restart"),
    ],
)
@pytest.mark.parametrize("secret_field", ["tokenIssueSecret", "token"])
def test_gateway_missing_provider_managed_start_for_webui_setup(
    tmp_path,
    monkeypatch,
    args: list[str],
    start_mode: str,
    secret_field: str,
) -> None:
    config_path = tmp_path / "explicit-gateway-config.json"
    workspace = tmp_path / "workspace"
    webui_port = 18776
    bootstrap_secret = "must-not-appear-in-gateway-output"
    config_path.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"workspace": str(workspace)}},
                "channels": {
                    "websocket": {
                        "enabled": True,
                        "host": "127.0.0.1",
                        "port": webui_port,
                        secret_field: bootstrap_secret,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    started_options: list[tuple[str, GatewayStartOptions]] = []
    status = GatewayStatus(
        running=True,
        pid=12345,
        state_path=tmp_path / "gateway.json",
        log_path=tmp_path / "gateway.log",
        started_at="2026-07-28T00:00:00Z",
        port=18790,
        reason="running",
    )

    def fake_start_background(
        _runtime: GatewayRuntime,
        options: GatewayStartOptions,
    ) -> RuntimeResult:
        started_options.append(("background", options))
        return RuntimeResult(True, "gateway_started_background", status)

    def fake_restart(
        _runtime: GatewayRuntime,
        options: GatewayStartOptions,
        *,
        timeout_s: int,
    ) -> RuntimeResult:
        assert timeout_s == 20
        started_options.append(("restart", options))
        return RuntimeResult(True, "gateway_started_background", status)

    monkeypatch.setattr(GatewayRuntime, "start_background", fake_start_background)
    monkeypatch.setattr(GatewayRuntime, "restart", fake_restart)
    monkeypatch.setattr(
        "nanobot.cli.webui_support.ensure_webui_bundle",
        lambda **_kwargs: None,
    )

    result = runner.invoke(
        app,
        [*args, "--config", str(config_path)],
    )
    output = _without_rendered_line_breaks(result.stdout)

    assert result.exit_code == 0
    assert "Provider/model setup is incomplete: No provider is configured for model" in output
    assert "Gateway will start so you can configure a provider and model" in output
    assert "WebUI Settings" in output
    assert "Models." in output
    assert f"WebUI: http://127.0.0.1:{webui_port}" in output
    assert f"channels.websocket.{secret_field}" in output
    if secret_field == "token":
        assert "channels.websocket.tokenIssueSecret" not in output
    assert "bootstrapSecret" not in output
    assert bootstrap_secret not in output
    assert "Gateway cannot start" not in output
    assert started_options == [
        (
            start_mode,
            GatewayStartOptions(
                port=18790,
                config_path=str(config_path.resolve()),
            ),
        )
    ]
    assert not workspace.exists()


def test_gateway_invalid_webui_config_blocks_unconfigured_setup_mode(tmp_path) -> None:
    config_path = tmp_path / "invalid-webui-config.json"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"workspace": str(workspace)}},
                "channels": {
                    "websocket": {
                        "enabled": True,
                        "port": "not-a-port",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_path)])
    output = _without_rendered_line_breaks(result.stdout)

    assert result.exit_code == 1
    assert "Gateway configuration is invalid." in output
    assert "channels.websocket.port" in output
    assert "Provider/model setup is incomplete" not in output
    assert "Traceback" not in output
    assert not workspace.exists()


@pytest.mark.parametrize(
    ("args", "summary", "retry_command"),
    [
        (
            ["webui", "--yes", "--no-open"],
            "WebUI configuration is invalid.",
            "nanobot webui --config",
        ),
        (
            ["gateway"],
            "Gateway configuration is invalid.",
            "nanobot gateway --config",
        ),
    ],
)
def test_runtime_config_validation_is_redacted_and_actionable(
    tmp_path,
    args: list[str],
    summary: str,
    retry_command: str,
) -> None:
    config_path = tmp_path / "explicit-runtime-config.json"
    workspace = tmp_path / "workspace"
    invalid_value = "sensitive-not-a-port"
    _write_ready_config(
        config_path,
        channels={
            "websocket": {
                "enabled": True,
                "port": invalid_value,
            }
        },
    )
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["agents"]["defaults"]["workspace"] = str(workspace)
    config_path.write_text(json.dumps(data), encoding="utf-8")

    result = runner.invoke(app, [*args, "--config", str(config_path)])
    output = _without_rendered_line_breaks(result.stdout)

    assert result.exit_code == 1
    assert summary in output
    assert "channels.websocket.port" in output
    assert retry_command in output
    assert config_path.name in output
    assert invalid_value not in output
    assert "input_value" not in output
    assert "errors.pydantic.dev" not in output
    assert "Traceback" not in output
    assert not workspace.exists()


def test_status_missing_file_points_to_setup_without_changing_exit_contract(tmp_path) -> None:
    config_path = tmp_path / "missing.json"

    result = runner.invoke(app, ["status", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "configuration file not found" in result.stdout
    assert "nanobot webui" in result.stdout
    assert "nanobot onboard --wizard" in result.stdout


@pytest.mark.parametrize("source", ["file", "environment"])
def test_onboard_rejects_legacy_proxy_without_printing_credentials(tmp_path, source):
    config_path = tmp_path / "config.json"
    secret = "synthetic-proxy-password"
    proxy = f"http://user:{secret}@localhost:8080"
    env = {key: value for key, value in os.environ.items() if not key.startswith("NANOBOT_")}
    env["PYTHONPATH"] = str(Path(__file__).parents[2])
    env["PYTHONUTF8"] = "1"
    if source == "file":
        original = json.dumps({"providers": {"openai": {"proxy": proxy}}}).encode()
        config_path.write_bytes(original)
    else:
        original = None
        env["NANOBOT_PROVIDERS__OPENAI__PROXY"] = proxy

    result = subprocess.run(
        [sys.executable, "-m", "nanobot", "onboard", "--refresh", "--config", str(config_path)],
        env=env, text=True, capture_output=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Legacy proxy settings" in output and "0.4.0" in output
    assert secret not in output
    assert "Traceback" not in output and "input_value" not in output
    if original is not None:
        assert config_path.read_bytes() == original
    else:
        assert not config_path.exists()


def test_onboard_overwrite_rejects_legacy_proxy_environment_without_changing_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    original = b'{"agents": {"defaults": {"model": "existing"}}}'
    config_path.write_bytes(original)
    secret = "synthetic-proxy-password"
    monkeypatch.setenv("NANOBOT_PROVIDERS__OPENAI__PROXY", f"http://user:{secret}@localhost:8080")

    result = runner.invoke(app, ["onboard", "--config", str(config_path)], input="y\n")

    assert result.exit_code == 1
    assert "0.4.0" in result.stdout
    assert secret not in result.stdout
    assert config_path.read_bytes() == original



def test_plugins_list_reports_legacy_proxy_without_credentials(tmp_path):
    config_path = tmp_path / "config.json"
    secret = "synthetic-plugin-proxy-password"
    original = json.dumps({"tools": {"web": {"proxy": f"http://user:{secret}@localhost:8080"}}}).encode()
    config_path.write_bytes(original)
    env = {key: value for key, value in os.environ.items() if not key.startswith("NANOBOT_")}
    env["PYTHONPATH"] = str(Path(__file__).parents[2])
    env["PYTHONUTF8"] = "1"

    result = subprocess.run(
        [sys.executable, "-m", "nanobot", "plugins", "list", "--config", str(config_path)],
        env=env, text=True, capture_output=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Legacy proxy settings" in output and "0.4.0" in output
    assert secret not in output and "Traceback" not in output
    assert config_path.read_bytes() == original


def test_cli_unhandled_traceback_does_not_show_locals(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    secret = "synthetic-unhandled-local-secret"
    env = {key: value for key, value in os.environ.items() if not key.startswith("NANOBOT_")}
    env["PYTHONPATH"] = str(Path(__file__).parents[2])
    env["PYTHONUTF8"] = "1"
    env["TEST_CLI_LOCAL_SECRET"] = secret
    code = (
        "import os, sys\n"
        "from nanobot.cli import commands\n"
        "def fail(*args):\n"
        "    synthetic_local = os.environ['TEST_CLI_LOCAL_SECRET']\n"
        "    raise RuntimeError('synthetic failure')\n"
        "commands._print_enable_options = fail\n"
        "sys.argv = ['nanobot', 'plugins', 'list', '--config', sys.argv[1]]\n"
        "commands.app()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(config_path)],
        env=env, text=True, capture_output=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "synthetic failure" in output
    assert secret not in output



@pytest.mark.parametrize("action", ["enable", "disable"])
def test_plugins_changes_reject_legacy_proxy_before_mutation(tmp_path, monkeypatch, action):
    from nanobot import optional_features

    config_path = tmp_path / "config.json"
    secret = "synthetic-plugin-proxy-password"
    original = json.dumps({"channels": {"telegram": {
        "enabled": True, "proxy": f"http://user:{secret}@localhost:8080",
    }}}).encode()
    config_path.write_bytes(original)

    def no_install(*args, **kwargs):
        pytest.fail("legacy config must be rejected before installing dependencies")

    monkeypatch.setattr(optional_features, "_install_feature_dependencies", no_install)
    result = runner.invoke(app, ["plugins", action, "telegram", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Legacy proxy settings" in result.stdout and "0.4.0" in result.stdout
    assert secret not in result.stdout
    assert config_path.read_bytes() == original
