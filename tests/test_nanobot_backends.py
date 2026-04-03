import json
import pytest
from pathlib import Path
from nanobot.nanobot import Nanobot


def _write_config(tmp_path: Path, extra: dict = None) -> Path:
    cfg = {
        "agents": {"defaults": {"model": "openai/gpt-4o"}},
        "providers": {"openai": {"apiKey": "test-key"}},
    }
    if extra:
        cfg["agents"]["defaults"].update(extra)
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(cfg))
    return config_file


def test_from_config_passes_session_backend(tmp_path, monkeypatch):
    config_file = _write_config(tmp_path, {"sessionBackend": "normal"})

    captured = {}

    original_init = __import__("nanobot.agent.loop", fromlist=["AgentLoop"]).AgentLoop.__init__

    def patched_init(self, *args, **kwargs):
        captured["session_backend"] = kwargs.get("session_backend", "normal")
        original_init(self, *args, **kwargs)

    monkeypatch.setattr("nanobot.agent.loop.AgentLoop.__init__", patched_init)
    Nanobot.from_config(config_file, workspace=tmp_path)

    assert captured["session_backend"] == "normal"


def test_from_config_passes_memory_backend(tmp_path, monkeypatch):
    config_file = _write_config(tmp_path, {"memoryBackend": "normal"})

    captured = {}

    original_init = __import__("nanobot.agent.loop", fromlist=["AgentLoop"]).AgentLoop.__init__

    def patched_init(self, *args, **kwargs):
        captured["memory_backend"] = kwargs.get("memory_backend", "normal")
        original_init(self, *args, **kwargs)

    monkeypatch.setattr("nanobot.agent.loop.AgentLoop.__init__", patched_init)
    Nanobot.from_config(config_file, workspace=tmp_path)

    assert captured["memory_backend"] == "normal"
