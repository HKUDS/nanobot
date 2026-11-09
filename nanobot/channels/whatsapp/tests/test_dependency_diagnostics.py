from __future__ import annotations

import builtins
import sys
import types

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.whatsapp import runtime


def _fail_import(monkeypatch, module, error):
    original = builtins.__import__

    def import_with_failure(name, *args, **kwargs):
        if name == module:
            raise error
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_with_failure)
    monkeypatch.setattr(runtime, "_NEONIZE_API", None)


@pytest.mark.parametrize(
    ("module", "error", "expected", "platform", "hint"),
    [
        (
            "magic", ModuleNotFoundError("No module named 'magic'", name="magic"),
            "python-magic", "linux", "nanobot plugins enable whatsapp",
        ),
        (
            "magic", ImportError("failed to find libmagic. Check your installation"),
            "libmagic", "darwin", "brew install libmagic",
        ),
        (
            "magic", ImportError("failed to find libmagic. Check your installation"),
            "libmagic", "linux", "apt install libmagic1",
        ),
        (
            "magic", OSError("Could not load libmagic.dll"),
            "libmagic", "win32", "python-magic-bin",
        ),
        (
            "neonize.aioze.client",
            ModuleNotFoundError("No module named 'neonize'", name="neonize"),
            "Neonize", "linux", "nanobot plugins enable whatsapp",
        ),
    ],
)
def test_dependency_failure_reports_the_actual_dependency(
    monkeypatch, module, error, expected, platform, hint,
):
    monkeypatch.setattr(runtime, "sys", types.SimpleNamespace(platform=platform))
    if module != "magic":
        magic = types.ModuleType("magic")
        magic.from_file = lambda *args, **kwargs: "text/plain"
        magic.from_buffer = lambda *args, **kwargs: "text/plain"
        monkeypatch.setitem(sys.modules, "magic", magic)
    _fail_import(monkeypatch, module, error)

    with pytest.raises(RuntimeError, match=expected) as caught:
        runtime._load_neonize()

    assert caught.value.__cause__ is error
    assert hint in str(caught.value)


def test_incompatible_magic_module_has_an_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "magic", types.ModuleType("magic"))
    monkeypatch.setattr(runtime, "_NEONIZE_API", None)

    with pytest.raises(RuntimeError, match="magic.*python-magic"):
        runtime._load_neonize()


@pytest.mark.parametrize(
    "error",
    [
        ModuleNotFoundError("No module named 'magic_dependency'", name="magic_dependency"),
        ImportError("cannot import name 'libmagic' from 'magic'"),
    ],
)
def test_unrelated_magic_import_failure_is_not_misreported(monkeypatch, error):
    _fail_import(monkeypatch, "magic", error)

    with pytest.raises(type(error)) as caught:
        runtime._load_neonize()

    assert caught.value is error


@pytest.mark.asyncio
async def test_missing_libmagic_is_visible_in_gateway_status(monkeypatch, tmp_path):
    from nanobot.channels import registry
    from nanobot.channels.manager import ChannelManager
    from nanobot.channels.whatsapp.manifest import PLUGIN
    from nanobot.config.schema import Config

    monkeypatch.setattr(registry, "discover_plugins", lambda: {"whatsapp": PLUGIN})
    monkeypatch.setattr(
        "nanobot.optional_features.ensure_enabled_channel_dependencies", lambda *_: {},
    )
    bus = MessageBus()
    config = Config.model_validate({"channels": {"whatsapp": {"enabled": True}}})
    manager = ChannelManager(config, bus, config_path=tmp_path / "config.json")
    channel = manager.channels["whatsapp"]
    _fail_import(
        monkeypatch, "magic", ImportError("failed to find libmagic. Check your installation"),
    )

    await manager._start_channel("whatsapp", channel)
    assert "libmagic" in manager.get_status()["whatsapp"]["error"]
