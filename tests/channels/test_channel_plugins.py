"""Tests for channel plugin discovery, merging, and config compatibility."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tomllib
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import (
    ProgressEvent,
    StreamDeltaEvent,
    StreamedResponseEvent,
    StreamEndEvent,
    outbound_message_for_event,
)
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.loader import save_config
from nanobot.config.schema import ChannelsConfig, Config
from nanobot.providers.transcription import GroqTranscriptionProvider as _GroqProvider
from nanobot.providers.transcription import OpenAITranscriptionProvider as _OpenAIProvider
from nanobot.utils.restart import RestartNotice

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakePlugin(BaseChannel):
    name = "fakeplugin"
    display_name = "Fake Plugin"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.login_calls: list[bool] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass

    async def login(self, force: bool = False) -> bool:
        self.login_calls.append(force)
        return True


class _FakeTelegram(BaseChannel):
    """Plugin that tries to shadow built-in telegram."""
    name = "telegram"
    display_name = "Fake Telegram"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass


def _make_entry_point(name: str, cls: type):
    """Create a mock entry point that returns *cls* on load()."""
    ep = SimpleNamespace(name=name, load=lambda _cls=cls: _cls)
    return ep


# ---------------------------------------------------------------------------
# ChannelsConfig extra="allow"
# ---------------------------------------------------------------------------

def test_channels_config_accepts_unknown_keys():
    cfg = ChannelsConfig.model_validate({
        "myplugin": {"enabled": True, "token": "abc"},
    })
    extra = cfg.model_extra
    assert extra is not None
    assert extra["myplugin"]["enabled"] is True
    assert extra["myplugin"]["token"] == "abc"


def test_channels_config_getattr_returns_extra():
    cfg = ChannelsConfig.model_validate({"myplugin": {"enabled": True}})
    section = getattr(cfg, "myplugin", None)
    assert isinstance(section, dict)
    assert section["enabled"] is True


def test_channels_config_builtin_fields_removed():
    """After decoupling, ChannelsConfig has no explicit channel fields."""
    cfg = ChannelsConfig()
    assert not hasattr(cfg, "telegram")
    assert cfg.send_progress is True
    assert cfg.send_tool_hints is False
    assert cfg.extract_document_text is True


def test_channels_config_extract_document_text_accepts_camel_alias():
    cfg = ChannelsConfig.model_validate({"extractDocumentText": False})

    assert cfg.extract_document_text is False


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------

_EP_TARGET = "importlib.metadata.entry_points"


def test_discover_plugins_loads_entry_points():
    from nanobot.channels.registry import discover_plugins

    ep = _make_entry_point("line", _FakePlugin)
    with patch(_EP_TARGET, return_value=[ep]):
        result = discover_plugins()

    assert "line" in result
    assert result["line"] is _FakePlugin


def test_discover_plugins_skips_names_outside_enabled_set():
    from nanobot.channels.registry import discover_plugins

    loaded: list[str] = []

    def _load_disabled():
        loaded.append("disabled")
        return _FakePlugin

    ep = SimpleNamespace(name="disabled", load=_load_disabled)
    with patch(_EP_TARGET, return_value=[ep]):
        result = discover_plugins({"enabled"})

    assert result == {}
    assert loaded == []


def test_discover_plugins_handles_load_error():
    from nanobot.channels.registry import discover_plugins

    def _boom():
        raise RuntimeError("broken")

    ep = SimpleNamespace(name="broken", load=_boom)
    with patch(_EP_TARGET, return_value=[ep]):
        result = discover_plugins()

    assert "broken" not in result


# ---------------------------------------------------------------------------
# discover_all — merge & priority
# ---------------------------------------------------------------------------

def test_discover_all_includes_builtins():
    from nanobot.channels.registry import discover_all, discover_channel_names

    with patch(_EP_TARGET, return_value=[]):
        result = discover_all()

    # discover_all() only returns channels that are actually available (dependencies installed)
    # discover_channel_names() returns all built-in channel names
    # So we check that all actually loaded channels are in the result
    for name in result:
        assert name in discover_channel_names()


def test_discover_all_includes_external_plugin():
    from nanobot.channels.registry import discover_all

    ep = _make_entry_point("line", _FakePlugin)
    with patch(_EP_TARGET, return_value=[ep]):
        result = discover_all()

    assert "line" in result
    assert result["line"] is _FakePlugin


def test_discover_enabled_imports_only_enabled_builtins():
    from nanobot.channels.registry import discover_enabled

    loaded: list[str] = []

    def _load_channel(name: str):
        loaded.append(name)
        return _FakePlugin

    with (
        patch("nanobot.channels.registry.load_channel_class", side_effect=_load_channel),
        patch(_EP_TARGET, return_value=[]),
    ):
        result = discover_enabled({"enabled"}, _names=["enabled", "disabled"])

    assert result == {"enabled": _FakePlugin}
    assert loaded == ["enabled"]


def test_discover_all_builtin_shadows_plugin():
    from nanobot.channels.registry import discover_all

    ep = _make_entry_point("telegram", _FakeTelegram)
    with patch(_EP_TARGET, return_value=[ep]):
        result = discover_all()

    assert "telegram" in result
    assert result["telegram"] is not _FakeTelegram


def test_discover_all_builtin_name_shadows_plugin_when_dependency_missing():
    from nanobot.channels.registry import discover_all

    ep = _make_entry_point("telegram", _FakeTelegram)
    with (
        patch("nanobot.channels.registry.discover_channel_names", return_value=["telegram"]),
        patch("nanobot.channels.registry.load_channel_class", side_effect=ImportError("missing")),
        patch(_EP_TARGET, return_value=[ep]),
    ):
        result = discover_all()

    assert "telegram" not in result


# ---------------------------------------------------------------------------
# Manager _init_channels with dict config (plugin scenario)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_loads_plugin_from_dict_config():
    """ChannelManager should instantiate a plugin channel from a raw dict config."""
    from nanobot.channels.manager import ChannelManager

    fake_config = SimpleNamespace(
        channels=ChannelsConfig.model_validate({
            "fakeplugin": {"enabled": True, "allowFrom": ["*"]},
        }),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="", api_base="")),
    )

    with patch(
        "nanobot.channels.registry.discover_enabled",
        return_value={"fakeplugin": _FakePlugin},
    ):
        mgr = ChannelManager.__new__(ChannelManager)
        mgr.config = fake_config
        mgr.bus = MessageBus()
        mgr.channels = {}
        mgr._dispatch_task = None
        mgr._init_channels()

    assert "fakeplugin" in mgr.channels
    assert isinstance(mgr.channels["fakeplugin"], _FakePlugin)


def test_manager_loads_websocket_from_default_config():
    from nanobot.channels.manager import ChannelManager

    class _FakeWebSocket(_FakePlugin):
        name = "websocket"
        display_name = "WebSocket"

        def __init__(self, config, bus, *, gateway):
            super().__init__(config, bus)
            self.gateway = gateway

    seen_enabled: set[str] = set()

    def _discover_enabled(enabled_names: set[str], _names=None):
        seen_enabled.update(enabled_names)
        return {"websocket": _FakeWebSocket} if "websocket" in enabled_names else {}

    with (
        patch("nanobot.channels.registry.discover_channel_names", return_value=["websocket"]),
        patch("nanobot.channels.registry.discover_enabled", side_effect=_discover_enabled),
    ):
        mgr = ChannelManager(Config(), MessageBus(), webui_static_dist=False)

    assert "websocket" in seen_enabled
    assert mgr.channels["websocket"].config["enabled"] is True
    assert mgr.channels["websocket"].config["host"] == "127.0.0.1"


def test_manager_respects_explicitly_disabled_websocket_config():
    from nanobot.channels.manager import ChannelManager

    seen_enabled: set[str] = set()

    def _discover_enabled(enabled_names: set[str], _names=None):
        seen_enabled.update(enabled_names)
        return {}

    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    with (
        patch("nanobot.channels.registry.discover_channel_names", return_value=["websocket"]),
        patch("nanobot.channels.registry.discover_enabled", side_effect=_discover_enabled),
    ):
        mgr = ChannelManager(config, MessageBus(), webui_static_dist=False)

    assert "websocket" not in seen_enabled
    assert "websocket" not in mgr.channels


@pytest.mark.asyncio
async def test_base_channel_reads_current_transcription_config_each_call(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    """BaseChannel.transcribe_audio resolves config at call time, not manager init time."""
    from nanobot.providers import transcription as transcription_mod

    config_path = tmp_path / "config.json"
    config = Config()
    config.transcription.provider = "openai"
    config.transcription.model = "whisper-custom"
    config.transcription.language = "en"
    config.providers.openai.api_key = "openai-key"
    config.providers.openai.api_base = "http://openai.local/v1/audio/transcriptions"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    channel = _FakePlugin({"enabled": True, "allowFrom": ["*"]}, MessageBus())

    calls: list[dict[str, object]] = []

    class _StubOpenAI:
        def __init__(self, api_key=None, api_base=None, language=None, model=None):
            calls.append({
                "provider": "openai",
                "api_key": api_key,
                "api_base": api_base,
                "language": language,
                "model": model,
            })

        async def transcribe(self, file_path):
            return "openai-ok"

    class _StubGroq:
        def __init__(self, api_key=None, api_base=None, language=None, model=None):
            calls.append({
                "provider": "groq",
                "api_key": api_key,
                "api_base": api_base,
                "language": language,
                "model": model,
            })

        async def transcribe(self, file_path):
            return "groq-ok"

    with (
        patch.object(transcription_mod, "OpenAITranscriptionProvider", _StubOpenAI),
        patch.object(transcription_mod, "GroqTranscriptionProvider", _StubGroq),
    ):
        assert await channel.transcribe_audio("/tmp/does-not-matter.wav") == "openai-ok"

        config.transcription.provider = "groq"
        config.transcription.model = "whisper-large-v3-turbo"
        config.transcription.language = "ko"
        config.providers.groq.api_key = "groq-key"
        config.providers.groq.api_base = "http://groq.local/v1/audio/transcriptions"
        save_config(config, config_path)

        assert await channel.transcribe_audio("/tmp/does-not-matter.wav") == "groq-ok"

    assert calls == [
        {
            "provider": "openai",
            "api_key": "openai-key",
            "api_base": "http://openai.local/v1/audio/transcriptions",
            "language": "en",
            "model": "whisper-custom",
        },
        {
            "provider": "groq",
            "api_key": "groq-key",
            "api_base": "http://groq.local/v1/audio/transcriptions",
            "language": "ko",
            "model": "whisper-large-v3-turbo",
        },
    ]


@pytest.mark.asyncio
async def test_base_channel_respects_disabled_transcription_config(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.json"
    config = Config()
    config.transcription.enabled = False
    config.providers.groq.api_key = "groq-key"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    channel = _FakePlugin({"enabled": True, "allowFrom": ["*"]}, MessageBus())

    with patch("nanobot.providers.transcription.GroqTranscriptionProvider") as provider:
        assert await channel.transcribe_audio("/tmp/does-not-matter.wav") == ""
    provider.assert_not_called()


def test_openai_transcription_provider_honors_api_base_argument():
    from nanobot.providers.transcription import OpenAITranscriptionProvider

    default = OpenAITranscriptionProvider(api_key="k")
    assert default.api_url == "https://api.openai.com/v1/audio/transcriptions"

    custom = OpenAITranscriptionProvider(
        api_key="k", api_base="http://override/v1/audio/transcriptions"
    )
    assert custom.api_url == "http://override/v1/audio/transcriptions"


# ---------------------------------------------------------------------------
# Transcription provider HTTP tests
# ---------------------------------------------------------------------------


class _StubResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"text": "hello"}


def _stub_async_client(captured: dict[str, object]):
    """Return an httpx.AsyncClient stub that records POST calls into *captured*."""
    class _AsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, files=None, timeout=None):
            captured["files"] = files
            return _StubResponse()

    return _AsyncClient()


@pytest.mark.parametrize(
    "provider_cls,language",
    [(_GroqProvider, "ko"), (_OpenAIProvider, "en")],
    ids=["groq", "openai"],
)
@pytest.mark.asyncio
async def test_transcription_provider_includes_language(tmp_path, provider_cls, language):
    """Provider must include the 'language' field in multipart body when set."""
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")
    captured: dict[str, object] = {}

    with patch("nanobot.providers.transcription.httpx.AsyncClient", return_value=_stub_async_client(captured)):
        provider = provider_cls(api_key="k", language=language)
        result = await provider.transcribe(audio)

    assert result == "hello"
    assert captured["files"]["language"] == (None, language)


@pytest.mark.parametrize(
    "provider_cls",
    [_GroqProvider, _OpenAIProvider],
    ids=["groq", "openai"],
)
@pytest.mark.asyncio
async def test_transcription_provider_omits_language_when_none(tmp_path, provider_cls):
    """When language is not set, the 'language' key must be absent from the multipart body."""
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")
    captured: dict[str, object] = {}

    with patch("nanobot.providers.transcription.httpx.AsyncClient", return_value=_stub_async_client(captured)):
        provider = provider_cls(api_key="k")
        result = await provider.transcribe(audio)

    assert result == "hello"
    assert "language" not in captured["files"]


def test_channels_login_uses_discovered_plugin_class(monkeypatch):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    from nanobot.config.schema import Config

    runner = CliRunner()
    seen: dict[str, object] = {}

    class _LoginPlugin(_FakePlugin):
        display_name = "Login Plugin"

        async def login(self, force: bool = False) -> bool:
            seen["force"] = force
            seen["config"] = self.config
            return True

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda config_path=None: Config())
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_all",
        lambda: {"fakeplugin": _LoginPlugin},
    )

    result = runner.invoke(app, ["channels", "login", "fakeplugin", "--force"])

    assert result.exit_code == 0
    assert seen["force"] is True


def test_channels_login_sets_custom_config_path(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    from nanobot.config.schema import Config

    runner = CliRunner()
    seen: dict[str, object] = {}
    config_path = tmp_path / "custom-config.json"

    class _LoginPlugin(_FakePlugin):
        async def login(self, force: bool = False) -> bool:
            return True

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda config_path=None: Config())
    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_all",
        lambda: {"fakeplugin": _LoginPlugin},
    )

    result = runner.invoke(app, ["channels", "login", "fakeplugin", "--config", str(config_path)])

    assert result.exit_code == 0
    assert seen["config_path"] == config_path.resolve()


def test_channels_status_sets_custom_config_path(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    from nanobot.config.schema import Config

    runner = CliRunner()
    seen: dict[str, object] = {}
    config_path = tmp_path / "custom-config.json"

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda config_path=None: Config())
    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr("nanobot.channels.registry.discover_all", lambda: {})

    result = runner.invoke(app, ["channels", "status", "--config", str(config_path)])

    assert result.exit_code == 0
    assert seen["config_path"] == config_path.resolve()


def test_plugins_list_shows_available_features(monkeypatch):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    from nanobot.config.schema import Config

    runner = CliRunner()
    config = Config.model_validate({"channels": {"weixin": {"enabled": True}}})
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda config_path=None: config)
    monkeypatch.setattr("nanobot.channels.registry.discover_channel_names", lambda: ["weixin"])
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {})
    monkeypatch.setattr(
        "nanobot.cli.commands._optional_dependency_groups",
        lambda: {"weixin": ["qrcode[pil]>=8.0"], "bedrock": ["boto3>=1.43.0"]},
    )

    result = runner.invoke(app, ["plugins", "list"])

    assert result.exit_code == 0
    assert "Available Features" in result.stdout
    assert "weixin" in result.stdout
    assert "bedrock" in result.stdout
    assert "channel" in result.stdout
    assert "feature" in result.stdout
    assert " - " not in result.stdout


def test_plugins_enable_channel_installs_extra_and_writes_config(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    class _WeixinChannel(_FakePlugin):
        name = "weixin"
        display_name = "Weixin"

        @classmethod
        def default_config(cls):
            return {"enabled": False, "token": "", "allowFrom": []}

    commands: list[list[str]] = []
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"channels": {"weixin": {"enabled": False, "token": "keep"}}}),
        encoding="utf-8",
    )

    def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    runner = CliRunner()
    monkeypatch.setattr("nanobot.channels.registry.discover_channel_names", lambda: ["weixin"])
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {})
    monkeypatch.setattr("nanobot.channels.registry.load_channel_class", lambda _name: _WeixinChannel)
    monkeypatch.setattr(
        "nanobot.cli.commands._optional_dependency_groups",
        lambda: {"weixin": ["qrcode[pil]>=8.0", "pycryptodome>=3.20.0"]},
    )
    monkeypatch.setattr("nanobot.cli.commands._extra_installed", lambda _name, _deps: False)
    monkeypatch.setattr("nanobot.cli.commands._run_install_command", _run)

    result = runner.invoke(app, ["plugins", "enable", "weixin", "--config", str(config_path)])

    assert result.exit_code == 0
    assert commands == [
        [sys.executable, "-m", "pip", "install", "qrcode[pil]>=8.0", "pycryptodome>=3.20.0"]
    ]
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["weixin"]["enabled"] is True
    assert data["channels"]["weixin"]["token"] == "keep"
    assert data["channels"]["weixin"]["allowFrom"] == []


def test_plugins_enable_extra_without_channel_only_installs(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    commands: list[list[str]] = []
    config_path = tmp_path / "config.json"

    def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    runner = CliRunner()
    monkeypatch.setattr("nanobot.channels.registry.discover_channel_names", lambda: [])
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {})
    monkeypatch.setattr(
        "nanobot.cli.commands._optional_dependency_groups",
        lambda: {"bedrock": ["boto3>=1.43.0"]},
    )
    monkeypatch.setattr("nanobot.cli.commands._extra_installed", lambda _name, _deps: False)
    monkeypatch.setattr("nanobot.cli.commands._run_install_command", _run)

    result = runner.invoke(app, ["plugins", "enable", "bedrock", "--config", str(config_path)])

    assert result.exit_code == 0
    assert commands == [[sys.executable, "-m", "pip", "install", "boto3>=1.43.0"]]
    assert not config_path.exists()


def test_plugins_enable_skips_install_when_extra_is_present(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    commands: list[list[str]] = []
    config_path = tmp_path / "config.json"

    def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    runner = CliRunner()
    monkeypatch.setattr("nanobot.channels.registry.discover_channel_names", lambda: [])
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {})
    monkeypatch.setattr(
        "nanobot.cli.commands._optional_dependency_groups",
        lambda: {"bedrock": ["boto3>=1.43.0"]},
    )
    monkeypatch.setattr("nanobot.cli.commands._extra_installed", lambda _name, _deps: True)
    monkeypatch.setattr("nanobot.cli.commands._run_install_command", _run)

    result = runner.invoke(app, ["plugins", "enable", "bedrock", "--config", str(config_path)])

    assert result.exit_code == 0
    assert commands == []
    assert not config_path.exists()


def test_enable_bootstraps_pip_with_ensurepip(monkeypatch):
    from nanobot.cli import commands as cli_commands

    calls: list[list[str]] = []

    def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="No module named pip")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(cli_commands, "_run_install_command", _run)
    monkeypatch.setattr("nanobot.optional_features.shutil.which", lambda _name: None)

    assert cli_commands._install_extra("weixin", None) is True
    assert calls == [
        [cli_commands.sys.executable, "-m", "pip", "install", "nanobot-ai[weixin]"],
        [cli_commands.sys.executable, "-m", "ensurepip", "--upgrade"],
        [cli_commands.sys.executable, "-m", "pip", "install", "nanobot-ai[weixin]"],
    ]


def test_install_extra_logs_command_and_output(monkeypatch):
    from nanobot import optional_features

    records: list[str] = []

    class _Logger:
        def info(self, message: str, *args: object) -> None:
            records.append(message.format(*args))

    def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout="install ok", stderr="")

    monkeypatch.setattr(optional_features, "logger", _Logger())

    result = optional_features.install_extra("weixin", ["qrcode[pil]>=8.0"], runner=_run)

    assert result.ok is True
    assert any("Installing optional feature 'weixin':" in record for record in records)
    assert any("Optional feature 'weixin' install exited with code 0" in record for record in records)
    assert any("install ok" in record for record in records)


def test_run_install_command_returns_failure_on_timeout(monkeypatch):
    from nanobot import optional_features

    def _run(*args, **kwargs):
        raise subprocess.TimeoutExpired(["pip"], 300, output="partial", stderr=b"still running")

    monkeypatch.setattr(optional_features.subprocess, "run", _run)

    result = optional_features.run_install_command(["pip"])

    assert result.returncode == 124
    assert result.stdout == "partial"
    assert result.stderr == "still running\nTimed out after 300s"


def test_optional_dependency_metadata_for_enable():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["optional-dependencies"]
    required = data["project"]["dependencies"]

    assert "boto3>=1.43.0" not in data["project"]["dependencies"]
    assert deps["bedrock"] == ["boto3>=1.43.0"]
    for dep_name in (
        "aiohttp",
        "dingtalk-stream",
        "lark-oapi",
        "msgpack",
        "openpyxl",
        "pypdf",
        "python-telegram-bot",
        "python-docx",
        "python-pptx",
        "python-socketio",
        "qq-botpy",
        "slack-sdk",
        "slackify-markdown",
    ):
        assert not any(dep.startswith(dep_name) for dep in required)
    assert deps["dingtalk"] == ["dingtalk-stream>=0.24.0,<1.0.0"]
    assert deps["documents"] == [
        "pypdf>=5.0.0,<6.0.0",
        "python-docx>=1.1.0,<2.0.0",
        "openpyxl>=3.1.0,<4.0.0",
        "python-pptx>=1.0.0,<2.0.0",
    ]
    assert deps["feishu"] == ["lark-oapi>=1.5.0,<2.0.0"]
    assert deps["mochat"] == [
        "python-socketio>=5.16.0,<6.0.0",
        "msgpack>=1.1.0,<2.0.0",
    ]
    assert deps["napcat"] == ["aiohttp>=3.9.0,<4.0.0"]
    assert deps["qq"] == ["aiohttp>=3.9.0,<4.0.0", "qq-botpy>=1.2.0,<2.0.0"]
    assert deps["slack"] == [
        "slack-sdk>=3.39.0,<4.0.0",
        "slackify-markdown>=0.2.0,<1.0.0",
    ]
    assert any(dep.startswith("python-telegram-bot") for dep in deps["telegram"])
    assert any(
        dep.startswith("matrix-nio>=0.25.2") and "sys_platform == 'win32'" in dep
        for dep in deps["matrix"]
    )


def test_optional_dependency_groups_falls_back_to_package_metadata(monkeypatch):
    from nanobot import optional_features

    class _Metadata:
        def get_all(self, key: str):
            assert key == "Provides-Extra"
            return ["bedrock", "dev"]

    monkeypatch.setattr(optional_features, "load_pyproject", lambda _path: {})
    monkeypatch.setattr("importlib.metadata.metadata", lambda _name: _Metadata())
    monkeypatch.setattr(
        "importlib.metadata.requires",
        lambda _name: [
            "packaging>=24.0",
            "boto3>=1.43.0; extra == 'bedrock'",
            "pytest>=8.0; extra == 'dev'",
        ],
    )

    deps = optional_features.optional_dependency_groups()

    assert deps == {"bedrock": ["boto3>=1.43.0; extra == 'bedrock'"]}
    assert optional_features.install_args_for_extra("bedrock", deps["bedrock"]) == (
        ["nanobot-ai[bedrock]"],
        '"nanobot-ai[bedrock]"',
    )


def test_requirement_installed_validates_requested_extras(monkeypatch):
    from nanobot import optional_features

    class _Metadata:
        def __init__(self, extras: list[str] | None = None) -> None:
            self._extras = extras or []

        def get_all(self, key: str):
            assert key == "Provides-Extra"
            return self._extras

    class _Distribution:
        def __init__(
            self,
            version: str,
            *,
            requires: list[str] | None = None,
            extras: list[str] | None = None,
        ) -> None:
            self.version = version
            self.requires = requires or []
            self.metadata = _Metadata(extras)

    installed: dict[str, _Distribution] = {
        "qrcode": _Distribution(
            "8.2",
            requires=["pillow>=9.1; extra == 'pil'"],
            extras=["pil"],
        ),
    }

    def _distribution(name: str) -> _Distribution:
        normalized = name.lower()
        if normalized not in installed:
            raise PackageNotFoundError(name)
        return installed[normalized]

    monkeypatch.setattr(optional_features, "distribution", _distribution)

    assert optional_features.requirement_installed("qrcode>=8.0") is True
    assert optional_features.requirement_installed("qrcode[pil]>=8.0") is False

    installed["pillow"] = _Distribution("10.0")

    assert optional_features.requirement_installed("qrcode[pil]>=8.0") is True


@pytest.mark.asyncio
async def test_manager_skips_disabled_plugin():
    fake_config = SimpleNamespace(
        channels=ChannelsConfig.model_validate({
            "fakeplugin": {"enabled": False},
        }),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    ep = _make_entry_point("fakeplugin", _FakePlugin)
    with patch(_EP_TARGET, return_value=[ep]):
        mgr = ChannelManager.__new__(ChannelManager)
        mgr.config = fake_config
        mgr.bus = MessageBus()
        mgr.channels = {}
        mgr._dispatch_task = None
        mgr._init_channels()

    assert "fakeplugin" not in mgr.channels


# ---------------------------------------------------------------------------
# Built-in channel default_config() and dict->Pydantic conversion
# ---------------------------------------------------------------------------

def test_builtin_channel_default_config():
    """Built-in channels expose default_config() returning a dict with 'enabled': False."""
    from nanobot.channels.dingtalk import DingTalkChannel
    cfg = DingTalkChannel.default_config()
    assert isinstance(cfg, dict)
    assert cfg["enabled"] is False
    assert "clientId" in cfg


def test_builtin_channel_init_from_dict():
    """Built-in channels accept a raw dict and convert to Pydantic internally."""
    from nanobot.channels.dingtalk import DingTalkChannel
    bus = MessageBus()
    ch = DingTalkChannel({"enabled": False, "clientId": "test-id", "allowFrom": ["*"]}, bus)
    assert ch.config.client_id == "test-id"
    assert ch.config.allow_from == ["*"]


def test_channels_config_send_max_retries_default():
    """ChannelsConfig should have send_max_retries with default value of 3."""
    cfg = ChannelsConfig()
    assert hasattr(cfg, 'send_max_retries')
    assert cfg.send_max_retries == 3


def test_channels_config_send_max_retries_upper_bound():
    """send_max_retries should be bounded to prevent resource exhaustion."""
    from pydantic import ValidationError

    # Value too high should be rejected
    with pytest.raises(ValidationError):
        ChannelsConfig(send_max_retries=100)

    # Negative should be rejected
    with pytest.raises(ValidationError):
        ChannelsConfig(send_max_retries=-1)

    # Boundary values should be allowed
    cfg_min = ChannelsConfig(send_max_retries=0)
    assert cfg_min.send_max_retries == 0

    cfg_max = ChannelsConfig(send_max_retries=10)
    assert cfg_max.send_max_retries == 10

    # Value above upper bound should be rejected
    with pytest.raises(ValidationError):
        ChannelsConfig(send_max_retries=11)


def test_channels_config_transcription_language_pattern():
    """transcription_language must match ISO-639 format (2-3 lowercase letters) or be None."""
    from pydantic import ValidationError

    # Valid values
    assert ChannelsConfig(transcription_language="en").transcription_language == "en"
    assert ChannelsConfig(transcription_language="kor").transcription_language == "kor"
    assert ChannelsConfig(transcription_language=None).transcription_language is None

    # Invalid values
    with pytest.raises(ValidationError):
        ChannelsConfig(transcription_language="EN")       # uppercase
    with pytest.raises(ValidationError):
        ChannelsConfig(transcription_language="english")   # full word
    with pytest.raises(ValidationError):
        ChannelsConfig(transcription_language="en-US")     # BCP 47 tag


# ---------------------------------------------------------------------------
# _send_with_retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_with_retry_succeeds_first_try():
    """_send_with_retry should succeed on first try and not retry."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            # Succeeds on first try

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")
    await mgr._send_with_retry(mgr.channels["failing"], msg)

    assert call_count == 1


