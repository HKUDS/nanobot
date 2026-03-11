from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.memory.mem0_adapter import _Mem0Adapter


class _RowsClient:
    def __init__(self, responses: list[object]):
        self._responses = responses

    def get_all(self, *args, **kwargs):
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _DeleteClient:
    def __init__(self, behavior: str):
        self.behavior = behavior

    def delete_all(self, *args, **kwargs):
        if self.behavior == "ok":
            return None
        if self.behavior == "typeerror":
            if kwargs:
                raise TypeError("kw not supported")
            return None
        raise RuntimeError("boom")


class _UpdateClient:
    def __init__(self, mode: str):
        self.mode = mode
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def update(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.mode == "ok":
            return None
        if self.mode == "typeerror":
            if "data" in kwargs:
                return None
            raise TypeError("signature mismatch")
        raise RuntimeError("update failed")


class _DeleteOneClient:
    def __init__(self, should_raise: bool = False):
        self.should_raise = should_raise
        self.calls: list[str] = []

    def delete(self, memory_id: str):
        self.calls.append(memory_id)
        if self.should_raise:
            raise RuntimeError("delete failed")


class _AddClient:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def add(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if "infer" in kwargs and kwargs["infer"] is True:
            raise RuntimeError("invalid api key")
        return {"ok": True}


class _SearchClient:
    def __init__(self, first_error: bool = False):
        self.first_error = first_error
        self.calls = 0

    def search(self, *args, **kwargs):
        self.calls += 1
        if self.first_error and self.calls == 1:
            raise RuntimeError("vector failed")
        return {"results": [{"id": "m1", "memory": "oauth2 auth", "score": 0.9, "metadata": {}}]}


class _AddModeClient:
    def __init__(self, outcomes: list[object]):
        self.outcomes = list(outcomes)

    def add(self, messages, **kwargs):
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _TypeErrorSearchClient:
    def __init__(self, fail_positional: bool = False):
        self.fail_positional = fail_positional

    def search(self, *args, **kwargs):
        if "query" in kwargs:
            raise TypeError("kw signature")
        if self.fail_positional:
            raise RuntimeError("positional failed")
        return {"results": [{"id": "s1", "memory": "oauth2 rollout", "score": 0.7, "metadata": {}}]}



def _adapter() -> _Mem0Adapter:
    adapter = object.__new__(_Mem0Adapter)
    adapter.workspace = Path(".")
    adapter.user_id = "nanobot"
    adapter.enabled = True
    adapter.client = None
    adapter.mode = "oss"
    adapter.error = None
    adapter._local_fallback_attempted = False
    adapter._local_mem0_dir = None
    adapter._fallback_enabled = True
    adapter._fallback_candidates = [("huggingface", {"model": "m"}, 384)]
    adapter.last_add_mode = "unknown"
    adapter._infer_true_disabled = False
    adapter._infer_true_disable_reason = ""
    adapter._add_debug = False
    adapter._verify_write = True
    adapter._force_infer_true = False
    return adapter


def test_load_fallback_config_and_parse_dotenv_line() -> None:
    adapter = _adapter()
    fallback = adapter._load_fallback_config(
        {
            "fallback": {
                "enabled": False,
                "providers": [
                    {"provider": "hf", "config": {"model": "x"}, "embedding_model_dims": "256"},
                    {"provider": "", "config": {}},
                ],
            }
        }
    )

    assert isinstance(fallback, dict)
    assert adapter._fallback_enabled is False
    assert adapter._fallback_candidates == [("hf", {"model": "x"}, 256)]

    assert adapter._parse_dotenv_line("A_KEY= value ") == ("A_KEY", "value")
    assert adapter._parse_dotenv_line("B='quoted'") == ("B", "quoted")
    assert adapter._parse_dotenv_line("1NOPE=x") is None
    assert adapter._parse_dotenv_line("#comment") is None


def test_load_api_keys_from_config_sets_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = _adapter()
    home = tmp_path / "home"
    cfg_dir = home / ".nanobot"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        '{"providers": {"openai": {"api_key": "k1"}, "anthropic": {"apiKey": "k2"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    adapter._load_api_keys_from_config()

    assert os.getenv("OPENAI_API_KEY") == "k1"
    assert os.getenv("ANTHROPIC_API_KEY") == "k2"


def test_get_all_count_typeerror_and_exception_paths() -> None:
    adapter = _adapter()
    adapter.client = _RowsClient([TypeError("kw"), {"results": [{"id": "1"}, {"id": "2"}]}])
    assert adapter.get_all_count(limit=2) == 2

    adapter.client = _RowsClient([RuntimeError("boom")])
    assert adapter.get_all_count(limit=2) == 0


def test_flush_vector_store_and_delete_all_user_memories() -> None:
    adapter = _adapter()
    closed = {"ok": False}

    class _Closer:
        def close(self):
            closed["ok"] = True

    adapter.client = SimpleNamespace(vector_store=SimpleNamespace(client=_Closer()))
    assert adapter.flush_vector_store() is True
    assert closed["ok"] is True

    adapter.enabled = False
    assert adapter.delete_all_user_memories() == (False, "mem0_disabled", 0)

    adapter.enabled = True
    adapter.get_all_count = lambda limit=200: 5
    adapter.client = _DeleteClient("ok")
    ok, reason, count = adapter.delete_all_user_memories()
    assert (ok, reason, count) == (True, "delete_all_user_id", 5)

    adapter.client = _DeleteClient("typeerror")
    ok2, reason2, count2 = adapter.delete_all_user_memories()
    assert (ok2, reason2, count2) == (True, "delete_all_positional_user_id", 5)


def test_add_text_disables_infer_true_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter()
    adapter.mode = "hosted"
    adapter.client = _AddClient()
    adapter._verify_write = False

    assert adapter.add_text("hello", metadata={"topic": "x"}) is True
    assert adapter._infer_true_disabled is True
    assert adapter.last_add_mode in {"default_signature", "infer_false_fallback"}


def test_search_handles_disabled_and_local_fallback() -> None:
    adapter = _adapter()
    adapter.enabled = False
    rows, stats = adapter.search("hi", return_stats=True)
    assert rows == []
    assert stats["source_vector"] == 0

    adapter.enabled = True
    adapter.client = _SearchClient(first_error=True)

    fallback_client = _SearchClient(first_error=False)

    def _activate_local_fallback(*, reason: str) -> bool:
        adapter.client = fallback_client
        return True

    adapter._activate_local_fallback = _activate_local_fallback  # type: ignore[method-assign]
    out = adapter.search("oauth2", top_k=1)
    assert len(out) == 1
    assert out[0]["summary"] == "oauth2 auth"


def test_update_and_delete_fallback_paths() -> None:
    adapter = _adapter()

    adapter.mode = "hosted"
    up = _UpdateClient("ok")
    adapter.client = up
    assert adapter.update("m1", "new", metadata={"x": 1}) is True
    assert up.calls[0][1]["metadata"] == {"x": 1}

    adapter.mode = "oss"
    up2 = _UpdateClient("typeerror")
    adapter.client = up2
    assert adapter.update("m1", "new") is True

    up3 = _UpdateClient("error")
    adapter.client = up3

    replacement = _UpdateClient("ok")

    def _activate_local_fallback(*, reason: str) -> bool:
        adapter.client = replacement
        return True

    adapter._activate_local_fallback = _activate_local_fallback  # type: ignore[method-assign]
    assert adapter.update("m1", "new") is True

    dclient = _DeleteOneClient(should_raise=True)
    adapter.client = dclient

    replacement_delete = _DeleteOneClient(should_raise=False)

    def _activate_for_delete(*, reason: str) -> bool:
        adapter.client = replacement_delete
        return True

    adapter._activate_local_fallback = _activate_for_delete  # type: ignore[method-assign]
    assert adapter.delete("m1") is True


def test_add_text_non_hosted_paths_and_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter()
    adapter.mode = "oss"
    adapter.get_all_count = lambda limit=200: 0  # type: ignore[method-assign]
    adapter._verify_write = False
    adapter._force_infer_true = True

    # infer_false_primary fails -> infer_true_forced succeeds
    adapter.client = _AddModeClient([RuntimeError("x"), {"ok": True}])
    assert adapter.add_text("hello") is True
    assert adapter.last_add_mode == "default_signature"

    # All primary attempts fail -> local fallback succeeds.
    adapter.client = _AddModeClient([RuntimeError("x"), RuntimeError("y"), RuntimeError("z")])

    def _activate_local_fallback(*, reason: str) -> bool:
        adapter.client = _AddModeClient([{"ok": True}])
        return True

    adapter._activate_local_fallback = _activate_local_fallback  # type: ignore[method-assign]
    assert adapter.add_text("hello") is True
    assert "local_fallback" in adapter.last_add_mode


def test_search_typeerror_paths_and_stats() -> None:
    adapter = _adapter()
    adapter.client = _TypeErrorSearchClient(fail_positional=False)
    rows, stats = adapter.search("oauth2", top_k=2, return_stats=True)
    assert rows
    assert stats["source_vector"] >= 1

    adapter.client = _TypeErrorSearchClient(fail_positional=True)
    rows2, stats2 = adapter.search("oauth2", top_k=2, return_stats=True)
    assert rows2 == []
    assert stats2["source_vector"] == 0


def test_update_delete_false_guards_and_search_no_query() -> None:
    adapter = _adapter()
    assert adapter.search("", return_stats=False) == []
    assert adapter.update("", "text") is False
    assert adapter.update("id", "") is False
    assert adapter.delete("") is False
