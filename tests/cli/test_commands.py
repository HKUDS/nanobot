import asyncio
import json
import re
import shutil
import signal
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from nanobot.agent.memory import MemoryStore
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.cli import commands as cli_commands
from nanobot.cli.commands import app
from nanobot.config.schema import Config
from nanobot.cron.service import CronJobSkippedError
from nanobot.cron.session_turns import CRON_DEFER_UNTIL_IDLE_META, CRON_TRIGGER_META
from nanobot.cron.types import CronJob, CronPayload
from nanobot.cron.webui_metadata import cron_proactive_delivery_metadata
from nanobot.providers.factory import ProviderSnapshot, make_provider, provider_signature
from nanobot.providers.openai_codex_provider import _strip_model_prefix
from nanobot.providers.registry import find_by_name
from nanobot.webui.metadata import (
    WEBUI_MESSAGE_SOURCE_METADATA_KEY,
    WEBUI_TURN_METADATA_KEY,
)

runner = CliRunner()


def test_proactive_websocket_delivery_gets_fresh_turn_id() -> None:
    metadata = {
        "webui": True,
        WEBUI_TURN_METADATA_KEY: "turn-that-created-the-reminder",
        "workspace_scope": {"mode": "default"},
    }

    out = cron_proactive_delivery_metadata(
        "websocket",
        metadata,
        turn_seed="cron:drink-water",
        source_label="drink water",
    )

    assert out["webui"] is True
    assert out["workspace_scope"] == {"mode": "default"}
    assert out[WEBUI_TURN_METADATA_KEY].startswith("cron:drink-water:")
    assert out[WEBUI_TURN_METADATA_KEY] != metadata[WEBUI_TURN_METADATA_KEY]
    assert out[WEBUI_MESSAGE_SOURCE_METADATA_KEY] == {"kind": "cron", "label": "drink water"}


def _fake_provider():
    """Return a minimal fake provider that satisfies AgentLoop.__init__."""
    p = MagicMock()
    p.generation.max_tokens = 4096
    return p


class _StopGatewayError(RuntimeError):
    pass


def test_gateway_signal_handler_first_signal_stops_and_second_forces() -> None:
    class _FakeLoop:
        def __init__(self) -> None:
            self.handlers: dict[int, tuple[object, tuple[object, ...]]] = {}
            self.removed: list[int] = []

        def add_signal_handler(self, signum, callback, *args) -> None:
            self.handlers[int(signum)] = (callback, args)

        def remove_signal_handler(self, signum) -> bool:
            self.removed.append(int(signum))
            self.handlers.pop(int(signum), None)
            return True

    async def _run() -> None:
        loop = _FakeLoop()
        shutdown_event = asyncio.Event()
        never = asyncio.Event()
        task = asyncio.create_task(never.wait())
        output: list[str] = []

        restore = cli_commands._install_gateway_shutdown_handlers(
            loop, shutdown_event, [task], output.append,
        )
        try:
            callback, args = loop.handlers[int(signal.SIGINT)]
            assert callable(callback)

            callback(*args)
            assert shutdown_event.is_set()
            assert output == ["\nShutting down... Press Ctrl+C again to force."]
            assert not task.done()

            callback(*args)
            await asyncio.sleep(0)
            assert task.cancelled()
        finally:
            restore()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        assert int(signal.SIGINT) in loop.removed
        assert int(signal.SIGTERM) in loop.removed

    asyncio.run(_run())


def test_gateway_tty_signal_mode_restores_ctrl_c(monkeypatch) -> None:
    try:
        import os
        import pty
        import termios
    except ImportError:  # pragma: no cover - platform without POSIX termios
        pytest.skip("termios unavailable")

    master_fd, slave_fd = pty.openpty()

    class _Stdin:
        def fileno(self) -> int:
            return slave_fd

    try:
        attrs = termios.tcgetattr(slave_fd)
        attrs[3] &= ~(termios.ISIG | termios.ICANON | termios.ECHO)
        termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

        monkeypatch.setattr(cli_commands.sys, "stdin", _Stdin())
        cli_commands._ensure_gateway_tty_signal_mode()

        restored = termios.tcgetattr(slave_fd)
        assert restored[3] & termios.ISIG
        assert restored[3] & termios.ICANON
        assert restored[3] & termios.ECHO
    finally:
        os.close(master_fd)
        os.close(slave_fd)


def test_disabled_dream_cursor_only_advances_when_behind(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.append_history("first")
    store.append_history("second")

    cli_commands._advance_dream_cursor_if_behind(store)
    assert store.get_last_dream_cursor() == 2

    store.set_last_dream_cursor(10)
    cli_commands._advance_dream_cursor_if_behind(store)
    assert store.get_last_dream_cursor() == 10


@pytest.fixture
def mock_paths():
    """Mock config/workspace paths for test isolation."""
    with patch("nanobot.config.loader.get_config_path") as mock_cp, \
         patch("nanobot.config.loader.save_config") as mock_sc, \
         patch("nanobot.config.loader.load_config") as mock_lc, \
         patch("nanobot.cli.commands.get_workspace_path") as mock_ws:
        base_dir = Path("./test_onboard_data")
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir()

        config_file = base_dir / "config.json"
        workspace_dir = base_dir / "workspace"

        mock_cp.return_value = config_file
        mock_ws.return_value = workspace_dir
        mock_lc.side_effect = lambda _config_path=None: Config()

        def _save_config(config: Config, config_path: Path | None = None):
            target = config_path or config_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(config.model_dump(by_alias=True)), encoding="utf-8")

        mock_sc.side_effect = _save_config

        yield config_file, workspace_dir, mock_ws

        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_onboard_fresh_install(mock_paths):
    """No existing config — should create from scratch."""
    config_file, workspace_dir, mock_ws = mock_paths

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 0
    assert "Created config" in result.stdout
    assert "Created workspace" in result.stdout
    assert "nanobot is ready" in result.stdout
    assert config_file.exists()
    assert (workspace_dir / "AGENTS.md").exists()
    assert (workspace_dir / "memory" / "MEMORY.md").exists()
    expected_workspace = Config().workspace_path
    assert mock_ws.call_args.args == (expected_workspace,)


def test_onboard_existing_config_refresh(mock_paths):
    """Config exists, user declines overwrite — should refresh (load-merge-save)."""
    config_file, workspace_dir, _ = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "existing values preserved" in result.stdout
    assert workspace_dir.exists()
    assert (workspace_dir / "AGENTS.md").exists()


def test_onboard_existing_config_overwrite(mock_paths):
    """Config exists, user confirms overwrite — should reset to defaults."""
    config_file, workspace_dir, _ = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="y\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "Config reset to defaults" in result.stdout
    assert workspace_dir.exists()


def test_onboard_existing_workspace_safe_create(mock_paths):
    """Workspace exists — should not recreate, but still add missing templates."""
    config_file, workspace_dir, _ = mock_paths
    workspace_dir.mkdir(parents=True)
    config_file.write_text("{}")

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Created workspace" not in result.stdout
    assert "Created AGENTS.md" in result.stdout
    assert (workspace_dir / "AGENTS.md").exists()


def _strip_ansi(text):
    """Remove ANSI escape codes from text."""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)


