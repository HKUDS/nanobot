import asyncio
import json
import subprocess
import shutil
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.cli.commands import app
from nanobot.config.schema import Config, MCPServerConfig
from nanobot.providers.base import LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.openai_codex_provider import _strip_model_prefix
from nanobot.providers.registry import find_by_model

runner = CliRunner()


@pytest.fixture
def mock_paths():
    """Mock config/workspace paths for test isolation."""
    with patch("nanobot.config.loader.get_config_path") as mock_cp, \
         patch("nanobot.config.loader.save_config") as mock_sc, \
         patch("nanobot.config.loader.load_config") as mock_lc, \
         patch("nanobot.utils.helpers.get_workspace_path") as mock_ws:

        base_dir = Path("./test_onboard_data")
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir()

        config_file = base_dir / "config.json"
        workspace_dir = base_dir / "workspace"

        mock_cp.return_value = config_file
        mock_ws.return_value = workspace_dir
        mock_sc.side_effect = lambda config: config_file.write_text("{}")

        yield config_file, workspace_dir

        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_onboard_fresh_install(mock_paths):
    """No existing config — should create from scratch."""
    config_file, workspace_dir = mock_paths

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 0
    assert "Created config" in result.stdout
    assert "Created workspace" in result.stdout
    assert "nanobot is ready" in result.stdout
    assert config_file.exists()
    assert (workspace_dir / "AGENTS.md").exists()
    assert (workspace_dir / "memory" / "MEMORY.md").exists()


def test_onboard_existing_config_refresh(mock_paths):
    """Config exists, user declines overwrite — should refresh (load-merge-save)."""
    config_file, workspace_dir = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "existing values preserved" in result.stdout
    assert workspace_dir.exists()
    assert (workspace_dir / "AGENTS.md").exists()


def test_onboard_existing_config_overwrite(mock_paths):
    """Config exists, user confirms overwrite — should reset to defaults."""
    config_file, workspace_dir = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="y\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "Config reset to defaults" in result.stdout
    assert workspace_dir.exists()


def test_onboard_existing_workspace_safe_create(mock_paths):
    """Workspace exists — should not recreate, but still add missing templates."""
    config_file, workspace_dir = mock_paths
    workspace_dir.mkdir(parents=True)
    config_file.write_text("{}")

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Created workspace" not in result.stdout
    assert "Created AGENTS.md" in result.stdout
    assert (workspace_dir / "AGENTS.md").exists()


def test_config_matches_github_copilot_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "github-copilot/gpt-5.3-codex"

    assert config.get_provider_name() == "github_copilot"


def test_config_matches_openai_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "openai-codex/gpt-5.1-codex"

    assert config.get_provider_name() == "openai_codex"


def test_find_by_model_prefers_explicit_prefix_over_generic_codex_keyword():
    spec = find_by_model("github-copilot/gpt-5.3-codex")

    assert spec is not None
    assert spec.name == "github_copilot"


def test_litellm_provider_canonicalizes_github_copilot_hyphen_prefix():
    provider = LiteLLMProvider(default_model="github-copilot/gpt-5.3-codex")

    resolved = provider._resolve_model("github-copilot/gpt-5.3-codex")

    assert resolved == "github_copilot/gpt-5.3-codex"


def test_openai_codex_strip_prefix_supports_hyphen_and_underscore():
    assert _strip_model_prefix("openai-codex/gpt-5.1-codex") == "gpt-5.1-codex"
    assert _strip_model_prefix("openai_codex/gpt-5.1-codex") == "gpt-5.1-codex"


def test_mobile_setup_creates_layout_and_maestro_mcp(monkeypatch, tmp_path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path / "workspace")
    saved: list[Config] = []

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("nanobot.config.loader.save_config", lambda c: saved.append(c))

    result = runner.invoke(app, ["mobile", "setup"])

    assert result.exit_code == 0
    workspace = cfg.workspace_path
    assert (workspace / "mobile" / "flows" / "smoke.yaml").exists()
    assert (workspace / "mobile" / "apps").exists()
    assert (workspace / "reports" / "mobile" / "runs").exists()
    assert "maestro" in cfg.tools.mcp_servers
    assert cfg.tools.mcp_servers["maestro"].command == "maestro"
    assert cfg.tools.mcp_servers["maestro"].args == ["mcp"]
    assert cfg.tools.mcp_servers["maestro"].tool_timeout == 180
    assert saved, "save_config should be called when MCP config is created"