@pytest.mark.asyncio
async def test_send_with_retry_retries_on_failure():
    """_send_with_retry should retry on failure up to max_retries times."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated failure")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")

    # Patch asyncio.sleep to avoid actual delays
    with patch("nanobot.channels.manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await mgr._send_with_retry(mgr.channels["failing"], msg)

    assert call_count == 3  # 3 total attempts (initial + 2 retries)
    assert mock_sleep.call_count == 2  # 2 sleeps between retries


@pytest.mark.asyncio
async def test_send_with_retry_no_retry_when_max_is_zero():
    """_send_with_retry should not retry when send_max_retries is 0."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated failure")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=0),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")

    with patch("nanobot.channels.manager.asyncio.sleep", new_callable=AsyncMock):
        await mgr._send_with_retry(mgr.channels["failing"], msg)

    assert call_count == 1  # Called once but no retry (max(0, 1) = 1)


@pytest.mark.asyncio
async def test_send_with_retry_calls_send_delta():
    """_send_with_retry should call send_delta for stream delta events."""
    send_delta_called = False

    class _StreamingChannel(BaseChannel):
        name = "streaming"
        display_name = "Streaming"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            pass  # Should not be called

        async def send_delta(
            self,
            chat_id: str,
            delta: str,
            metadata: dict | None = None,
            *,
            stream_id: str | None = None,
            stream_end: bool = False,
            resuming: bool = False,
        ) -> None:
            nonlocal send_delta_called
            send_delta_called = True

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"streaming": _StreamingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = outbound_message_for_event(
        channel="streaming",
        chat_id="123",
        event=StreamDeltaEvent(content="test delta"),
    )
    await mgr._send_with_retry(mgr.channels["streaming"], msg)

    assert send_delta_called is True


