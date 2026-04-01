"""Unit tests for MemobaseMemoryStore (memobase adapter)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.memory.base import BaseMemoryStore


def _make_messages(count: int = 3) -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(count)
    ]


def _make_profile(pid: str = "p1", topic: str = "basic_info", sub_topic: str = "name"):
    return SimpleNamespace(
        id=pid,
        describe=f"User's {sub_topic}",
        topic=topic,
        sub_topic=sub_topic,
        content=f"User {sub_topic} is set",
    )


def _make_event(eid: str = "ev1", tip: str = "User mentioned they like cats"):
    return SimpleNamespace(
        event_id=eid,
        event_tip=tip,
        created_at="2026-03-22T10:00:00",
    )


def _mock_memobase_imports():
    """Create mock AsyncMemoBaseClient and Blob classes."""
    mock_user = AsyncMock()
    mock_user.insert = AsyncMock(return_value="blob-uuid-123")
    mock_user.search_event = AsyncMock(return_value=[_make_event()])
    mock_user.profile = AsyncMock(return_value=[_make_profile()])
    mock_user.context = AsyncMock(return_value="User is a developer who likes cats")
    mock_user.flush = AsyncMock(return_value=True)
    mock_user.update_profile = AsyncMock()
    mock_user.delete_profile = AsyncMock()

    mock_client = AsyncMock()
    mock_client.get_or_create_user = AsyncMock(return_value=mock_user)
    mock_client.close = AsyncMock()

    mock_client_cls = MagicMock(return_value=mock_client)
    mock_blob_cls = MagicMock()

    return mock_client_cls, mock_blob_cls, mock_client, mock_user


@pytest.fixture
def memobase_store(tmp_path: Path):
    """Create a MemobaseMemoryStore with fully mocked memobase SDK."""
    mock_client_cls, mock_blob_cls, mock_client, mock_user = _mock_memobase_imports()

    with patch(
        "nanobot.agent.memory.memobase_store._lazy_import_memobase",
        return_value=(mock_client_cls, mock_blob_cls),
    ):
        from nanobot.agent.memory.memobase_store import MemobaseMemoryStore

        store = MemobaseMemoryStore(
            tmp_path,
            project_url="http://mock:8019",
            api_key="test-secret",
            max_token_size=300,
        )

    store._client = mock_client
    store._mock_client = mock_client
    store._mock_user = mock_user
    return store


# ── Init ──────────────────────────────────────────────────────────────────────


class TestMemobaseStoreInit:

    def test_is_subclass_of_base(self, memobase_store):
        assert isinstance(memobase_store, BaseMemoryStore)

    def test_import_error_without_library(self):
        from nanobot.agent.memory.memobase_store import _lazy_import_memobase

        with patch.dict("sys.modules", {"memobase": None, "memobase.core": None, "memobase.core.async_entry": None}):
            with pytest.raises(ImportError, match="memobase"):
                _lazy_import_memobase()

    def test_dedicated_loop_is_running(self, memobase_store):
        assert memobase_store._dedicated_loop.is_running()
        assert memobase_store._dedicated_thread.is_alive()

    def test_stores_config(self, tmp_path: Path):
        mock_client_cls, mock_blob_cls, _, _ = _mock_memobase_imports()
        with patch(
            "nanobot.agent.memory.memobase_store._lazy_import_memobase",
            return_value=(mock_client_cls, mock_blob_cls),
        ):
            from nanobot.agent.memory.memobase_store import MemobaseMemoryStore

            store = MemobaseMemoryStore(
                tmp_path,
                project_url="http://custom:9000",
                api_key="my-key",
                max_token_size=1024,
            )
        assert store._project_url == "http://custom:9000"
        assert store._api_key == "my-key"
        assert store._max_token_size == 1024


# ── UUID helper ───────────────────────────────────────────────────────────────


class TestToUuid:

    def test_deterministic(self):
        from nanobot.agent.memory.memobase_store import _to_uuid

        a = _to_uuid("alice")
        b = _to_uuid("alice")
        assert a == b

    def test_different_ids_different_uuids(self):
        from nanobot.agent.memory.memobase_store import _to_uuid

        assert _to_uuid("alice") != _to_uuid("bob")

    def test_is_valid_uuid_format(self):
        import uuid as uuid_mod

        from nanobot.agent.memory.memobase_store import _to_uuid

        result = _to_uuid("test_user")
        parsed = uuid_mod.UUID(result)
        assert str(parsed) == result


# ── CRUD ──────────────────────────────────────────────────────────────────────


class TestMemobaseStoreCRUD:

    @pytest.mark.asyncio
    async def test_add_inserts_chat_blob(self, memobase_store):
        with patch("nanobot.agent.memory.memobase_store._lazy_import_memobase") as mock_import:
            mock_import.return_value = (MagicMock(), MagicMock())
            with patch("memobase.core.blob.ChatBlob", create=True) as mock_chat_blob:
                mock_chat_blob.return_value = MagicMock()
                result = await memobase_store.add(_make_messages(2), user_id="alice")
        assert "blob_id" in result
        memobase_store._mock_user.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_filters_tool_messages(self, memobase_store):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": "tool result"},
            {"role": "assistant", "content": "response"},
        ]
        with patch("nanobot.agent.memory.memobase_store._lazy_import_memobase") as mock_import:
            mock_import.return_value = (MagicMock(), MagicMock())
            with patch("memobase.core.blob.ChatBlob", create=True):
                await memobase_store.add(messages, user_id="alice")
        memobase_store._mock_user.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_empty_valid_returns_empty_dict(self, memobase_store):
        messages = [
            {"role": "tool", "content": "only tool messages"},
            {"role": "user", "content": ""},
        ]
        with patch("nanobot.agent.memory.memobase_store._lazy_import_memobase") as mock_import:
            mock_import.return_value = (MagicMock(), MagicMock())
            result = await memobase_store.add(messages, user_id="alice")
        assert result == {}

    @pytest.mark.asyncio
    async def test_add_filters_non_string_content(self, memobase_store):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "multimodal"}]},
            {"role": "user", "content": "plain text"},
        ]
        with patch("nanobot.agent.memory.memobase_store._lazy_import_memobase") as mock_import:
            mock_import.return_value = (MagicMock(), MagicMock())
            with patch("memobase.core.blob.ChatBlob", create=True):
                await memobase_store.add(messages, user_id="alice")
        memobase_store._mock_user.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_returns_events(self, memobase_store):
        results = await memobase_store.search("cats", user_id="alice", limit=3)
        assert len(results) == 1
        assert results[0]["memory"] == "User mentioned they like cats"
        assert results[0]["id"] == "ev1"

    @pytest.mark.asyncio
    async def test_search_failure_returns_empty_list(self, memobase_store):
        memobase_store._mock_user.search_event = AsyncMock(side_effect=RuntimeError("fail"))
        results = await memobase_store.search("query")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_all_returns_profiles(self, memobase_store):
        results = await memobase_store.get_all(user_id="bob")
        assert len(results) == 1
        assert results[0]["topic"] == "basic_info"
        assert "memory" in results[0]

    @pytest.mark.asyncio
    async def test_get_all_failure_returns_empty(self, memobase_store):
        memobase_store._mock_user.profile = AsyncMock(side_effect=RuntimeError("fail"))
        results = await memobase_store.get_all()
        assert results == []

    @pytest.mark.asyncio
    async def test_update_success(self, memobase_store):
        result = await memobase_store.update("p1", "updated content", user_id="alice")
        assert result is True
        memobase_store._mock_user.update_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_failure_returns_false(self, memobase_store):
        memobase_store._mock_user.update_profile = AsyncMock(
            side_effect=RuntimeError("DB error")
        )
        result = await memobase_store.update("p1", "fail", user_id="alice")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_success(self, memobase_store):
        result = await memobase_store.delete("p1", user_id="alice")
        assert result is True
        memobase_store._mock_user.delete_profile.assert_called_once_with("p1")

    @pytest.mark.asyncio
    async def test_delete_failure_returns_false(self, memobase_store):
        memobase_store._mock_user.delete_profile = AsyncMock(
            side_effect=RuntimeError("not found")
        )
        result = await memobase_store.delete("p1", user_id="alice")
        assert result is False


# ── Memory context ────────────────────────────────────────────────────────────


class TestMemobaseStoreContext:

    def test_get_memory_context_returns_profile_text(self, memobase_store):
        ctx = memobase_store.get_memory_context(user_id="alice")
        assert "developer" in ctx
        assert "cats" in ctx

    def test_get_memory_context_empty(self, memobase_store):
        memobase_store._mock_user.context = AsyncMock(return_value="")
        assert memobase_store.get_memory_context() == ""

    def test_get_memory_context_exception_returns_empty(self, memobase_store):
        memobase_store._mock_user.context = AsyncMock(side_effect=RuntimeError("fail"))
        assert memobase_store.get_memory_context() == ""

    def test_get_memory_context_respects_max_token_size(self, memobase_store):
        memobase_store.get_memory_context(user_id="alice", max_token_size=2048)
        memobase_store._mock_user.context.assert_called_with(max_token_size=2048)


# ── Consolidation ─────────────────────────────────────────────────────────────


class TestMemobaseStoreConsolidation:

    @pytest.mark.asyncio
    async def test_consolidate_empty_returns_true(self, memobase_store):
        provider = AsyncMock()
        result = await memobase_store.consolidate([], provider, "model")
        assert result is True

    @pytest.mark.asyncio
    async def test_consolidate_delegates_to_add(self, memobase_store):
        provider = AsyncMock()
        messages = _make_messages(3)
        with patch("nanobot.agent.memory.memobase_store._lazy_import_memobase") as mock_import:
            mock_import.return_value = (MagicMock(), MagicMock())
            with patch("memobase.core.blob.ChatBlob", create=True):
                result = await memobase_store.consolidate(
                    messages, provider, "model", user_id="alice"
                )
        assert result is True
        assert memobase_store._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_consolidate_failure_increments_counter(self, memobase_store):
        provider = AsyncMock()
        memobase_store._mock_user.insert = AsyncMock(side_effect=RuntimeError("fail"))
        with patch("nanobot.agent.memory.memobase_store._lazy_import_memobase") as mock_import:
            mock_import.return_value = (MagicMock(), MagicMock())
            with patch("memobase.core.blob.ChatBlob", create=True):
                result = await memobase_store.consolidate(
                    _make_messages(), provider, "m"
                )
        assert result is False
        assert memobase_store._consecutive_failures == 1


# ── Flush / Close ─────────────────────────────────────────────────────────────


class TestMemobaseStoreLifecycle:

    @pytest.mark.asyncio
    async def test_flush_calls_user_flush(self, memobase_store):
        result = await memobase_store.flush(user_id="alice", sync=True)
        assert result is True
        memobase_store._mock_user.flush.assert_called_once_with(sync=True)

    @pytest.mark.asyncio
    async def test_flush_failure_returns_false(self, memobase_store):
        memobase_store._mock_user.flush = AsyncMock(side_effect=RuntimeError("fail"))
        result = await memobase_store.flush()
        assert result is False

    @pytest.mark.asyncio
    async def test_close_stops_loop(self, memobase_store):
        await memobase_store.close()
        memobase_store._mock_client.close.assert_called_once()


# ── User caching ──────────────────────────────────────────────────────────────


class TestMemobaseStoreUserCaching:

    @pytest.mark.asyncio
    async def test_user_cached_after_first_retrieval(self, memobase_store):
        await memobase_store.search("test", user_id="alice")
        await memobase_store.search("test2", user_id="alice")
        memobase_store._mock_client.get_or_create_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_users_create_separate_handles(self, memobase_store):
        await memobase_store.search("test", user_id="alice")
        await memobase_store.search("test", user_id="bob")
        assert memobase_store._mock_client.get_or_create_user.call_count == 2