def test_mobile_setup_keeps_existing_mcp_without_force(monkeypatch, tmp_path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path / "workspace")
    cfg.tools.mcp_servers["maestro"] = MCPServerConfig(
        command="custom-maestro",
        args=["mcp"],
        tool_timeout=55,
    )
    saved: list[Config] = []

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("nanobot.config.loader.save_config", lambda c: saved.append(c))

    result = runner.invoke(app, ["mobile", "setup"])

    assert result.exit_code == 0
    assert "already exists" in result.stdout
    assert cfg.tools.mcp_servers["maestro"].command == "custom-maestro"
    assert cfg.tools.mcp_servers["maestro"].tool_timeout == 55
    assert not saved, "save_config should not be called when MCP config is unchanged"


def test_mobile_setup_overwrites_existing_mcp_with_force(monkeypatch, tmp_path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path / "workspace")
    cfg.tools.mcp_servers["maestro"] = MCPServerConfig(
        command="custom-maestro",
        args=["mcp"],
        tool_timeout=55,
    )
    saved: list[Config] = []

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("nanobot.config.loader.save_config", lambda c: saved.append(c))

    result = runner.invoke(
        app,
        ["mobile", "setup", "--force", "--maestro-command", "/opt/maestro/bin/maestro", "--tool-timeout", "240"],
    )

    assert result.exit_code == 0
    assert cfg.tools.mcp_servers["maestro"].command == "/opt/maestro/bin/maestro"
    assert cfg.tools.mcp_servers["maestro"].args == ["mcp"]
    assert cfg.tools.mcp_servers["maestro"].tool_timeout == 240
    assert saved, "save_config should be called when force-overwriting MCP config"