@pytest.mark.asyncio
async def test_send_with_retry_supports_legacy_stream_delta_signature():
    """External plugins with the old send_delta signature should keep working."""
    calls: list[tuple[str, str, dict]] = []

    class _LegacyStreamingChannel(BaseChannel):
        name = "legacy_streaming"
        display_name = "Legacy Streaming"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            pass

        async def send_delta(
            self,
            chat_id: str,
            delta: str,
            metadata: dict | None = None,
        ) -> None:
            calls.append((chat_id, delta, dict(metadata or {})))

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )
    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"legacy_streaming": _LegacyStreamingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    await mgr._send_with_retry(
        mgr.channels["legacy_streaming"],
        outbound_message_for_event(
            channel="legacy_streaming",
            chat_id="123",
            event=StreamDeltaEvent(content="hello", stream_id="s1"),
        ),
    )
    await mgr._send_with_retry(
        mgr.channels["legacy_streaming"],
        outbound_message_for_event(
            channel="legacy_streaming",
            chat_id="123",
            event=StreamEndEvent(content="", stream_id="s1", resuming=True),
        ),
    )

    assert calls == [
        ("123", "hello", {"_stream_id": "s1", "_stream_delta": True}),
        ("123", "", {"_stream_id": "s1", "_stream_end": True}),
    ]


