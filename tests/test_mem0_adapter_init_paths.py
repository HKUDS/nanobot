from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.memory.mem0_adapter import _Mem0Adapter


class _FakeMem0:
    calls: list[dict] = []
    should_fail = False

    @classmethod
    def from_config(cls, payload):
        cls.calls.append(payload)
        if cls.should_fail:
            raise RuntimeError("mem0 init failed")
        return SimpleNamespace(
            add=lambda *a, **k: None,
            search=lambda *a, **k: {"results": []},
            get_all=lambda *a, **k: {"results": []},
        )


class _FakeHostedClient:
    should_fail = False

    def __init__(self, **kwargs):
        if _FakeHostedClient.should_fail:
            raise RuntimeError("hosted init failed")


class _FakeMem0Runtime:
    calls: list[dict] = []

    @classmethod
    def from_config(cls, payload):
        cls.calls.append(payload)
        return SimpleNamespace()


def _base_adapter(tmp_path: Path) -> _Mem0Adapter:
    a = object.__new__(_Mem0Adapter)
    a.workspace = tmp_path
    a.user_id = "nanobot"
    a.enabled = False
    a.client = None
    a.mode = "disabled"
    a.error = None
    a._local_fallback_attempted = False
    a._local_mem0_dir = None
    a._fallback_enabled = True
    a._fallback_candidates = [("huggingface", {"model": "m"}, 384)]
    a.last_add_mode = "unknown"
    a._infer_true_disabled = False
    a._infer_true_disable_reason = ""
    a._add_debug = False
    a._verify_write = True
    a._force_infer_true = False
    return a


def test_load_env_candidates_reads_dotenv_and_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = _base_adapter(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=dotenv-key\nINVALID LINE\n", encoding="utf-8")

    home = tmp_path / "home"
    (home / ".nanobot").mkdir(parents=True)
    (home / ".nanobot" / "config.json").write_text(
        json.dumps({"providers": {"anthropic": {"apiKey": "cfg-anth"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    adapter._load_env_candidates()

    assert "OPENAI_API_KEY" in __import__("os").environ
    assert __import__("os").environ["ANTHROPIC_API_KEY"] == "cfg-anth"


def test_activate_local_fallback_and_reopen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = _base_adapter(tmp_path)
    monkeypatch.setattr("nanobot.agent.memory.mem0_adapter.Mem0Memory", _FakeMem0)

    ok = adapter._activate_local_fallback(reason="test")
    assert ok is True
    assert adapter.enabled is True
    assert adapter.mode.startswith("oss-local-fallback")

    called = {"n": 0}

    def _init_client():
        called["n"] += 1

    adapter._init_client = _init_client  # type: ignore[method-assign]
    adapter.reopen_client()
    assert called["n"] == 1


def test_activate_local_fallback_respects_guards(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = _base_adapter(tmp_path)
    adapter._local_fallback_attempted = True
    monkeypatch.setattr("nanobot.agent.memory.mem0_adapter.Mem0Memory", _FakeMem0)
    assert adapter._activate_local_fallback(reason="x") is False

    adapter2 = _base_adapter(tmp_path)
    adapter2._fallback_enabled = False
    assert adapter2._activate_local_fallback(reason="x") is False

    adapter3 = _base_adapter(tmp_path)
    adapter3.mode = "hosted"
    assert adapter3._activate_local_fallback(reason="x") is False


def test_init_client_real_hosted_and_oss_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Stop the global conftest no-op patch so we can execute real _init_client.
    import conftest as conftest_mod

    conftest_mod._patcher.stop()
    try:
        monkeypatch.setattr("nanobot.agent.memory.mem0_adapter.Mem0MemoryClient", _FakeHostedClient)
        monkeypatch.setattr("nanobot.agent.memory.mem0_adapter.Mem0Memory", _FakeMem0Runtime)

        # Hosted mode path (MEM0_API_KEY present).
        hosted = _base_adapter(tmp_path / "hosted")
        hosted.workspace.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("MEM0_API_KEY", "k")
        hosted._init_client()
        assert hosted.enabled is True
        assert hosted.mode == "hosted"

        # OSS path from explicit config payload.
        monkeypatch.delenv("MEM0_API_KEY", raising=False)
        ws = tmp_path / "oss"
        (ws / "memory").mkdir(parents=True, exist_ok=True)
        (ws / "memory" / "mem0_config.json").write_text(
            json.dumps(
                {
                    "vector_store": {
                        "provider": "qdrant",
                        "config": {"path": "./data"},
                    },
                    "fallback": {"enabled": True},
                }
            ),
            encoding="utf-8",
        )
        oss = _base_adapter(ws)
        oss._init_client()
        assert oss.enabled is True
        assert oss.mode == "oss"
        assert _FakeMem0Runtime.calls
        last_payload = _FakeMem0Runtime.calls[-1]
        assert last_payload["vector_store"]["config"]["on_disk"] is True
        assert os.environ.get("MEM0_DIR")
    finally:
        conftest_mod._patcher.start()