def test_onboard_help_shows_workspace_and_config_options():
    result = runner.invoke(app, ["onboard", "--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "--workspace" in stripped_output
    assert "-w" in stripped_output
    assert "--config" in stripped_output
    assert "-c" in stripped_output
    assert "--wizard" in stripped_output
    assert "--dir" not in stripped_output


def test_status_help_shows_workspace_and_config_options():
    result = runner.invoke(app, ["status", "--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "--workspace" in stripped_output
    assert "-w" in stripped_output
    assert "--config" in stripped_output
    assert "-c" in stripped_output


def test_status_uses_explicit_config_and_workspace(tmp_path: Path):
    config_path = tmp_path / "instance" / "config.json"
    config_workspace = tmp_path / "config-workspace"
    override_workspace = tmp_path / "override-workspace"
    config = Config()
    config.agents.defaults.workspace = str(config_workspace)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(config.model_dump(mode="json", by_alias=True)))

    result = runner.invoke(
        app,
        ["status", "--config", str(config_path), "--workspace", str(override_workspace)],
    )

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    compact_output = stripped_output.replace("\n", "")
    assert str(config_path.resolve(strict=False)) in compact_output
    assert str(override_workspace) in compact_output
    assert str(config_workspace) not in compact_output


def test_onboard_interactive_discard_does_not_save_or_create_workspace(mock_paths, monkeypatch):
    config_file, workspace_dir, _ = mock_paths

    from nanobot.cli.onboard import OnboardResult

    monkeypatch.setattr(
        "nanobot.cli.onboard.run_onboard",
        lambda initial_config: OnboardResult(config=initial_config, should_save=False),
    )

    result = runner.invoke(app, ["onboard", "--wizard"])

    assert result.exit_code == 0
    assert "No changes were saved" in result.stdout
    assert not config_file.exists()
    assert not workspace_dir.exists()


def test_onboard_uses_explicit_config_and_workspace_paths(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    monkeypatch.setattr("nanobot.channels.registry.discover_all", lambda: {})

    result = runner.invoke(
        app,
        ["onboard", "--config", str(config_path), "--workspace", str(workspace_path)],
    )

    assert result.exit_code == 0
    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
    assert saved.workspace_path == workspace_path
    assert (workspace_path / "AGENTS.md").exists()
    stripped_output = _strip_ansi(result.stdout)
    compact_output = stripped_output.replace("\n", "")
    resolved_config = str(config_path.resolve())
    assert resolved_config in compact_output
    assert f"--config {resolved_config}" in compact_output


def test_onboard_wizard_preserves_explicit_config_in_next_steps(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    from nanobot.cli.onboard import OnboardResult

    monkeypatch.setattr(
        "nanobot.cli.onboard.run_onboard",
        lambda initial_config: OnboardResult(config=initial_config, should_save=True),
    )
    monkeypatch.setattr("nanobot.channels.registry.discover_all", lambda: {})

    result = runner.invoke(
        app,
        ["onboard", "--wizard", "--config", str(config_path), "--workspace", str(workspace_path)],
    )

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    compact_output = stripped_output.replace("\n", "")
    resolved_config = str(config_path.resolve())
    assert f'nanobot agent -m "Hello!" --config {resolved_config}' in compact_output
    assert f"nanobot gateway --config {resolved_config}" in compact_output


def test_config_matches_github_copilot_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "github-copilot/gpt-5.3-codex"

    assert config.get_provider_name() == "github_copilot"


def test_config_matches_openai_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "openai-codex/gpt-5.1-codex"

    assert config.get_provider_name() == "openai_codex"


def test_config_dump_excludes_oauth_provider_blocks():
    config = Config()

    providers = config.model_dump(by_alias=True)["providers"]

    assert "openaiCodex" not in providers
    assert "githubCopilot" not in providers


def test_plugins_list_uses_explicit_config(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"channels": {"example": {"enabled": True}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_channel_names",
        lambda: ["example"],
    )
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_plugins",
        lambda: {},
    )
    monkeypatch.setattr(
        "nanobot.optional_features.optional_dependency_groups",
        lambda: {},
    )

    result = runner.invoke(app, ["plugins", "list", "--config", str(config_path)])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "example" in stripped_output
    assert "yes" in stripped_output


def test_provider_logout_openai_codex_removes_local_oauth_files(tmp_path, monkeypatch):
    token_path = tmp_path / "auth" / "codex.json"
    lock_path = token_path.with_suffix(".lock")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("{}", encoding="utf-8")
    lock_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("OAUTH_CLI_KIT_TOKEN_PATH", str(token_path))

    result = runner.invoke(app, ["provider", "logout", "openai-codex"])

    assert result.exit_code == 0
    assert not token_path.exists()
    assert not lock_path.exists()
    assert "Logged out from OpenAI Codex" in result.stdout


def test_provider_logout_openai_codex_succeeds_when_no_local_oauth_file(monkeypatch, tmp_path):
    token_path = tmp_path / "auth" / "codex.json"
    monkeypatch.setenv("OAUTH_CLI_KIT_TOKEN_PATH", str(token_path))

    result = runner.invoke(app, ["provider", "logout", "openai-codex"])

    assert result.exit_code == 0
    assert "No local OAuth credentials found for OpenAI Codex" in result.stdout


def test_provider_logout_github_copilot_removes_local_oauth_files(tmp_path, monkeypatch):
    token_path = tmp_path / "auth" / "github-copilot.json"
    lock_path = token_path.with_suffix(".lock")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("{}", encoding="utf-8")
    lock_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("OAUTH_CLI_KIT_TOKEN_PATH", str(token_path))

    result = runner.invoke(app, ["provider", "logout", "github-copilot"])

    assert result.exit_code == 0
    assert not token_path.exists()
    assert not lock_path.exists()
    assert "Logged out from GitHub Copilot" in result.stdout


def test_provider_logout_github_copilot_succeeds_when_no_local_oauth_file(monkeypatch, tmp_path):
    token_path = tmp_path / "auth" / "github-copilot.json"
    monkeypatch.setenv("OAUTH_CLI_KIT_TOKEN_PATH", str(token_path))

    result = runner.invoke(app, ["provider", "logout", "github-copilot"])

    assert result.exit_code == 0
    assert "No local OAuth credentials found for GitHub Copilot" in result.stdout


def test_provider_logout_rejects_unknown_provider():
    result = runner.invoke(app, ["provider", "logout", "not-a-real-provider"])

    assert result.exit_code == 1
    assert "Unknown OAuth provider" in result.stdout


def test_provider_logout_paths_resolve_to_expected_files():
    from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
    from oauth_cli_kit.storage import FileTokenStorage

    from nanobot.providers.github_copilot_provider import get_storage

    codex_storage = FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename)
    codex_path = codex_storage.get_token_path()
    assert codex_path.name == "codex.json"
    assert codex_path.parent.name == "auth"

    gh_storage = get_storage()
    gh_path = gh_storage.get_token_path()
    assert gh_path.name == "github-copilot.json"
    assert gh_path.parent.name == "auth"


def test_provider_login_rejects_unknown_provider():
    result = runner.invoke(app, ["provider", "login", "not-a-real-provider"])

    assert result.exit_code == 1
    assert "Unknown OAuth provider" in result.stdout


def test_provider_login_can_set_openai_codex_as_main_provider(tmp_path):
    config_path = tmp_path / "config.json"
    called = False
    original = cli_commands._LOGIN_HANDLERS["openai_codex"]

    def fake_login() -> None:
        nonlocal called
        called = True

    cli_commands._LOGIN_HANDLERS["openai_codex"] = fake_login
    try:
        result = runner.invoke(
            app,
            [
                "provider",
                "login",
                "openai-codex",
                "--set-main",
                "--config",
                str(config_path),
            ],
        )
    finally:
        cli_commands._LOGIN_HANDLERS["openai_codex"] = original

    assert result.exit_code == 0
    assert called is True
    assert "Set openai-codex as the main provider" in result.stdout

    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
    assert saved.agents.defaults.provider == "openai_codex"
    assert saved.agents.defaults.model == "openai-codex/gpt-5.4-mini"
    assert saved.agents.defaults.model_preset is None
    assert make_provider(saved).__class__.__name__ == "OpenAICodexProvider"


def test_provider_login_can_set_github_copilot_as_main_provider(tmp_path):
    config_path = tmp_path / "config.json"
    original = cli_commands._LOGIN_HANDLERS["github_copilot"]
    cli_commands._LOGIN_HANDLERS["github_copilot"] = lambda: None
    try:
        result = runner.invoke(
            app,
            [
                "provider",
                "login",
                "github-copilot",
                "--set-main",
                "--config",
                str(config_path),
            ],
        )
    finally:
        cli_commands._LOGIN_HANDLERS["github_copilot"] = original

    assert result.exit_code == 0
    assert "Set github-copilot as the main provider" in result.stdout

    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
    assert saved.agents.defaults.provider == "github_copilot"
    assert saved.agents.defaults.model == "github-copilot/gpt-5.4-mini"
    assert saved.agents.defaults.model_preset is None
    assert make_provider(saved).__class__.__name__ == "GitHubCopilotProvider"


def test_provider_login_model_implies_set_main_provider(tmp_path):
    config_path = tmp_path / "config.json"
    original = cli_commands._LOGIN_HANDLERS["github_copilot"]
    cli_commands._LOGIN_HANDLERS["github_copilot"] = lambda: None
    try:
        result = runner.invoke(
            app,
            [
                "provider",
                "login",
                "github-copilot",
                "--model",
                "github-copilot/gpt-5.4-mini",
                "--config",
                str(config_path),
            ],
        )
    finally:
        cli_commands._LOGIN_HANDLERS["github_copilot"] = original

    assert result.exit_code == 0
    assert "Set github-copilot as the main provider" in result.stdout

    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
    assert saved.agents.defaults.provider == "github_copilot"
    assert saved.agents.defaults.model == "github-copilot/gpt-5.4-mini"
    assert make_provider(saved).__class__.__name__ == "GitHubCopilotProvider"


def test_provider_login_openai_codex_passes_configured_proxy(monkeypatch):
    proxy = "http://127.0.0.1:23458"
    monkeypatch.setattr(
        "nanobot.config.loader.load_config",
        lambda: Config.model_validate({"providers": {"openaiCodex": {"proxy": proxy}}}),
    )

    import oauth_cli_kit

    def fake_get_token(**_kwargs):
        raise RuntimeError("no-token")

    monkeypatch.setattr(oauth_cli_kit, "get_token", fake_get_token)

    captured: dict[str, str | None] = {}

    def fake_login(*, print_fn, prompt_fn, proxy=None):
        captured["proxy"] = proxy
        return SimpleNamespace(access="access-token", account_id="acct-test")

    monkeypatch.setattr(oauth_cli_kit, "login_oauth_interactive", fake_login)

    result = runner.invoke(app, ["provider", "login", "openai-codex"])

    assert result.exit_code == 0
    assert captured["proxy"] == proxy


def test_provider_login_openai_codex_resolves_proxy_env_ref(monkeypatch):
    proxy = "http://127.0.0.1:23458"
    monkeypatch.setenv("CODEX_PROXY_FOR_TEST", proxy)
    monkeypatch.setattr(
        "nanobot.config.loader.load_config",
        lambda: Config.model_validate(
            {"providers": {"openaiCodex": {"proxy": "${CODEX_PROXY_FOR_TEST}"}}}
        ),
    )

    import oauth_cli_kit

    captured: dict[str, str | None] = {}

    def fake_get_token(*, proxy=None):
        captured["proxy"] = proxy
        return SimpleNamespace(access="access-token", account_id="acct-test")

    monkeypatch.setattr(oauth_cli_kit, "get_token", fake_get_token)

    result = runner.invoke(app, ["provider", "login", "openai-codex"])

    assert result.exit_code == 0
    assert captured["proxy"] == proxy


def test_config_matches_explicit_ollama_prefix_without_api_key():
    config = Config()
    config.agents.defaults.model = "ollama/llama3.2"

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434/v1"


def test_config_explicit_ollama_provider_uses_default_localhost_api_base():
    config = Config()
    config.agents.defaults.provider = "ollama"
    config.agents.defaults.model = "llama3.2"

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434/v1"


def test_config_accepts_camel_case_explicit_provider_name_for_coding_plan():
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "volcengineCodingPlan",
                    "model": "doubao-1-5-pro",
                }
            },
            "providers": {
                "volcengineCodingPlan": {
                    "apiKey": "test-key",
                }
            },
        }
    )

    assert config.get_provider_name() == "volcengine_coding_plan"
    assert config.get_api_base() == "https://ark.cn-beijing.volces.com/api/coding/v3"