@pytest.mark.asyncio
async def test_send_with_retry_supports_legacy_reasoning_signature():
    """External plugins with the old reasoning hook signature should keep working."""
    deltas: list[tuple[str, str, dict]] = []
    ends: list[tuple[str, dict]] = []

    class _LegacyReasoningChannel(BaseChannel):
        name = "legacy_reasoning"
        display_name = "Legacy Reasoning"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            pass

        async def send_reasoning_delta(
            self,
            chat_id: str,
            delta: str,
            metadata: dict | None = None,
        ) -> None:
            deltas.append((chat_id, delta, dict(metadata or {})))

        async def send_reasoning_end(
            self,
            chat_id: str,
            metadata: dict | None = None,
        ) -> None:
            ends.append((chat_id, dict(metadata or {})))

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )
    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"legacy_reasoning": _LegacyReasoningChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    await mgr._send_with_retry(
        mgr.channels["legacy_reasoning"],
        outbound_message_for_event(
            channel="legacy_reasoning",
            chat_id="123",
            event=ProgressEvent(content="thinking", reasoning_delta=True, stream_id="r1"),
        ),
    )
    await mgr._send_with_retry(
        mgr.channels["legacy_reasoning"],
        outbound_message_for_event(
            channel="legacy_reasoning",
            chat_id="123",
            event=ProgressEvent(reasoning_end=True, stream_id="r1"),
        ),
    )

    assert deltas == [
        ("123", "thinking", {"_reasoning_delta": True, "_stream_id": "r1"}),
    ]
    assert ends == [
        ("123", {"_reasoning_end": True, "_stream_id": "r1"}),
    ]