def test_mobile_run_writes_summary_and_logs(monkeypatch, tmp_path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path / "workspace")
    flows_dir = cfg.workspace_path / "mobile" / "flows"
    flows_dir.mkdir(parents=True, exist_ok=True)
    (flows_dir / "a-smoke.yaml").write_text("appId: com.example\n---\n- launchApp\n", encoding="utf-8")
    (flows_dir / "b-smoke.yaml").write_text("appId: com.example\n---\n- launchApp\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(cmd, cwd, capture_output, text):
        assert cwd == cfg.workspace_path
        assert capture_output is True
        assert text is True
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/maestro")
    monkeypatch.setattr("subprocess.run", fake_run)

    result = runner.invoke(app, ["mobile", "run", "--suite", "smoke", "--platform", "android"])

    assert result.exit_code == 0
    assert len(calls) == 2
    summary_path = cfg.workspace_path / "reports" / "mobile" / "summary-latest.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert summary["suite"] == "smoke"
    assert summary["platform"] == "android"
    assert summary["requestedFlows"] == 2
    assert summary["executedFlows"] == 2
    assert summary["passedFlows"] == 2
    assert summary["failedFlows"] == 0
    artifact_types = {item["type"] for item in summary["artifacts"]}
    assert "log" in artifact_types
    assert "maestro-output-dir" in artifact_types


def test_mobile_run_fail_fast_stops_after_first_failure(monkeypatch, tmp_path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path / "workspace")
    flows_dir = cfg.workspace_path / "mobile" / "flows"
    flows_dir.mkdir(parents=True, exist_ok=True)
    (flows_dir / "01-first.yaml").write_text("appId: com.example\n---\n- launchApp\n", encoding="utf-8")
    (flows_dir / "02-second.yaml").write_text("appId: com.example\n---\n- launchApp\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(cmd, cwd, capture_output, text):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="failed")

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/maestro")
    monkeypatch.setattr("subprocess.run", fake_run)

    result = runner.invoke(app, ["mobile", "run", "--fail-fast"])

    assert result.exit_code == 1
    assert len(calls) == 1
    summary_path = cfg.workspace_path / "reports" / "mobile" / "summary-latest.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["requestedFlows"] == 2
    assert summary["executedFlows"] == 1
    assert summary["passedFlows"] == 0
    assert summary["failedFlows"] == 1


def test_mobile_run_mode_mcp_uses_mcp_executor(monkeypatch, tmp_path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path / "workspace")
    cfg.tools.mcp_servers["maestro"] = MCPServerConfig(command="maestro", args=["mcp"])
    flows_dir = cfg.workspace_path / "mobile" / "flows"
    flows_dir.mkdir(parents=True, exist_ok=True)
    (flows_dir / "mcp-smoke.yaml").write_text("appId: com.example\n---\n- launchApp\n", encoding="utf-8")

    async def fake_mcp(config, server_name, flows, artifacts_dir, run_dir, suite, platform, continue_on_fail):
        assert server_name == "maestro"
        log = run_dir / "01-mcp-smoke.log"
        artifact = artifacts_dir / "01-mcp-smoke"
        artifact.mkdir(parents=True, exist_ok=True)
        log.write_text("mcp ok", encoding="utf-8")
        return (
            [
                {
                    "flow": str(flows[0]),
                    "status": "passed",
                    "exitCode": 0,
                    "logFile": str(log),
                    "artifactDir": str(artifact),
                }
            ],
            [log],
            [artifact],
            "mcp_maestro_run_flow_files",
        )

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("nanobot.cli.commands._mobile_run_with_mcp", fake_mcp)

    result = runner.invoke(app, ["mobile", "run", "--mode", "mcp"])

    assert result.exit_code == 0
    summary_path = cfg.workspace_path / "reports" / "mobile" / "summary-latest.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["executionMode"] == "mcp"
    assert summary["mcpServer"] == "maestro"
    assert summary["status"] == "passed"


def test_mobile_run_mode_auto_falls_back_to_local_when_mcp_fails(monkeypatch, tmp_path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path / "workspace")
    cfg.tools.mcp_servers["maestro"] = MCPServerConfig(command="maestro", args=["mcp"])
    flows_dir = cfg.workspace_path / "mobile" / "flows"
    flows_dir.mkdir(parents=True, exist_ok=True)
    (flows_dir / "fallback.yaml").write_text("appId: com.example\n---\n- launchApp\n", encoding="utf-8")

    async def fake_mcp(*_args, **_kwargs):
        raise RuntimeError("boom")

    calls: list[list[str]] = []

    def fake_local_run(cmd, cwd, capture_output, text):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("nanobot.cli.commands._mobile_run_with_mcp", fake_mcp)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/maestro")
    monkeypatch.setattr("subprocess.run", fake_local_run)

    result = runner.invoke(app, ["mobile", "run", "--mode", "auto"])

    assert result.exit_code == 0
    assert len(calls) == 1
    summary_path = cfg.workspace_path / "reports" / "mobile" / "summary-latest.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["executionMode"] == "local"
    assert summary["status"] == "passed"


def _make_agent_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model", memory_window=10)


def test_agent_mobile_shortcut_extracts_app_id(tmp_path) -> None:
    loop = _make_agent_loop(tmp_path)
    app_id = loop._extract_mobile_transfer_app_id("打开im.token.app，进入转账页面")
    assert app_id == "im.token.app"


def test_agent_mobile_shortcut_extracts_selected_token(tmp_path) -> None:
    loop = _make_agent_loop(tmp_path)
    assert loop._extract_selected_token_symbol("打开im.token.app，进入转账页面，选择ETH") == "ETH"
    assert loop._extract_selected_token_symbol("open im.token.app, go transfer page, select usdt") == "USDT"
    assert loop._extract_selected_token_symbol("打开im.token.app，进入转账页面") is None
    assert loop._extract_selected_token_symbol("打开im.token.app，选择Ethereum地址") is None


def test_agent_mobile_shortcut_extracts_address_network_and_input(tmp_path) -> None:
    loop = _make_agent_loop(tmp_path)
    assert loop._extract_address_network("打开im.token.app，选择Ethereum地址") == "Ethereum"
    assert loop._extract_address_network("select arbitrum address") == "arbitrum"
    assert loop._extract_input_payload("输入0x11111") == "0x11111"
    assert loop._extract_input_payload("input 0xabc123") == "0xabc123"


def test_agent_mobile_shortcut_builds_flow_from_instruction(tmp_path) -> None:
    loop = _make_agent_loop(tmp_path)
    flow_lines, target = loop._build_mobile_flow_from_instruction(
        "im.token.app",
        "打开im.token.app，进入转账页面，选择ETH",
    )
    script = "\n".join(flow_lines)
    assert 'id: "FunctionBar.转账"' in script
    assert 'id: "TokenSelectModal.TokenSymbol.ETH"' in script
    assert "tapOn" in script
    assert target == "进入转账页面，选择ETH"


def test_agent_mobile_shortcut_maps_screenshot_to_take_screenshot(tmp_path) -> None:
    loop = _make_agent_loop(tmp_path)
    flow_lines, target = loop._build_mobile_flow_from_instruction(
        "im.token.app",
        "打开im.token.app，进入转账页面，选择ETH，截图",
    )
    script = "\n".join(flow_lines)
    assert "- takeScreenshot: shot-01" in script
    assert target == "进入转账页面，选择ETH，截图"


def test_agent_mobile_shortcut_maps_address_and_input(tmp_path) -> None:
    loop = _make_agent_loop(tmp_path)
    flow_lines, target = loop._build_mobile_flow_from_instruction(
        "im.token.app",
        "打开im.token.app，进入转账页面，选择USDC，选择Ethereum地址，输入0x11111，截图",
    )
    script = "\n".join(flow_lines)
    assert 'id: "TokenSelectModal.TokenSymbol.USDC"' in script
    assert 'text: "Ethereum"' in script
    assert '- inputText: "0x11111"' in script
    assert "- takeScreenshot: shot-01" in script
    assert "选择USDC" in target
    assert "选择Ethereum地址" in target


def test_agent_mobile_failure_classification_is_step_specific() -> None:
    stdout = """Running on emulator-5554
 > Flow test
Launch app "im.token.app"... COMPLETED
Assert that id: FunctionBar.转账 is visible... COMPLETED
Assert that id: TokenSelectModal.TokenSymbol.ETHEREUM is visible... FAILED
"""
    reason = AgentLoop._classify_mobile_failure(stdout, "")
    assert reason.startswith("页面断言失败")
    assert "TokenSelectModal.TokenSymbol.ETHEREUM" in reason


def test_agent_mobile_shortcut_bypasses_provider(tmp_path) -> None:
    loop = _make_agent_loop(tmp_path)
    loop.provider.chat = AsyncMock(return_value=LLMResponse(content="should-not-be-called", tool_calls=[]))
    loop._run_mobile_transfer_shortcut = AsyncMock(return_value="mobile-ok")
    loop.bus.publish_outbound = AsyncMock()

    msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="打开im.token.app，进入转账页面")
    result = asyncio.run(loop._process_message(msg))

    assert result is None
    assert loop.bus.publish_outbound.await_count >= 1
    loop._run_mobile_transfer_shortcut.assert_awaited_once_with(
        "im.token.app",
        instruction="打开im.token.app，进入转账页面",
        expose_paths=False,
        timeout_s=ANY,
        on_progress=ANY,
    )
    loop.provider.chat.assert_not_called()


def test_agent_mobile_shortcut_cli_keeps_local_paths(tmp_path) -> None:
    loop = _make_agent_loop(tmp_path)
    loop.provider.chat = AsyncMock(return_value=LLMResponse(content="should-not-be-called", tool_calls=[]))
    loop._run_mobile_transfer_shortcut = AsyncMock(return_value="mobile-ok")

    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="打开im.token.app，进入转账页面")
    result = asyncio.run(loop._process_message(msg))

    assert result is not None
    assert result.content == "mobile-ok"
    loop._run_mobile_transfer_shortcut.assert_awaited_once_with(
        "im.token.app",
        instruction="打开im.token.app，进入转账页面",
        expose_paths=True,
        timeout_s=ANY,
        on_progress=ANY,
    )
    loop.provider.chat.assert_not_called()