def test_config_accepts_lm_studio_without_api_key_and_uses_default_localhost_api_base():
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "lm_studio",
                    "model": "local-model",
                }
            },
            "providers": {
                "lmStudio": {
                    "apiKey": None,
                }
            },
        }
    )

    assert config.get_provider_name() == "lm_studio"
    assert config.get_api_key() is None
    assert config.get_api_base() == "http://localhost:1234/v1"


def test_config_accepts_atomic_chat_without_api_key_and_uses_default_localhost_api_base():
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "atomic_chat",
                    "model": "local-model",
                }
            },
            "providers": {
                "atomicChat": {
                    "apiKey": None,
                }
            },
        }
    )

    assert config.get_provider_name() == "atomic_chat"
    assert config.get_api_key() is None
    assert config.get_api_base() == "http://localhost:1337/v1"


def test_find_by_name_accepts_camel_case_and_hyphen_aliases():
    assert find_by_name("volcengineCodingPlan") is not None
    assert find_by_name("volcengineCodingPlan").name == "volcengine_coding_plan"
    assert find_by_name("github-copilot") is not None
    assert find_by_name("github-copilot").name == "github_copilot"
    assert find_by_name("longcat") is not None
    assert find_by_name("longcat").name == "longcat"
    assert find_by_name("atomic-chat") is not None
    assert find_by_name("atomic-chat").name == "atomic_chat"


def test_config_explicit_longcat_provider_resolves_provider_name():
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "longcat",
                    "model": "LongCat-Flash-Chat",
                }
            },
            "providers": {
                "longcat": {
                    "apiKey": "test-key",
                }
            },
        }
    )

    assert config.get_provider_name() == "longcat"
    assert config.get_api_base() == "https://api.longcat.chat/openai/v1"


def test_config_auto_detects_longcat_from_model_keyword():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "longcat/LongCat-Flash-Chat"}},
            "providers": {"longcat": {"apiKey": "test-key"}},
        }
    )

    assert config.get_provider_name() == "longcat"


def test_config_explicit_xiaomi_mimo_provider_uses_default_api_base():
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "xiaomi_mimo",
                    "model": "MiniMax-M1-80k",
                }
            },
            "providers": {
                "xiaomiMimo": {
                    "apiKey": "test-key",
                }
            },
        }
    )

    assert config.get_provider_name() == "xiaomi_mimo"
    assert config.get_api_base() == "https://api.xiaomimimo.com/v1"


def test_config_auto_detects_xiaomi_mimo_from_model_keyword():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "mimo/MiniMax-M1-80k"}},
            "providers": {"xiaomiMimo": {"apiKey": "test-key"}},
        }
    )

    assert config.get_provider_name() == "xiaomi_mimo"
    assert config.get_api_base() == "https://api.xiaomimimo.com/v1"


def test_config_explicit_minimax_anthropic_provider_uses_default_api_base():
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "minimax_anthropic",
                    "model": "MiniMax-M2.7-highspeed",
                }
            },
            "providers": {
                "minimaxAnthropic": {
                    "apiKey": "test-key",
                }
            },
        }
    )

    assert config.get_provider_name() == "minimax_anthropic"
    assert config.get_api_key() == "test-key"
    assert config.get_api_base() == "https://api.minimax.io/anthropic"


def test_config_auto_detects_ollama_from_local_api_base():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "llama3.2"}},
            "providers": {"ollama": {"apiBase": "http://localhost:11434/v1"}},
        }
    )

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434/v1"


def test_config_prefers_ollama_over_vllm_when_both_local_providers_configured():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "llama3.2"}},
            "providers": {
                "vllm": {"apiBase": "http://localhost:8000"},
                "ollama": {"apiBase": "http://localhost:11434/v1"},
            },
        }
    )

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434/v1"


def test_config_falls_back_to_vllm_when_ollama_not_configured():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "llama3.2"}},
            "providers": {
                "vllm": {"apiBase": "http://localhost:8000"},
            },
        }
    )

    assert config.get_provider_name() == "vllm"
    assert config.get_api_base() == "http://localhost:8000"


def test_openai_compat_provider_passes_model_through():
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(default_model="github-copilot/gpt-5.3-codex")

    assert provider.get_default_model() == "github-copilot/gpt-5.3-codex"


def test_make_provider_uses_github_copilot_backend():
    from nanobot.config.schema import Config
    from nanobot.providers.factory import make_provider

    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "github-copilot",
                    "model": "github-copilot/gpt-4.1",
                }
            }
        }
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = make_provider(config)

    assert provider.__class__.__name__ == "GitHubCopilotProvider"


def test_openai_codex_proxy_config_affects_provider_and_signature():
    def config_with_proxy(proxy: str) -> Config:
        return Config.model_validate(
            {
                "agents": {
                    "defaults": {
                        "provider": "openai-codex",
                        "model": "openai-codex/gpt-5.5",
                    }
                },
                "providers": {"openaiCodex": {"proxy": proxy}},
            }
        )

    proxy = "http://127.0.0.1:23458"
    config = config_with_proxy(proxy)

    provider = make_provider(config)

    assert provider.__class__.__name__ == "OpenAICodexProvider"
    assert provider.proxy == proxy
    assert provider_signature(config) != provider_signature(
        config_with_proxy("http://127.0.0.1:23459")
    )


def test_provider_proxy_rejects_unsupported_backend():
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "anthropic",
                    "model": "anthropic/claude-opus-4-5",
                }
            },
            "providers": {
                "anthropic": {
                    "apiKey": "sk-test",
                    "proxy": "http://127.0.0.1:23458",
                }
            },
        }
    )

    with pytest.raises(ValueError, match=r"providers\.anthropic\.proxy"):
        make_provider(config)


def test_github_copilot_provider_strips_prefixed_model_name():
    from nanobot.providers.github_copilot_provider import GitHubCopilotProvider

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = GitHubCopilotProvider(default_model="github-copilot/gpt-5.1")

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="github-copilot/gpt-5.1",
        max_tokens=16,
        temperature=0.1,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "gpt-5.1"


@pytest.mark.asyncio
async def test_github_copilot_provider_refreshes_client_api_key_before_chat():
    from nanobot.providers.github_copilot_provider import GitHubCopilotProvider

    mock_client = MagicMock()
    mock_client.api_key = "no-key"
    mock_client.chat.completions.create = AsyncMock(return_value={
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI", return_value=mock_client):
        provider = GitHubCopilotProvider(default_model="github-copilot/gpt-4")
        await provider._ensure_client()

    provider._get_copilot_access_token = AsyncMock(return_value="copilot-access-token")

    response = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="github-copilot/gpt-4",
        max_tokens=16,
        temperature=0.1,
    )

    assert response.content == "ok"
    assert provider._client.api_key == "copilot-access-token"
    provider._get_copilot_access_token.assert_awaited_once()
    mock_client.chat.completions.create.assert_awaited_once()


def test_openai_codex_strip_prefix_supports_hyphen_and_underscore():
    assert _strip_model_prefix("openai-codex/gpt-5.1-codex") == "gpt-5.1-codex"
    assert _strip_model_prefix("openai_codex/gpt-5.1-codex") == "gpt-5.1-codex"


def test_make_provider_passes_extra_headers_to_custom_provider():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "custom", "model": "gpt-4o-mini"}},
            "providers": {
                "custom": {
                    "apiKey": "test-key",
                    "apiBase": "https://example.com/v1",
                    "extraHeaders": {
                        "APP-Code": "demo-app",
                        "x-session-affinity": "sticky-session",
                    },
                }
            }
        }
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        provider = make_provider(config)
        asyncio.run(provider._ensure_client())

    kwargs = mock_async_openai.call_args.kwargs
    assert kwargs["api_key"] == "test-key"
    assert kwargs["base_url"] == "https://example.com/v1"
    assert kwargs["default_headers"]["APP-Code"] == "demo-app"
    assert kwargs["default_headers"]["x-session-affinity"] == "sticky-session"