@pytest.mark.asyncio
async def test_send_with_retry_skips_send_when_streamed():
    """_send_with_retry should not call send for streamed response events."""
    send_called = False
    send_delta_called = False

    class _StreamedChannel(BaseChannel):
        name = "streamed"
        display_name = "Streamed"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal send_called
            send_called = True

        async def send_delta(
            self,
            chat_id: str,
            delta: str,
            metadata: dict | None = None,
            *,
            stream_id: str | None = None,
            stream_end: bool = False,
            resuming: bool = False,
        ) -> None:
            nonlocal send_delta_called
            send_delta_called = True

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"streamed": _StreamedChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = outbound_message_for_event(
        channel="streamed",
        chat_id="123",
        event=StreamedResponseEvent(),
        content="test",
    )
    await mgr._send_with_retry(mgr.channels["streamed"], msg)

    assert send_called is False
    assert send_delta_called is False


def test_outbound_duplicate_suppression_is_scoped_to_origin_message() -> None:
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {}
    mgr._dispatch_task = None
    mgr._origin_reply_fingerprints = {}

    first = OutboundMessage(
        channel="feishu",
        chat_id="chat123",
        content="Done",
        metadata={"message_id": "msg-1"},
    )
    duplicate = OutboundMessage(
        channel="feishu",
        chat_id="chat123",
        content="  Done  ",
        metadata={"origin_message_id": "msg-1"},
    )
    separate_turn = OutboundMessage(
        channel="feishu",
        chat_id="chat123",
        content="Done",
        metadata={"message_id": "msg-2"},
    )
    new_origin_content = OutboundMessage(
        channel="feishu",
        chat_id="chat123",
        content="Done with extra details",
        metadata={"origin_message_id": "msg-1"},
    )

    assert mgr._should_suppress_outbound(first) is False
    assert mgr._should_suppress_outbound(duplicate) is True
    assert mgr._should_suppress_outbound(separate_turn) is False
    assert mgr._should_suppress_outbound(new_origin_content) is False