def test_agent_mobile_shortcut_passes_selected_token(tmp_path) -> None:
    loop = _make_agent_loop(tmp_path)
    loop.provider.chat = AsyncMock(return_value=LLMResponse(content="should-not-be-called", tool_calls=[]))
    loop._run_mobile_transfer_shortcut = AsyncMock(return_value="mobile-ok")
    loop.bus.publish_outbound = AsyncMock()

    msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="打开im.token.app，进入转账页面，选择ETH")
    result = asyncio.run(loop._process_message(msg))

    assert result is None
    assert loop.bus.publish_outbound.await_count >= 1
    loop._run_mobile_transfer_shortcut.assert_awaited_once_with(
        "im.token.app",
        instruction="打开im.token.app，进入转账页面，选择ETH",
        expose_paths=False,
        timeout_s=ANY,
        on_progress=ANY,
    )
    loop.provider.chat.assert_not_called()


def test_agent_mobile_result_summary_success() -> None:
    content = (
        "已完成移动自动化测试。\n"
        "app: im.token.app\n"
        "target: 进入转账页面并选择 ETH\n"
        "runId: intent-20260301-010000-im-token-app\n"
        "执行证据已保存到本地服务器（已脱敏，不返回本地目录路径）。"
    )
    summary = AgentLoop._summarize_mobile_result(content)
    assert "成功" in summary
    assert "runId: intent-20260301-010000-im-token-app" in summary


def test_agent_mobile_result_summary_failure() -> None:
    content = (
        "移动自动化测试执行失败。\n"
        "app: im.token.app\n"
        "reason: 未检测到可用设备\n"
        "runId: intent-20260301-010101-im-token-app\n"
        "详情日志已保存到本地服务器（已脱敏，不返回本地目录路径）。"
    )
    summary = AgentLoop._summarize_mobile_result(content)
    assert "失败" in summary
    assert "未检测到可用设备" in summary
    assert "runId: intent-20260301-010101-im-token-app" in summary


def test_agent_non_mobile_message_still_calls_provider(tmp_path) -> None:
    loop = _make_agent_loop(tmp_path)
    loop.provider.chat = AsyncMock(return_value=LLMResponse(content="hello", tool_calls=[]))
    loop.tools.get_definitions = MagicMock(return_value=[])

    msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="你好")
    result = asyncio.run(loop._process_message(msg))

    assert result is not None
    assert "hello" in result.content
    loop.provider.chat.assert_awaited_once()