def test_make_provider_treats_dynamic_custom_provider_as_direct():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "my-company-api", "model": "gpt-4o-mini"}},
            "providers": {
                "my-company-api": {
                    "apiBase": "https://example.com/v1",
                }
            },
        }
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        provider = make_provider(config)
        asyncio.run(provider._ensure_client())

    assert provider.get_default_model() == "gpt-4o-mini"
    assert provider._spec.name == "my_company_api"
    assert provider._spec.is_direct is True
    kwargs = mock_async_openai.call_args.kwargs
    assert kwargs["api_key"] == "no-key"
    assert kwargs["base_url"] == "https://example.com/v1"


def test_make_provider_strips_dynamic_custom_route_prefix_from_request_model():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "my-company-api/gpt-4o-mini"}},
            "providers": {
                "my-company-api": {
                    "apiBase": "https://example.com/v1",
                }
            },
        }
    )

    provider = make_provider(config)

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model=None,
        max_tokens=16,
        temperature=0.1,
        reasoning_effort=None,
        tool_choice=None,
    )
    body = provider._build_responses_body(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model=None,
        max_tokens=16,
        temperature=0.1,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert config.get_provider_name() == "my-company-api"
    assert kwargs["model"] == "gpt-4o-mini"
    assert body["model"] == "gpt-4o-mini"


def test_make_provider_preserves_namespaced_model_for_forced_dynamic_provider():
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "my-company-api",
                    "model": "openai/gpt-4o-mini",
                }
            },
            "providers": {
                "my-company-api": {
                    "apiBase": "https://example.com/v1",
                }
            },
        }
    )

    provider = make_provider(config)
    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model=None,
        max_tokens=16,
        temperature=0.1,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "openai/gpt-4o-mini"


def test_make_provider_strips_dynamic_custom_route_prefix_once():
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "auto",
                    "model": "my-company-api/openai/gpt-4o-mini",
                }
            },
            "providers": {
                "my-company-api": {
                    "apiBase": "https://example.com/v1",
                }
            },
        }
    )

    provider = make_provider(config)
    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model=None,
        max_tokens=16,
        temperature=0.1,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "openai/gpt-4o-mini"


def test_make_provider_rejects_dynamic_custom_provider_without_api_base():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "my-company-api", "model": "gpt-4o-mini"}},
            "providers": {
                "my-company-api": {
                    "apiKey": "sk-test",
                }
            },
        }
    )

    with pytest.raises(ValueError, match="Provider 'my-company-api' requires api_base"):
        make_provider(config)


def test_make_provider_rejects_auto_dynamic_custom_prefix_without_api_base():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "companyProxy/gpt-4o"}},
            "providers": {
                "otherProxy": {
                    "apiBase": "https://other.example.test/v1",
                },
                "companyProxy": {
                    "apiKey": "sk-company",
                },
            },
        }
    )

    with pytest.raises(ValueError, match="Provider 'companyProxy' requires api_base"):
        make_provider(config)


@pytest.fixture
def mock_agent_runtime(tmp_path):
    """Mock agent command dependencies for focused CLI tests."""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "default-workspace")

    with patch("nanobot.config.loader.load_config", return_value=config) as mock_load_config, \
         patch("nanobot.config.loader.resolve_config_env_vars", side_effect=lambda c: c), \
         patch("nanobot.cli.commands.sync_workspace_templates") as mock_sync_templates, \
         patch("nanobot.providers.factory.make_provider", return_value=_fake_provider()), \
         patch("nanobot.cli.commands._print_agent_response") as mock_print_response, \
         patch("nanobot.bus.queue.MessageBus"), \
         patch("nanobot.cron.service.CronService"), \
         patch("nanobot.cli.commands.AgentLoop.from_config") as mock_from_config:
        agent_loop = MagicMock()
        agent_loop.channels_config = None
        agent_loop.process_direct = AsyncMock(
            return_value=OutboundMessage(channel="cli", chat_id="direct", content="mock-response"),
        )
        agent_loop.close_mcp = AsyncMock(return_value=None)
        mock_from_config.return_value = agent_loop

        yield {
            "config": config,
            "load_config": mock_load_config,
            "sync_templates": mock_sync_templates,
            "from_config": mock_from_config,
            "agent_loop": agent_loop,
            "print_response": mock_print_response,
        }