@pytest.mark.asyncio
async def test_send_with_retry_propagates_cancelled_error():
    """_send_with_retry should re-raise CancelledError for graceful shutdown."""
    class _CancellingChannel(BaseChannel):
        name = "cancelling"
        display_name = "Cancelling"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            raise asyncio.CancelledError("simulated cancellation")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"cancelling": _CancellingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="cancelling", chat_id="123", content="test")

    with pytest.raises(asyncio.CancelledError):
        await mgr._send_with_retry(mgr.channels["cancelling"], msg)


@pytest.mark.asyncio
async def test_send_with_retry_propagates_cancelled_error_during_sleep():
    """_send_with_retry should re-raise CancelledError during sleep."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated failure")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")

    # Mock sleep to raise CancelledError
    async def cancel_during_sleep(_):
        raise asyncio.CancelledError("cancelled during sleep")

    with patch("nanobot.channels.manager.asyncio.sleep", side_effect=cancel_during_sleep):
        with pytest.raises(asyncio.CancelledError):
            await mgr._send_with_retry(mgr.channels["failing"], msg)

    # Should have attempted once before sleep was cancelled
    assert call_count == 1


# ---------------------------------------------------------------------------
# ChannelManager - lifecycle and getters
# ---------------------------------------------------------------------------

class _ChannelWithAllowFrom(BaseChannel):
    """Channel with configurable allow_from."""
    name = "withallow"
    display_name = "With Allow"

    def __init__(self, config, bus, allow_from):
        super().__init__(config, bus)
        if isinstance(self.config, dict):
            self.config["allow_from"] = allow_from
        else:
            self.config.allow_from = allow_from

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass


class _StartableChannel(BaseChannel):
    """Channel that tracks start/stop calls."""
    name = "startable"
    display_name = "Startable"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, msg: OutboundMessage) -> None:
        pass


@pytest.mark.asyncio
async def test_validate_allow_from_allows_empty_list():
    """Empty allow_from is valid now — pairing store handles unapproved senders."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.channels = {"test": _ChannelWithAllowFrom(fake_config, None, [])}
    mgr._dispatch_task = None

    # Should not raise — empty list defers to pairing store
    mgr._validate_allow_from()
    assert list(mgr.channels) == ["test"]
    assert mgr.channels["test"].config.allow_from == []


@pytest.mark.asyncio
async def test_validate_allow_from_passes_with_asterisk():
    """_validate_allow_from should not raise when allow_from contains '*'."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.channels = {"test": _ChannelWithAllowFrom(fake_config, None, ["*"])}
    mgr._dispatch_task = None

    # Should not raise
    mgr._validate_allow_from()
    assert list(mgr.channels) == ["test"]
    assert mgr.channels["test"].config.allow_from == ["*"]


@pytest.mark.asyncio
async def test_validate_allow_from_allows_empty_dict_allow_from():
    """Empty dict-backed allow_from is valid — pairing store handles approval."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.channels = {"test": _ChannelWithAllowFrom({"enabled": True}, None, [])}
    mgr._dispatch_task = None

    mgr._validate_allow_from()
    assert list(mgr.channels) == ["test"]
    assert mgr.channels["test"].config["allow_from"] == []


@pytest.mark.asyncio
async def test_validate_allow_from_allows_missing_allow_from():
    """Omitted allowFrom is valid — channel operates in pairing-only mode."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    class _NoAllowFromChannel(BaseChannel):
        name = "noallow"
        display_name = "No Allow"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            pass

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.channels = {"test": _NoAllowFromChannel({"enabled": True}, None)}
    mgr._dispatch_task = None

    # Should not raise — pairing-only mode
    mgr._validate_allow_from()
    assert list(mgr.channels) == ["test"]
    assert "allow_from" not in mgr.channels["test"].config


@pytest.mark.asyncio
async def test_get_channel_returns_channel_if_exists():
    """get_channel should return the channel if it exists."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"telegram": _StartableChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    assert mgr.get_channel("telegram") is not None
    assert mgr.get_channel("nonexistent") is None