def test_agent_help_shows_workspace_and_config_options():
    result = runner.invoke(app, ["agent", "--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "--workspace" in stripped_output
    assert "-w" in stripped_output
    assert "--config" in stripped_output
    assert "-c" in stripped_output


def test_agent_uses_default_config_when_no_workspace_or_config_flags(mock_agent_runtime):
    result = runner.invoke(app, ["agent", "-m", "hello"])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (None,)
    assert mock_agent_runtime["sync_templates"].call_args.args == (
        mock_agent_runtime["config"].workspace_path,
    )
    passed_config = mock_agent_runtime["from_config"].call_args.args[0]
    assert passed_config.workspace_path == mock_agent_runtime["config"].workspace_path
    mock_agent_runtime["agent_loop"].process_direct.assert_awaited_once()
    mock_agent_runtime["print_response"].assert_called_once_with(
        "mock-response", render_markdown=True, metadata={},
    )


def test_agent_uses_explicit_config_path(mock_agent_runtime, tmp_path: Path):
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}")

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (config_path.resolve(),)


def test_agent_config_sets_active_path(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    seen: dict[str, Path] = {}

    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.providers.factory.make_provider", lambda _config: _fake_provider())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())
    monkeypatch.setattr("nanobot.cron.service.CronService", lambda _store: object())

    class _FakeAgentLoop:
        @classmethod
        def from_config(cls, config, bus=None, **extra):
            return cls(**extra)
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def process_direct(self, *_args, **_kwargs):
            return OutboundMessage(channel="cli", chat_id="direct", content="ok")

        async def close_mcp(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cli.commands.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.cli.commands._print_agent_response", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert seen["config_path"] == config_file.resolve()


def test_agent_uses_workspace_directory_for_cron_store(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "agent-workspace")
    seen: dict[str, Path] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.providers.factory.make_provider", lambda _config: _fake_provider())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())

    class _FakeCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path

    class _FakeAgentLoop:
        @classmethod
        def from_config(cls, config, bus=None, **extra):
            return cls(**extra)
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def process_direct(self, *_args, **_kwargs):
            return OutboundMessage(channel="cli", chat_id="direct", content="ok")

        async def close_mcp(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.cli.commands.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.cli.commands._print_agent_response", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert seen["cron_store"] == config.workspace_path / "cron" / "jobs.json"


def test_agent_workspace_override_does_not_migrate_legacy_cron(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "jobs.json"
    legacy_file.write_text('{"jobs": []}')

    override = tmp_path / "override-workspace"
    config = Config()
    seen: dict[str, Path] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.providers.factory.make_provider", lambda _config: _fake_provider())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: legacy_dir)

    class _FakeCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path

    class _FakeAgentLoop:
        @classmethod
        def from_config(cls, config, bus=None, **extra):
            return cls(**extra)
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def process_direct(self, *_args, **_kwargs):
            return OutboundMessage(channel="cli", chat_id="direct", content="ok")

        async def close_mcp(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.cli.commands.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.cli.commands._print_agent_response", lambda *_args, **_kwargs: None)

    result = runner.invoke(
        app,
        ["agent", "-m", "hello", "-c", str(config_file), "-w", str(override)],
    )

    assert result.exit_code == 0
    assert seen["cron_store"] == override / "cron" / "jobs.json"
    assert legacy_file.exists()
    assert not (override / "cron" / "jobs.json").exists()


def test_agent_custom_config_workspace_does_not_migrate_legacy_cron(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "jobs.json"
    legacy_file.write_text('{"jobs": []}')

    custom_workspace = tmp_path / "custom-workspace"
    config = Config()
    config.agents.defaults.workspace = str(custom_workspace)
    seen: dict[str, Path] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.providers.factory.make_provider", lambda _config: _fake_provider())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: legacy_dir)

    class _FakeCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path

    class _FakeAgentLoop:
        @classmethod
        def from_config(cls, config, bus=None, **extra):
            return cls(**extra)
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def process_direct(self, *_args, **_kwargs):
            return OutboundMessage(channel="cli", chat_id="direct", content="ok")

        async def close_mcp(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.cli.commands.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr(
        "nanobot.cli.commands._print_agent_response", lambda *_args, **_kwargs: None
    )

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert seen["cron_store"] == custom_workspace / "cron" / "jobs.json"
    assert legacy_file.exists()
    assert not (custom_workspace / "cron" / "jobs.json").exists()


def test_agent_overrides_workspace_path(mock_agent_runtime):
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(app, ["agent", "-m", "hello", "-w", str(workspace_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["config"].agents.defaults.workspace == str(workspace_path)
    assert mock_agent_runtime["sync_templates"].call_args.args == (workspace_path,)
    passed_config = mock_agent_runtime["from_config"].call_args.args[0]
    assert passed_config.workspace_path == workspace_path


def test_agent_workspace_override_wins_over_config_workspace(mock_agent_runtime, tmp_path: Path):
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}")
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(
        app,
        ["agent", "-m", "hello", "-c", str(config_path), "-w", str(workspace_path)],
    )

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (config_path.resolve(),)
    assert mock_agent_runtime["config"].agents.defaults.workspace == str(workspace_path)
    assert mock_agent_runtime["sync_templates"].call_args.args == (workspace_path,)
    passed_config = mock_agent_runtime["from_config"].call_args.args[0]
    assert passed_config.workspace_path == workspace_path


def test_agent_hints_about_deprecated_memory_window(mock_agent_runtime, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"agents": {"defaults": {"memoryWindow": 42}}}))

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert "memoryWindow" in result.stdout
    assert "no longer used" in result.stdout


def test_heartbeat_retains_recent_messages_by_default():
    config = Config()

    assert config.gateway.heartbeat.keep_recent_messages == 8


@pytest.mark.parametrize(
    "content, expected",
    [
        ("", False),
        ("# Title\n\n## Active Tasks\n", False),
        ("<!--\nmulti-line\ncomment\n-->\n", False),  # block comment, not tasks
        ("<!-- single line -->\n", False),
        ("## Active Tasks\n\n- water the plants\n", True),
        ("## Active Tasks\n\n### Garden\n\n- water the plants\n", True),
        ("## Notes\n\nsome random note\n", False),
        ("stray text before any heading\n## Active Tasks\n\n- task\n", True),
        ("stray text before any heading\n", False),
    ],
)
def test_heartbeat_has_active_tasks(content, expected):
    from nanobot.cli.commands import _heartbeat_has_active_tasks

    assert _heartbeat_has_active_tasks(content) is expected


def test_heartbeat_skips_bundled_template():
    from nanobot.cli.commands import _heartbeat_has_active_tasks
    from nanobot.utils.helpers import load_bundled_template

    assert _heartbeat_has_active_tasks(load_bundled_template("HEARTBEAT.md")) is False


def test_heartbeat_target_skips_archived_webui_sessions():
    from nanobot.cli.commands import _pick_heartbeat_target_from_sessions

    target = _pick_heartbeat_target_from_sessions(
        enabled_channels=["websocket"],
        archived_keys=["websocket:archived"],
        sessions=[
            {"key": "websocket:archived"},
            {"key": "websocket:active"},
        ],
    )

    assert target == ("websocket", "active")


def _write_instance_config(tmp_path: Path) -> Path:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")
    return config_file


def _stop_gateway_provider(_config) -> object:
    raise _StopGatewayError("stop")


def _test_provider_snapshot(provider: object, config: Config) -> ProviderSnapshot:
    return ProviderSnapshot(
        provider=provider,
        model=config.agents.defaults.model,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        signature=("test",),
    )


def _patch_webui_provider_ready(monkeypatch) -> None:
    provider = _fake_provider()

    def _snapshot(config: Config, **_kwargs) -> ProviderSnapshot:
        return _test_provider_snapshot(provider, config)

    monkeypatch.setattr("nanobot.providers.factory.build_provider_snapshot", _snapshot)


def _patch_cli_command_runtime(
    monkeypatch,
    config: Config,
    *,
    set_config_path=None,
    sync_templates=None,
    make_provider=None,
    message_bus=None,
    session_manager=None,
    cron_service=None,
    get_cron_dir=None,
) -> None:
    provider_factory = make_provider or (lambda _config: _fake_provider())

    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        set_config_path or (lambda _path: None),
    )
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.config.loader.resolve_config_env_vars", lambda c: c)
    monkeypatch.setattr(
        "nanobot.cli.commands.sync_workspace_templates",
        sync_templates or (lambda _path: None),
    )
    monkeypatch.setattr(
        "nanobot.providers.factory.make_provider",
        provider_factory,
    )
    monkeypatch.setattr(
        "nanobot.providers.factory.build_provider_snapshot",
        lambda _config: _test_provider_snapshot(provider_factory(_config), _config),
    )
    monkeypatch.setattr(
        "nanobot.providers.factory.load_provider_snapshot",
        lambda _config_path=None: _test_provider_snapshot(provider_factory(config), config),
    )

    if message_bus is not None:
        monkeypatch.setattr("nanobot.bus.queue.MessageBus", message_bus)
    if session_manager is not None:
        monkeypatch.setattr("nanobot.session.manager.SessionManager", session_manager)
    if cron_service is not None:
        monkeypatch.setattr("nanobot.cron.service.CronService", cron_service)
    if get_cron_dir is not None:
        monkeypatch.setattr("nanobot.config.paths.get_cron_dir", get_cron_dir)


def test_webui_yes_creates_config_and_enables_local_websocket(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "instance" / "config.json"
    workspace = tmp_path / "workspace"
    seen: dict[str, object] = {}
    _patch_webui_provider_ready(monkeypatch)
    monkeypatch.setattr(
        "nanobot.cli.commands.sync_workspace_templates",
        lambda path: seen.__setitem__("templates", path),
    )

    def _fake_run_gateway(config: Config, **kwargs) -> None:
        seen["gateway_config"] = config
        seen["gateway_kwargs"] = kwargs

    monkeypatch.setattr("nanobot.cli.commands._run_gateway", _fake_run_gateway)

    result = runner.invoke(
        app,
        [
            "webui",
            "--config",
            str(config_file),
            "--workspace",
            str(workspace),
            "--port",
            "8899",
            "--gateway-port",
            "18888",
            "--yes",
            "--no-open",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(config_file.read_text(encoding="utf-8"))
    websocket = data["channels"]["websocket"]
    assert websocket["enabled"] is True
    assert websocket["host"] == "127.0.0.1"
    assert websocket["port"] == 8899
    assert websocket["websocketRequiresToken"] is True
    assert isinstance(websocket["tokenIssueSecret"], str)
    assert len(websocket["tokenIssueSecret"]) >= 32
    assert data["agents"]["defaults"]["workspace"] == str(workspace)
    assert seen["templates"] == workspace
    assert seen["gateway_kwargs"] == {"port": 18888, "open_browser_url": None}


def test_webui_yes_refuses_missing_provider_setup(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"

    def _missing_provider(_config: Config, **_kwargs) -> ProviderSnapshot:
        raise ValueError("No API key configured for provider 'custom'.")

    monkeypatch.setattr("nanobot.providers.factory.build_provider_snapshot", _missing_provider)

    result = runner.invoke(app, ["webui", "--config", str(config_file), "--yes"])

    assert result.exit_code == 1
    assert "provider/model setup is incomplete" in result.stdout
    assert not config_file.exists()


def test_webui_background_starts_runtime_and_opens_browser(monkeypatch, tmp_path: Path) -> None:
    from nanobot.gateway import GatewayStartOptions, GatewayStatus, RuntimeResult

    config_file = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    config_file.write_text("{}")
    seen: dict[str, object] = {}
    _patch_webui_provider_ready(monkeypatch)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)

    class _FakeRuntime:
        def __init__(self, **kwargs) -> None:
            seen["runtime_kwargs"] = kwargs

        def start_background(self, options: GatewayStartOptions) -> RuntimeResult:
            seen["start_options"] = options
            status = GatewayStatus(
                running=True,
                pid=123,
                state_path=tmp_path / "gateway.json",
                log_path=tmp_path / "gateway.log",
                port=options.port,
                reason="running",
            )
            return RuntimeResult(True, "gateway_started_background", status)

    monkeypatch.setattr("nanobot.gateway.GatewayRuntime", _FakeRuntime)
    monkeypatch.setattr(
        "nanobot.cli.commands._open_webui_browser",
        lambda url: seen.__setitem__("opened_url", url),
    )

    result = runner.invoke(
        app,
        [
            "webui",
            "--config",
            str(config_file),
            "--workspace",
            str(workspace),
            "--background",
            "--gateway-port",
            "18889",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert "Gateway started in the background" in result.stdout
    compact_output = _strip_ansi(result.stdout).replace("\n", " ")
    assert "nanobot gateway status --config" in compact_output
    assert "--workspace" in compact_output
    options = seen["start_options"]
    assert isinstance(options, GatewayStartOptions)
    assert options.port == 18889
    assert options.config_path == str(config_file.resolve(strict=False))
    assert options.workspace == str(workspace.resolve(strict=False))
    opened_url = seen["opened_url"]
    assert isinstance(opened_url, str)
    assert opened_url.startswith("http://127.0.0.1:8765/#/?bootstrapSecret=")
    assert "bootstrapSecret=<redacted>" in compact_output
    assert "bootstrapSecret=" in opened_url


def _patch_serve_runtime(monkeypatch, config: Config, seen: dict[str, object]) -> None:
    pytest.importorskip("aiohttp")

    class _FakeApiApp:
        def __init__(self) -> None:
            self.on_startup: list[object] = []
            self.on_cleanup: list[object] = []

    class _FakeAgentLoop:
        @classmethod
        def from_config(cls, config, bus=None, **extra):
            return cls(workspace=config.workspace_path, **extra)
        def __init__(self, **kwargs) -> None:
            seen["workspace"] = kwargs["workspace"]

        async def _connect_mcp(self) -> None:
            return None

        async def close_mcp(self) -> None:
            return None

    def _fake_create_app(
        agent_loop,
        model_name: str,
        request_timeout: float,
        api_key: str = "",
    ):
        seen["agent_loop"] = agent_loop
        seen["model_name"] = model_name
        seen["request_timeout"] = request_timeout
        seen["api_key"] = api_key
        return _FakeApiApp()

    def _fake_run_app(api_app, host: str, port: int, print):
        seen["api_app"] = api_app
        seen["host"] = host
        seen["port"] = port

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
    )
    monkeypatch.setattr("nanobot.cli.commands.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.api.server.create_app", _fake_create_app)
    monkeypatch.setattr("aiohttp.web.run_app", _fake_run_app)


def test_gateway_uses_workspace_from_config_by_default(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    seen: dict[str, Path] = {}

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        set_config_path=lambda path: seen.__setitem__("config_path", path),
        sync_templates=lambda path: seen.__setitem__("workspace", path),
        make_provider=_stop_gateway_provider,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGatewayError)
    assert seen["config_path"] == config_file.resolve()
    assert seen["workspace"] == Path(config.agents.defaults.workspace)


def test_gateway_workspace_option_overrides_config(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    override = tmp_path / "override-workspace"
    seen: dict[str, Path] = {}

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        sync_templates=lambda path: seen.__setitem__("workspace", path),
        make_provider=_stop_gateway_provider,
    )

    result = runner.invoke(
        app,
        ["gateway", "--config", str(config_file), "--workspace", str(override)],
    )

    assert isinstance(result.exception, _StopGatewayError)
    assert seen["workspace"] == override
    assert config.workspace_path == override


def test_gateway_uses_workspace_directory_for_cron_store(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    seen: dict[str, Path] = {}

    class _StopCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path
            raise _StopGatewayError("stop")

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
        cron_service=_StopCron,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGatewayError)
    assert seen["cron_store"] == config.workspace_path / "cron" / "jobs.json"


def test_gateway_unbound_agent_cron_is_skipped(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    provider = _fake_provider()
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    seen: dict[str, object] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.providers.factory.make_provider", lambda _config: provider)
    monkeypatch.setattr(
        "nanobot.providers.factory.build_provider_snapshot",
        lambda _config: _test_provider_snapshot(provider, _config),
    )
    monkeypatch.setattr(
        "nanobot.providers.factory.load_provider_snapshot",
        lambda _config_path=None: _test_provider_snapshot(provider, config),
    )
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: bus)

    class _FakeSession:
        def __init__(self) -> None:
            self.messages = []

        def add_message(self, role: str, content: str, **kwargs) -> None:
            self.messages.append({"role": role, "content": content, **kwargs})

    class _FakeSessionManager:
        def __init__(self, _workspace: Path) -> None:
            self.session = _FakeSession()
            seen["session_manager"] = self

        def get_or_create(self, key: str) -> _FakeSession:
            seen["session_key"] = key
            return self.session

        def save(self, session: _FakeSession) -> None:
            seen["saved_session"] = session

    monkeypatch.setattr("nanobot.session.manager.SessionManager", _FakeSessionManager)

    class _FakeCron:
        def __init__(self, _store_path: Path) -> None:
            self.on_job = None
            seen["cron"] = self

    class _FakeAgentLoop:
        @classmethod
        def from_config(cls, config, bus=None, **extra):
            return cls(**extra)
        def __init__(self, *args, **kwargs) -> None:
            self.model = "test-model"
            self.provider = kwargs.get("provider", object())
            self.tools = {}
            seen["agent"] = self

        async def process_direct(self, *_args, **_kwargs):
            raise AssertionError("unbound cron job must not use process_direct")

        async def submit_cron_turn(self, _msg: InboundMessage):
            raise AssertionError("unbound cron job must not run as a bound cron turn")

        async def close_mcp(self) -> None:
            return None

        async def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _StopAfterCronSetup:
        def __init__(self, *_args, **_kwargs) -> None:
            raise _StopGatewayError("stop")

    async def _capture_evaluate_response(
        *_args,
        **_kwargs,
    ) -> bool:
        raise AssertionError("unbound cron job must not be evaluated for delivery")

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.cli.commands.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _StopAfterCronSetup)
    monkeypatch.setattr(
        "nanobot.cli.commands.evaluate_response",
        _capture_evaluate_response,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGatewayError)
    cron = seen["cron"]
    assert isinstance(cron, _FakeCron)
    assert cron.on_job is not None

    runtime_provider = object()
    agent = seen["agent"]
    agent.provider = runtime_provider
    agent.model = "runtime-model"

    job = CronJob(
        id="cron-1",
        name="stretch",
        payload=CronPayload(
            message="Remind me to stretch.",
            deliver=True,
            channel="telegram",
            to="user-1",
        ),
    )

    with pytest.raises(CronJobSkippedError, match="unbound agent cron job"):
        asyncio.run(cron.on_job(job))

    bus.publish_outbound.assert_not_awaited()


def test_gateway_bound_cron_runs_as_session_turn(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    provider = _fake_provider()
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    seen: dict[str, object] = {"run_records": []}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.providers.factory.make_provider", lambda _config: provider)
    monkeypatch.setattr(
        "nanobot.providers.factory.build_provider_snapshot",
        lambda _config: _test_provider_snapshot(provider, _config),
    )
    monkeypatch.setattr(
        "nanobot.providers.factory.load_provider_snapshot",
        lambda _config_path=None: _test_provider_snapshot(provider, config),
    )
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: bus)

    class _FakeSessionManager:
        def __init__(self, _workspace: Path) -> None:
            pass

    monkeypatch.setattr("nanobot.session.manager.SessionManager", _FakeSessionManager)

    class _FakeCron:
        def __init__(self, _store_path: Path) -> None:
            self.on_job = None
            seen["cron"] = self

        def write_run_record(self, run_id: str, record: dict[str, object]) -> None:
            seen["run_records"].append((run_id, record))

    class _FakeAgentLoop:
        @classmethod
        def from_config(cls, config, bus=None, **extra):
            return cls(**extra)

        def __init__(self, *args, **kwargs) -> None:
            self.model = "test-model"
            self.provider = kwargs.get("provider", object())
            self.tools = {}
            seen["agent"] = self

        async def submit_cron_turn(self, msg: InboundMessage):
            seen["cron_msg"] = msg
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Checked the repo.",
            )

        async def close_mcp(self) -> None:
            return None

        async def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _StopAfterCronSetup:
        def __init__(self, *_args, **_kwargs) -> None:
            raise _StopGatewayError("stop")

    async def _unexpected_evaluator(*_args, **_kwargs) -> bool:
        raise AssertionError("bound cron must not use legacy response evaluator")

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.cli.commands.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _StopAfterCronSetup)
    monkeypatch.setattr("nanobot.cli.commands.evaluate_response", _unexpected_evaluator)

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])
    assert isinstance(result.exception, _StopGatewayError)

    cron = seen["cron"]
    job = CronJob(
        id="repo-check",
        name="Repo check",
        payload=CronPayload(
            message="Check repository health.",
            session_key="websocket:chat-1",
            origin_channel="websocket",
            origin_chat_id="chat-1",
        ),
    )

    response = asyncio.run(cron.on_job(job))

    assert response == "Checked the repo."
    msg = seen["cron_msg"]
    assert isinstance(msg, InboundMessage)
    assert msg.channel == "websocket"
    assert msg.chat_id == "chat-1"
    assert msg.sender_id == "cron"
    assert msg.session_key_override == "websocket:chat-1"
    assert "Cron job: Check repository health." in msg.content
    assert msg.metadata["webui"] is True
    assert msg.metadata[WEBUI_MESSAGE_SOURCE_METADATA_KEY] == {
        "kind": "cron",
        "label": "Repo check",
    }
    trigger = msg.metadata[CRON_TRIGGER_META]
    assert trigger["job_id"] == "repo-check"
    assert trigger["job_name"] == "Repo check"
    assert trigger["persist_content"] == (
        "Scheduled cron job triggered: Repo check\n\nCheck repository health."
    )
    assert msg.metadata[CRON_DEFER_UNTIL_IDLE_META] is True
    statuses = [record["status"] for _run_id, record in seen["run_records"]]
    assert statuses == ["queued", "ok"]
    assert seen["run_records"][0][0] == seen["run_records"][1][0]

    discord_job = CronJob(
        id="thread-check",
        name="Thread check",
        payload=CronPayload(
            message="Check the Discord thread.",
            session_key="discord:456:thread:777",
            origin_channel="discord",
            origin_chat_id="777",
            origin_metadata={
                "context_chat_id": "456",
                "parent_channel_id": "456",
                "thread_id": "777",
            },
        ),
    )

    response = asyncio.run(cron.on_job(discord_job))

    assert response == "Checked the repo."
    msg = seen["cron_msg"]
    assert isinstance(msg, InboundMessage)
    assert msg.channel == "discord"
    assert msg.chat_id == "777"
    assert msg.session_key_override == "discord:456:thread:777"
    assert msg.metadata["context_chat_id"] == "456"
    assert msg.metadata["parent_channel_id"] == "456"
    assert msg.metadata["thread_id"] == "777"

    telegram_job = CronJob(
        id="telegram-topic",
        name="Telegram topic",
        payload=CronPayload(
            message="Check the Telegram topic.",
            session_key="telegram:-100123:topic:42",
            origin_channel="telegram",
            origin_chat_id="-100123",
            origin_metadata={"message_thread_id": 42},
        ),
    )

    response = asyncio.run(cron.on_job(telegram_job))

    assert response == "Checked the repo."
    msg = seen["cron_msg"]
    assert isinstance(msg, InboundMessage)
    assert msg.channel == "telegram"
    assert msg.chat_id == "-100123"
    assert msg.session_key_override == "telegram:-100123:topic:42"
    assert msg.metadata["message_thread_id"] == 42

    feishu_job = CronJob(
        id="feishu-topic",
        name="Feishu topic",
        payload=CronPayload(
            message="Check the Feishu topic.",
            session_key="feishu:oc_abc:om_root123",
            origin_channel="feishu",
            origin_chat_id="oc_abc",
            origin_metadata={
                "chat_type": "group",
                "message_id": "om_root123",
                "thread_id": "om_root123",
            },
        ),
    )

    response = asyncio.run(cron.on_job(feishu_job))

    assert response == "Checked the repo."
    msg = seen["cron_msg"]
    assert isinstance(msg, InboundMessage)
    assert msg.channel == "feishu"
    assert msg.chat_id == "oc_abc"
    assert msg.session_key_override == "feishu:oc_abc:om_root123"
    assert msg.metadata["message_id"] == "om_root123"
    assert msg.metadata["thread_id"] == "om_root123"


def test_gateway_local_trigger_queue_submits_agent_turns(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    config.agents.defaults.dream.enabled = False
    config.gateway.heartbeat.enabled = False
    bus = MagicMock()
    seen: dict[str, object] = {}

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: bus,
        session_manager=lambda _workspace: _FakeSessionManager(),
        cron_service=lambda _store_path: _FakeCronService(),
    )

    class _FakeMemory:
        def get_latest_cursor(self) -> int:
            return 0

        def get_last_dream_cursor(self) -> int:
            return 0

        def set_last_dream_cursor(self, _cursor: int) -> None:
            return None

    class _FakeContext:
        memory = _FakeMemory()

    class _FakeSessionManager:
        def flush_all(self) -> int:
            return 0

        def list_sessions(self) -> list[dict[str, object]]:
            return []

    class _FakeCronService:
        def __init__(self) -> None:
            self.on_job = None

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def status(self) -> dict[str, int]:
            return {"jobs": 0}

        def register_system_job(self, _job) -> None:
            return None

    class _FakeAgentLoop:
        @classmethod
        def from_config(cls, config, bus=None, **extra):
            seen["agent_from_config_kwargs"] = extra
            return cls(**extra)

        def __init__(self, *args, **kwargs) -> None:
            self.model = "test-model"
            self.provider = _fake_provider()
            self.tools = {}
            self.context = _FakeContext()
            self.sessions = kwargs["session_manager"]
            self.submit_local_trigger_turn = AsyncMock()
            seen["agent"] = self

        def _schedule_background(self, _coro) -> None:
            return None

        async def run(self) -> None:
            await asyncio.Event().wait()

        async def close_mcp(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeChannelManager:
        enabled_channels: list[str] = []

        def __init__(self, *_args, **_kwargs) -> None:
            return None

        async def start_all(self) -> None:
            await asyncio.Event().wait()

        async def stop_all(self) -> None:
            return None

    async def _fake_run_local_trigger_queue(**kwargs):
        seen["local_trigger_queue_kwargs"] = kwargs
        raise _StopGatewayError("stop")

    monkeypatch.setattr("nanobot.cli.commands.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _FakeChannelManager)
    monkeypatch.setattr(
        "nanobot.triggers.local_runner.run_local_trigger_queue",
        _fake_run_local_trigger_queue,
    )

    cli_commands._run_gateway(config, health_server_enabled=False)

    agent = seen["agent"]
    agent_kwargs = seen["agent_from_config_kwargs"]
    kwargs = seen["local_trigger_queue_kwargs"]
    assert "local_trigger_store" in agent_kwargs
    assert kwargs["store"] is agent_kwargs["local_trigger_store"]
    assert "bus" not in kwargs
    assert kwargs["submit_turn"] is agent.submit_local_trigger_turn


def test_gateway_workspace_override_does_not_migrate_legacy_cron(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = _write_instance_config(tmp_path)
    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "jobs.json"
    legacy_file.write_text('{"jobs": []}')

    override = tmp_path / "override-workspace"
    config = Config()
    seen: dict[str, Path] = {}

    class _StopCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path
            raise _StopGatewayError("stop")

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
        cron_service=_StopCron,
        get_cron_dir=lambda: legacy_dir,
    )

    result = runner.invoke(
        app,
        ["gateway", "--config", str(config_file), "--workspace", str(override)],
    )

    assert isinstance(result.exception, _StopGatewayError)
    assert seen["cron_store"] == override / "cron" / "jobs.json"
    assert legacy_file.exists()
    assert not (override / "cron" / "jobs.json").exists()


def test_gateway_custom_config_workspace_does_not_migrate_legacy_cron(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = _write_instance_config(tmp_path)
    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "jobs.json"
    legacy_file.write_text('{"jobs": []}')

    custom_workspace = tmp_path / "custom-workspace"
    config = Config()
    config.agents.defaults.workspace = str(custom_workspace)
    seen: dict[str, Path] = {}

    class _StopCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path
            raise _StopGatewayError("stop")

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
        cron_service=_StopCron,
        get_cron_dir=lambda: legacy_dir,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGatewayError)
    assert seen["cron_store"] == custom_workspace / "cron" / "jobs.json"
    assert legacy_file.exists()
    assert not (custom_workspace / "cron" / "jobs.json").exists()


def test_migrate_cron_store_moves_legacy_file(tmp_path: Path) -> None:
    """Legacy global jobs.json is moved into the workspace on first run."""
    from nanobot.cli.commands import _migrate_cron_store

    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "jobs.json"
    legacy_file.write_text('{"jobs": []}')

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    workspace_cron = config.workspace_path / "cron" / "jobs.json"

    with patch("nanobot.config.paths.get_cron_dir", return_value=legacy_dir):
        _migrate_cron_store(config)

    assert workspace_cron.exists()
    assert workspace_cron.read_text() == '{"jobs": []}'
    assert not legacy_file.exists()


def test_migrate_cron_store_skips_when_workspace_file_exists(tmp_path: Path) -> None:
    """Migration does not overwrite an existing workspace cron store."""
    from nanobot.cli.commands import _migrate_cron_store

    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "jobs.json").write_text('{"old": true}')

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    workspace_cron = config.workspace_path / "cron" / "jobs.json"
    workspace_cron.parent.mkdir(parents=True)
    workspace_cron.write_text('{"new": true}')

    with patch("nanobot.config.paths.get_cron_dir", return_value=legacy_dir):
        _migrate_cron_store(config)

    assert workspace_cron.read_text() == '{"new": true}'


def test_gateway_uses_configured_port_when_cli_flag_is_missing(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.gateway.port = 18791

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        make_provider=_stop_gateway_provider,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGatewayError)
    assert "port 18791" in result.stdout


def test_gateway_cli_port_overrides_configured_port(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.gateway.port = 18791

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        make_provider=_stop_gateway_provider,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file), "--port", "18792"])

    assert isinstance(result.exception, _StopGatewayError)
    assert "port 18792" in result.stdout


def test_gateway_health_endpoint_binds_and_serves_expected_responses(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.gateway.port = 18791
    captured: dict[str, object] = {}

    class _FakeSessionManager:
        def flush_all(self) -> int:
            return 0

    class _FakeAgentLoop:
        @classmethod
        def from_config(cls, config, bus=None, **extra):
            return cls(**extra)
        def __init__(self, **_kwargs) -> None:
            self.model = "test-model"
            self.provider = object()
            self.sessions = _FakeSessionManager()

        def llm_runtime(self) -> None:
            return None

        async def run(self) -> None:
            await asyncio.Event().wait()

        async def close_mcp(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeChannelManager:
        def __init__(self, _config, _bus, **_kwargs) -> None:
            self.enabled_channels = ["telegram", "discord"]

        async def start_all(self) -> None:
            await asyncio.Event().wait()

        async def stop_all(self) -> None:
            return None

    class _FakeCronService:
        def __init__(self, _store_path: Path) -> None:
            self.on_job = None

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def status(self) -> dict[str, int]:
            return {"jobs": 0}

        def register_system_job(self, _job) -> None:
            return None

    class _FakeServer:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def serve_forever(self) -> None:
            raise _StopGatewayError("stop")

    async def _fake_start_server(handler, host: str, port: int):
        captured["handler"] = handler
        captured["host"] = host
        captured["port"] = port
        return _FakeServer()

    class _FakeReader:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        async def read(self, _size: int) -> bytes:
            return self.payload

    class _FakeWriter:
        def __init__(self) -> None:
            self.output = b""
            self.closed = False

        def write(self, data: bytes) -> None:
            self.output += data

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
    )
    monkeypatch.setattr("nanobot.cli.commands.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _FakeChannelManager)
    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCronService)
    monkeypatch.setattr("asyncio.start_server", _fake_start_server)

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert result.exit_code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 18791
    assert "Health endpoint: http://127.0.0.1:18791/health" in result.stdout

    def _call_handler(path: str) -> tuple[str, _FakeWriter]:
        request = f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
        writer = _FakeWriter()
        handler = captured["handler"]
        assert callable(handler)
        asyncio.run(handler(_FakeReader(request), writer))
        return writer.output.decode(), writer

    root_response, root_writer = _call_handler("/")
    assert root_writer.closed is True
    assert "HTTP/1.0 404 Not Found" in root_response
    assert root_response.endswith("\r\n\r\nNot Found")

    health_response, health_writer = _call_handler("/health")
    assert health_writer.closed is True
    assert "HTTP/1.0 200 OK" in health_response
    health_body = json.loads(health_response.split("\r\n\r\n", 1)[1])
    assert health_body == {"status": "ok"}

    missing_response, missing_writer = _call_handler("/missing")
    assert missing_writer.closed is True
    assert "HTTP/1.0 404 Not Found" in missing_response
    assert missing_response.endswith("\r\n\r\nNot Found")


def test_gateway_shutdown_lets_agent_task_own_mcp_cleanup(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.gateway.port = 18791
    seen: dict[str, object] = {}

    class _FakeSessionManager:
        def flush_all(self) -> int:
            return 0

    class _FakeAgentLoop:
        @classmethod
        def from_config(cls, config, bus=None, **extra):
            return cls(**extra)

        def __init__(self, **_kwargs) -> None:
            self.model = "test-model"
            self.provider = object()
            self.sessions = _FakeSessionManager()

        def llm_runtime(self) -> None:
            return None

        async def run(self) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                seen["agent_task_cleaned_up"] = True

        async def close_mcp(self) -> None:
            raise AssertionError("gateway must not close MCP from the outer task")

        def stop(self) -> None:
            seen["agent_stopped"] = True

    class _FakeChannelManager:
        def __init__(self, _config, _bus, **_kwargs) -> None:
            self.enabled_channels = ["telegram"]

        async def start_all(self) -> None:
            await asyncio.Event().wait()

        async def stop_all(self) -> None:
            seen["channels_stopped"] = True

    class _FakeCronService:
        def __init__(self, _store_path: Path) -> None:
            self.on_job = None

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            seen["cron_stopped"] = True

        def status(self) -> dict[str, int]:
            return {"jobs": 0}

        def register_system_job(self, _job) -> None:
            return None

    class _FakeServer:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def serve_forever(self) -> None:
            raise _StopGatewayError("stop")

    async def _fake_start_server(_handler, _host: str, _port: int):
        return _FakeServer()

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
    )
    monkeypatch.setattr("nanobot.cli.commands.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _FakeChannelManager)
    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCronService)
    monkeypatch.setattr("asyncio.start_server", _fake_start_server)

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert result.exit_code == 0
    assert seen["agent_stopped"] is True
    assert seen["agent_task_cleaned_up"] is True
    assert seen["channels_stopped"] is True
    assert seen["cron_stopped"] is True


def test_gateway_shutdown_event_exits_forever_runtime_tasks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.gateway.port = 18791
    seen: dict[str, object] = {}

    class _FakeSessionManager:
        def flush_all(self) -> int:
            return 0

    class _FakeAgentLoop:
        @classmethod
        def from_config(cls, config, bus=None, **extra):
            return cls(**extra)

        def __init__(self, **_kwargs) -> None:
            self.model = "test-model"
            self.provider = object()
            self.sessions = _FakeSessionManager()

        def llm_runtime(self) -> None:
            return None

        async def run(self) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                seen["agent_task_cleaned_up"] = True

        async def close_mcp(self) -> None:
            raise AssertionError("gateway must not close MCP from the outer task")

        def stop(self) -> None:
            seen["agent_stopped"] = True

    class _FakeChannelManager:
        def __init__(self, _config, _bus, **_kwargs) -> None:
            self.enabled_channels = ["websocket"]

        async def start_all(self) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                seen["channel_task_cleaned_up"] = True

        async def stop_all(self) -> None:
            seen["channels_stopped"] = True

    class _FakeCronService:
        def __init__(self, _store_path: Path) -> None:
            self.on_job = None

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            seen["cron_stopped"] = True

        def status(self) -> dict[str, int]:
            return {"jobs": 0}

        def register_system_job(self, _job) -> None:
            return None

    class _FakeServer:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def serve_forever(self) -> None:
            await asyncio.Event().wait()

    async def _fake_start_server(_handler, _host: str, _port: int):
        return _FakeServer()

    def _fake_install_shutdown_handlers(_loop, event, _tasks, _print_status):
        async def _trigger_shutdown() -> None:
            await asyncio.sleep(0)
            event.set()

        asyncio.create_task(_trigger_shutdown())

        def _restore() -> None:
            seen["shutdown_handlers_restored"] = True

        return _restore

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
    )
    monkeypatch.setattr("nanobot.cli.commands.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _FakeChannelManager)
    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCronService)
    monkeypatch.setattr("asyncio.start_server", _fake_start_server)
    monkeypatch.setattr(
        "nanobot.cli.commands._install_gateway_shutdown_handlers",
        _fake_install_shutdown_handlers,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert result.exit_code == 0
    assert seen["agent_stopped"] is True
    assert seen["agent_task_cleaned_up"] is True
    assert seen["channel_task_cleaned_up"] is True
    assert seen["channels_stopped"] is True
    assert seen["cron_stopped"] is True
    assert seen["shutdown_handlers_restored"] is True


def test_serve_uses_api_config_defaults_and_workspace_override(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    config.api.host = "127.0.0.2"
    config.api.port = 18900
    config.api.timeout = 45.0
    config.api.api_key = "secret"
    override_workspace = tmp_path / "override-workspace"
    seen: dict[str, object] = {}

    _patch_serve_runtime(monkeypatch, config, seen)

    result = runner.invoke(
        app,
        ["serve", "--config", str(config_file), "--workspace", str(override_workspace)],
    )

    assert result.exit_code == 0
    assert seen["workspace"] == override_workspace
    assert seen["host"] == "127.0.0.2"
    assert seen["port"] == 18900
    assert seen["request_timeout"] == 45.0
    assert seen["api_key"] == "secret"


def test_trigger_cli_queues_message_in_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.triggers.local_store import LocalTriggerStore

    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    _patch_cli_command_runtime(monkeypatch, config)

    store = LocalTriggerStore(config.workspace_path)
    trigger = store.create(
        name="Review hook",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )

    result = runner.invoke(
        app,
        ["trigger", "--config", str(config_file), trigger.id, "Review PR #4502"],
    )

    assert result.exit_code == 0
    assert f"Queued {trigger.id}" in result.stdout
    deliveries = store.claim_deliveries()
    assert len(deliveries) == 1
    assert deliveries[0].trigger_id == trigger.id
    assert deliveries[0].content == "Review PR #4502"


def test_serve_cli_options_override_api_config(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.api.host = "127.0.0.2"
    config.api.port = 18900
    config.api.timeout = 45.0
    config.api.api_key = "secret"
    seen: dict[str, object] = {}

    _patch_serve_runtime(monkeypatch, config, seen)

    result = runner.invoke(
        app,
        [
            "serve",
            "--config",
            str(config_file),
            "--host",
            "127.0.0.1",
            "--port",
            "18901",
            "--timeout",
            "46",
        ],
    )

    assert result.exit_code == 0
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 18901
    assert seen["request_timeout"] == 46.0
    assert seen["api_key"] == "secret"


def test_serve_allows_loopback_without_api_key(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    seen: dict[str, object] = {}

    _patch_serve_runtime(monkeypatch, config, seen)

    result = runner.invoke(app, ["serve", "--config", str(config_file)])

    assert result.exit_code == 0
    assert seen["host"] == "127.0.0.1"
    assert seen["api_key"] == ""


def test_serve_passes_configured_api_key(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.api.api_key = " secret "
    seen: dict[str, object] = {}

    _patch_serve_runtime(monkeypatch, config, seen)

    result = runner.invoke(app, ["serve", "--config", str(config_file)])

    assert result.exit_code == 0
    assert seen["api_key"] == "secret"


def test_serve_rejects_wildcard_host_without_api_key(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    seen: dict[str, object] = {}

    _patch_serve_runtime(monkeypatch, config, seen)

    result = runner.invoke(app, ["serve", "--config", str(config_file), "--host", "0.0.0.0"])

    assert result.exit_code == 1
    assert "api_key is not set" in result.stdout
    assert "workspace" not in seen
    assert "api_app" not in seen


def test_channels_login_requires_channel_name() -> None:
    result = runner.invoke(app, ["channels", "login"])

    assert result.exit_code == 2