@pytest.mark.asyncio
async def test_get_status_returns_running_state():
    """get_status should return enabled and running state for each channel."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    ch = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {"startable": ch}
    mgr._dispatch_task = None

    status = mgr.get_status()

    assert status["startable"]["enabled"] is True
    assert status["startable"]["running"] is False  # Not started yet


@pytest.mark.asyncio
async def test_enabled_channels_returns_channel_names():
    """enabled_channels should return list of enabled channel names."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {
        "telegram": _StartableChannel(fake_config, mgr.bus),
        "slack": _StartableChannel(fake_config, mgr.bus),
    }
    mgr._dispatch_task = None

    enabled = mgr.enabled_channels

    assert "telegram" in enabled
    assert "slack" in enabled
    assert len(enabled) == 2


@pytest.mark.asyncio
async def test_stop_all_cancels_dispatcher_and_stops_channels():
    """stop_all should cancel the dispatch task and stop all channels."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()

    ch = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {"startable": ch}

    # Create a real cancelled task
    async def dummy_task():
        while True:
            await asyncio.sleep(1)

    dispatch_task = asyncio.create_task(dummy_task())
    mgr._dispatch_task = dispatch_task

    await mgr.stop_all()

    # Task should be cancelled
    assert dispatch_task.cancelled()
    # Channel should be stopped
    assert ch.stopped is True


@pytest.mark.asyncio
async def test_start_channel_logs_error_on_failure():
    """_start_channel should log error when channel start fails."""
    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            raise RuntimeError("connection failed")

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            pass

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {}
    mgr._dispatch_task = None

    ch = _FailingChannel(fake_config, mgr.bus)

    # Should not raise, just log error
    await mgr._start_channel("failing", ch)
    assert mgr.channels == {}
    assert mgr._dispatch_task is None


@pytest.mark.asyncio
async def test_stop_all_handles_channel_exception():
    """stop_all should handle exceptions when stopping channels gracefully."""
    class _StopFailingChannel(BaseChannel):
        name = "stopfailing"
        display_name = "Stop Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            raise RuntimeError("stop failed")

        async def send(self, msg: OutboundMessage) -> None:
            pass

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"stopfailing": _StopFailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    # Should not raise even if channel.stop() raises
    await mgr.stop_all()
    assert list(mgr.channels) == ["stopfailing"]
    assert mgr._dispatch_task is None


@pytest.mark.asyncio
async def test_stop_all_handles_channel_stop_cancelled_task():
    """stop_all should treat a channel's already-cancelled internals as stopped."""

    class _StopCancelledChannel(BaseChannel):
        name = "stopcancelled"
        display_name = "Stop Cancelled"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            raise asyncio.CancelledError("server task cancelled")

        async def send(self, msg: OutboundMessage) -> None:
            pass

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    next_channel = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {
        "stopcancelled": _StopCancelledChannel(fake_config, mgr.bus),
        "next": next_channel,
    }
    mgr._dispatch_task = None

    await mgr.stop_all()

    assert next_channel.stopped is True


@pytest.mark.asyncio
async def test_start_all_no_channels_logs_warning():
    """start_all should log warning when no channels are enabled."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {}  # No channels
    mgr._dispatch_task = None

    # Should return early without creating dispatch task
    await mgr.start_all()

    assert mgr._dispatch_task is None


@pytest.mark.asyncio
async def test_start_all_creates_dispatch_task():
    """start_all should create the dispatch task when channels exist."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()

    ch = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {"startable": ch}
    mgr._dispatch_task = None

    # Cancel immediately after start to avoid running forever
    async def cancel_after_start():
        await asyncio.sleep(0.01)
        if mgr._dispatch_task:
            mgr._dispatch_task.cancel()

    cancel_task = asyncio.create_task(cancel_after_start())

    try:
        await mgr.start_all()
    except asyncio.CancelledError:
        pass
    finally:
        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass

    # Dispatch task should have been created
    assert mgr._dispatch_task is not None


@pytest.mark.asyncio
async def test_notify_restart_done_enqueues_outbound_message():
    """Restart notice should schedule send_with_retry for target channel."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"feishu": _StartableChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None
    mgr._send_with_retry = AsyncMock()

    notice = RestartNotice(channel="feishu", chat_id="oc_123", started_at_raw="100.0")
    with patch("nanobot.channels.manager.consume_restart_notice_from_env", return_value=notice):
        mgr._notify_restart_done_if_needed()

    await asyncio.sleep(0)
    mgr._send_with_retry.assert_awaited_once()
    sent_channel, sent_msg = mgr._send_with_retry.await_args.args
    assert sent_channel is mgr.channels["feishu"]
    assert sent_msg.channel == "feishu"
    assert sent_msg.chat_id == "oc_123"
    assert sent_msg.content.startswith("Restart completed")
