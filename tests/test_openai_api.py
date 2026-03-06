"""Tests for the OpenAI-compatible API server."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.api.server import _SessionLocks, _chat_completion_response, _error_json, create_app

# ---------------------------------------------------------------------------
# aiohttp test client helper
# ---------------------------------------------------------------------------

try:
    from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
    from aiohttp import web

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

pytest_plugins = ("pytest_asyncio",)

# ---------------------------------------------------------------------------
# Unit tests — no aiohttp required
# ---------------------------------------------------------------------------


class TestSessionLocks:
    def test_acquire_creates_lock(self):
        sl = _SessionLocks()
        lock = sl.acquire("k1")
        assert isinstance(lock, asyncio.Lock)

    def test_same_key_returns_same_lock(self):
        sl = _SessionLocks()
        l1 = sl.acquire("k1")
        l2 = sl.acquire("k1")
        assert l1 is l2

    def test_different_keys_different_locks(self):
        sl = _SessionLocks()
        l1 = sl.acquire("k1")
        l2 = sl.acquire("k2")
        assert l1 is not l2

    def test_release_cleans_up(self):
        sl = _SessionLocks()
        sl.acquire("k1")
        sl.release("k1")
        assert "k1" not in sl._locks

    def test_release_keeps_lock_if_still_referenced(self):
        sl = _SessionLocks()
        sl.acquire("k1")
        sl.acquire("k1")
        sl.release("k1")
        assert "k1" in sl._locks
        sl.release("k1")
        assert "k1" not in sl._locks


class TestResponseHelpers:
    def test_error_json(self):
        resp = _error_json(400, "bad request")
        assert resp.status == 400
        body = json.loads(resp.body)
        assert body["error"]["message"] == "bad request"
        assert body["error"]["code"] == 400

    def test_chat_completion_response(self):
        result = _chat_completion_response("hello world", "test-model")
        assert result["object"] == "chat.completion"
        assert result["model"] == "test-model"
        assert result["choices"][0]["message"]["content"] == "hello world"
        assert result["choices"][0]["finish_reason"] == "stop"
        assert result["id"].startswith("chatcmpl-")


# ---------------------------------------------------------------------------
# Integration tests — require aiohttp
# ---------------------------------------------------------------------------


def _make_mock_agent(response_text: str = "mock response") -> MagicMock:
    agent = MagicMock()
    agent.process_direct = AsyncMock(return_value=response_text)
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()
    return agent


@pytest.fixture
def mock_agent():
    return _make_mock_agent()


@pytest.fixture
def app(mock_agent):
    return create_app(mock_agent, model_name="test-model", request_timeout=10.0)


@pytest.fixture
def cli(event_loop, aiohttp_client, app):
    return event_loop.run_until_complete(aiohttp_client(app))


# ---- Missing header tests ----


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_missing_session_key_returns_400(aiohttp_client, app):
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status == 400
    body = await resp.json()
    assert "x-session-key" in body["error"]["message"]


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_empty_session_key_returns_400(aiohttp_client, app):
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"x-session-key": "   "},
    )
    assert resp.status == 400


# ---- Missing messages tests ----


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_missing_messages_returns_400(aiohttp_client, app):
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "test"},
        headers={"x-session-key": "test-key"},
    )
    assert resp.status == 400


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_no_user_message_returns_400(aiohttp_client, app):
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "system", "content": "you are a bot"}]},
        headers={"x-session-key": "test-key"},
    )
    assert resp.status == 400


# ---- Stream not supported ----


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_stream_true_returns_400(aiohttp_client, app):
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
        headers={"x-session-key": "test-key"},
    )
    assert resp.status == 400
    body = await resp.json()
    assert "stream" in body["error"]["message"].lower()


# ---- Successful request ----


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_successful_request(aiohttp_client, mock_agent):
    app = create_app(mock_agent, model_name="test-model")
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"x-session-key": "wx:dm:user1"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["choices"][0]["message"]["content"] == "mock response"
    assert body["model"] == "test-model"
    mock_agent.process_direct.assert_called_once_with(
        content="hello",
        session_key="wx:dm:user1",
        channel="api",
        chat_id="wx:dm:user1",
        isolate_memory=True,
        disabled_tools={"read_file", "write_file", "edit_file", "list_dir", "exec"},
    )


# ---- Session isolation ----


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_session_isolation_different_keys(aiohttp_client):
    """Two different session keys must route to separate session_key arguments."""
    call_log: list[str] = []

    async def fake_process(content, session_key="", channel="", chat_id="",
                           isolate_memory=False, disabled_tools=None):
        call_log.append(session_key)
        return f"reply to {session_key}"

    agent = MagicMock()
    agent.process_direct = fake_process
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)

    r1 = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "msg1"}]},
        headers={"x-session-key": "wx:dm:alice"},
    )
    r2 = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "msg2"}]},
        headers={"x-session-key": "wx:group:g1:user:bob"},
    )

    assert r1.status == 200
    assert r2.status == 200

    b1 = await r1.json()
    b2 = await r2.json()
    assert b1["choices"][0]["message"]["content"] == "reply to wx:dm:alice"
    assert b2["choices"][0]["message"]["content"] == "reply to wx:group:g1:user:bob"
    assert call_log == ["wx:dm:alice", "wx:group:g1:user:bob"]


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_same_session_key_serialized(aiohttp_client):
    """Concurrent requests with the same session key must run serially."""
    order: list[str] = []
    barrier = asyncio.Event()

    async def slow_process(content, session_key="", channel="", chat_id="",
                           isolate_memory=False, disabled_tools=None):
        order.append(f"start:{content}")
        if content == "first":
            barrier.set()
            await asyncio.sleep(0.1)  # hold lock
        else:
            await barrier.wait()  # ensure "second" starts after "first" begins
        order.append(f"end:{content}")
        return content

    agent = MagicMock()
    agent.process_direct = slow_process
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)

    async def send(msg):
        return await client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": msg}]},
            headers={"x-session-key": "same-key"},
        )

    r1, r2 = await asyncio.gather(send("first"), send("second"))
    assert r1.status == 200
    assert r2.status == 200
    # "first" must fully complete before "second" starts
    assert order.index("end:first") < order.index("start:second")


# ---- /v1/models ----


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_models_endpoint(aiohttp_client, app):
    client = await aiohttp_client(app)
    resp = await client.get("/v1/models")
    assert resp.status == 200
    body = await resp.json()
    assert body["object"] == "list"
    assert len(body["data"]) >= 1
    assert body["data"][0]["id"] == "test-model"


# ---- /health ----


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_health_endpoint(aiohttp_client, app):
    client = await aiohttp_client(app)
    resp = await client.get("/health")
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"


# ---- Multimodal content array ----


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_multimodal_content_extracts_text(aiohttp_client, mock_agent):
    app = create_app(mock_agent, model_name="m")
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                    ],
                }
            ]
        },
        headers={"x-session-key": "test"},
    )
    assert resp.status == 200
    mock_agent.process_direct.assert_called_once()
    call_kwargs = mock_agent.process_direct.call_args
    assert call_kwargs.kwargs["content"] == "describe this"


# ---------------------------------------------------------------------------
# Memory isolation regression tests (root cause of cross-session leakage)
# ---------------------------------------------------------------------------


class TestMemoryIsolation:
    """Verify that per-session-key memory prevents cross-session context leakage.

    Root cause: ContextBuilder.build_system_prompt() reads a SHARED
    workspace/memory/MEMORY.md into the system prompt of ALL users.
    If user_1 writes "my name is Alice" and the agent persists it to
    MEMORY.md, user_2/user_N will see it.

    Fix: API mode passes a per-session MemoryStore so each session reads/
    writes its own MEMORY.md.
    """

    def test_context_builder_uses_override_memory(self, tmp_path):
        """build_system_prompt with memory_store= must use the override, not global."""
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.memory import MemoryStore

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "memory").mkdir()
        (workspace / "memory" / "MEMORY.md").write_text("Global: I am shared context")

        ctx = ContextBuilder(workspace)

        # Without override → sees global memory
        prompt_global = ctx.build_system_prompt()
        assert "I am shared context" in prompt_global

        # With override → sees only the override's memory
        override_dir = tmp_path / "isolated" / "memory"
        override_dir.mkdir(parents=True)
        (override_dir / "MEMORY.md").write_text("User Alice's private note")

        override_store = MemoryStore.__new__(MemoryStore)
        override_store.memory_dir = override_dir
        override_store.memory_file = override_dir / "MEMORY.md"
        override_store.history_file = override_dir / "HISTORY.md"

        prompt_isolated = ctx.build_system_prompt(memory_store=override_store)
        assert "User Alice's private note" in prompt_isolated
        assert "I am shared context" not in prompt_isolated

    def test_different_session_keys_get_different_memory_dirs(self, tmp_path):
        """_isolated_memory_store must return distinct paths for distinct keys."""
        from unittest.mock import MagicMock
        from nanobot.agent.loop import AgentLoop

        agent = MagicMock(spec=AgentLoop)
        agent.workspace = tmp_path
        agent._isolated_memory_store = AgentLoop._isolated_memory_store.__get__(agent)

        store_a = agent._isolated_memory_store("wx:dm:alice")
        store_b = agent._isolated_memory_store("wx:dm:bob")

        assert store_a.memory_file != store_b.memory_file
        assert store_a.memory_dir != store_b.memory_dir
        assert store_a.memory_file.parent.exists()
        assert store_b.memory_file.parent.exists()

    def test_isolated_memory_does_not_leak_across_sessions(self, tmp_path):
        """End-to-end: writing to one session's memory must not appear in another's."""
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.memory import MemoryStore

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "memory").mkdir()
        (workspace / "memory" / "MEMORY.md").write_text("")

        ctx = ContextBuilder(workspace)

        # Simulate two isolated memory stores (as the API server would create)
        def make_store(name):
            d = tmp_path / "sessions" / name / "memory"
            d.mkdir(parents=True)
            s = MemoryStore.__new__(MemoryStore)
            s.memory_dir = d
            s.memory_file = d / "MEMORY.md"
            s.history_file = d / "HISTORY.md"
            return s

        store_alice = make_store("wx_dm_alice")
        store_bob = make_store("wx_dm_bob")

        # Use unique markers that won't appear in builtin skills/prompts
        alice_marker = "XYZZY_ALICE_PRIVATE_MARKER_42"
        store_alice.write_long_term(alice_marker)

        # Alice's prompt sees it
        prompt_alice = ctx.build_system_prompt(memory_store=store_alice)
        assert alice_marker in prompt_alice

        # Bob's prompt must NOT see it
        prompt_bob = ctx.build_system_prompt(memory_store=store_bob)
        assert alice_marker not in prompt_bob

        # Global prompt must NOT see it either
        prompt_global = ctx.build_system_prompt()
        assert alice_marker not in prompt_global

    def test_build_messages_passes_memory_store(self, tmp_path):
        """build_messages must forward memory_store to build_system_prompt."""
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.memory import MemoryStore

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "memory").mkdir()
        (workspace / "memory" / "MEMORY.md").write_text("GLOBAL_SECRET")

        ctx = ContextBuilder(workspace)

        override_dir = tmp_path / "per_session" / "memory"
        override_dir.mkdir(parents=True)
        (override_dir / "MEMORY.md").write_text("SESSION_PRIVATE")

        override_store = MemoryStore.__new__(MemoryStore)
        override_store.memory_dir = override_dir
        override_store.memory_file = override_dir / "MEMORY.md"
        override_store.history_file = override_dir / "HISTORY.md"

        messages = ctx.build_messages(
            history=[], current_message="hello",
            memory_store=override_store,
        )
        system_content = messages[0]["content"]
        assert "SESSION_PRIVATE" in system_content
        assert "GLOBAL_SECRET" not in system_content

    def test_api_handler_passes_isolate_memory_and_disabled_tools(self):
        """The API handler must call process_direct with isolate_memory=True and disabled filesystem tools."""
        import ast
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "nanobot" / "api" / "server.py"
        source = server_path.read_text()
        tree = ast.parse(source)

        found_isolate = False
        found_disabled = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword):
                if node.arg == "isolate_memory" and isinstance(node.value, ast.Constant) and node.value.value is True:
                    found_isolate = True
                if node.arg == "disabled_tools":
                    found_disabled = True
        assert found_isolate, "server.py must call process_direct with isolate_memory=True"
        assert found_disabled, "server.py must call process_direct with disabled_tools"

    def test_disabled_tools_constant_blocks_filesystem_and_exec(self):
        """_API_DISABLED_TOOLS must include all filesystem tool names and exec."""
        from nanobot.api.server import _API_DISABLED_TOOLS
        for name in ("read_file", "write_file", "edit_file", "list_dir", "exec"):
            assert name in _API_DISABLED_TOOLS, f"{name} missing from _API_DISABLED_TOOLS"

    def test_system_prompt_uses_isolated_memory_path(self, tmp_path):
        """When memory_store is provided, the system prompt must reference
        the store's paths, NOT the global workspace/memory/MEMORY.md."""
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.memory import MemoryStore

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "memory").mkdir()

        ctx = ContextBuilder(workspace)

        # Default prompt references global path
        default_prompt = ctx.build_system_prompt()
        assert "memory/MEMORY.md" in default_prompt

        # Isolated store
        iso_dir = tmp_path / "sessions" / "wx_dm_alice" / "memory"
        iso_dir.mkdir(parents=True)
        store = MemoryStore.__new__(MemoryStore)
        store.memory_dir = iso_dir
        store.memory_file = iso_dir / "MEMORY.md"
        store.history_file = iso_dir / "HISTORY.md"

        iso_prompt = ctx.build_system_prompt(memory_store=store)
        # Must reference the isolated path
        assert str(iso_dir / "MEMORY.md") in iso_prompt
        assert str(iso_dir / "HISTORY.md") in iso_prompt
        # Must NOT reference the global workspace memory path
        global_mem = str(workspace.resolve() / "memory" / "MEMORY.md")
        assert global_mem not in iso_prompt

    def test_run_agent_loop_filters_disabled_tools(self):
        """_run_agent_loop must exclude disabled tools from definitions
        and reject execution of disabled tools."""
        from nanobot.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()

        # Create minimal fake tool definitions
        class FakeTool:
            def __init__(self, n):
                self._name = n

            @property
            def name(self):
                return self._name

            def to_schema(self):
                return {"type": "function", "function": {"name": self._name, "parameters": {}}}

            def validate_params(self, params):
                return []

            async def execute(self, **kw):
                return "ok"

        for n in ("read_file", "write_file", "web_search", "exec"):
            registry.register(FakeTool(n))

        all_defs = registry.get_definitions()
        assert len(all_defs) == 4

        disabled = {"read_file", "write_file"}
        filtered = [d for d in all_defs
                    if d.get("function", {}).get("name") not in disabled]
        assert len(filtered) == 2
        names = {d["function"]["name"] for d in filtered}
        assert names == {"web_search", "exec"}


# ---------------------------------------------------------------------------
# Consolidation isolation regression tests
# ---------------------------------------------------------------------------


class TestConsolidationIsolation:
    """Verify that memory consolidation in API (isolate_memory) mode writes
    to the per-session directory and never touches global workspace/memory."""

    @pytest.mark.asyncio
    async def test_consolidate_memory_uses_provided_store(self, tmp_path):
        """_consolidate_memory(memory_store=X) must call X.consolidate,
        not MemoryStore(self.workspace).consolidate."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from nanobot.agent.loop import AgentLoop
        from nanobot.agent.memory import MemoryStore
        from nanobot.session.manager import Session

        agent = MagicMock(spec=AgentLoop)
        agent.workspace = tmp_path / "workspace"
        agent.workspace.mkdir()
        agent.provider = MagicMock()
        agent.model = "test"
        agent.memory_window = 50

        # Bind the real method
        agent._consolidate_memory = AgentLoop._consolidate_memory.__get__(agent)

        session = Session(key="test")
        session.messages = [{"role": "user", "content": "hi", "timestamp": "2025-01-01T00:00"}] * 10

        # Create an isolated store and mock its consolidate
        iso_store = MagicMock(spec=MemoryStore)
        iso_store.consolidate = AsyncMock(return_value=True)

        result = await agent._consolidate_memory(session, memory_store=iso_store)

        assert result is True
        iso_store.consolidate.assert_called_once()
        call_args = iso_store.consolidate.call_args
        assert call_args[0][0] is session  # first positional arg is session

    @pytest.mark.asyncio
    async def test_consolidate_memory_defaults_to_global_when_no_store(self, tmp_path):
        """Without memory_store, _consolidate_memory must use MemoryStore(workspace)."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from nanobot.agent.loop import AgentLoop
        from nanobot.session.manager import Session

        agent = MagicMock(spec=AgentLoop)
        agent.workspace = tmp_path / "workspace"
        agent.workspace.mkdir()
        (agent.workspace / "memory").mkdir()
        agent.provider = MagicMock()
        agent.model = "test"
        agent.memory_window = 50
        agent._consolidate_memory = AgentLoop._consolidate_memory.__get__(agent)

        session = Session(key="test")

        with patch("nanobot.agent.loop.MemoryStore") as MockStore:
            mock_instance = MagicMock()
            mock_instance.consolidate = AsyncMock(return_value=True)
            MockStore.return_value = mock_instance

            await agent._consolidate_memory(session)

            MockStore.assert_called_once_with(agent.workspace)
            mock_instance.consolidate.assert_called_once()

    def test_consolidate_writes_to_isolated_dir_not_global(self, tmp_path):
        """End-to-end: MemoryStore.consolidate with an isolated store must
        write HISTORY.md in the isolated dir, not in workspace/memory."""
        from nanobot.agent.memory import MemoryStore

        # Set up global workspace memory
        global_mem_dir = tmp_path / "workspace" / "memory"
        global_mem_dir.mkdir(parents=True)
        (global_mem_dir / "MEMORY.md").write_text("")
        (global_mem_dir / "HISTORY.md").write_text("")

        # Set up isolated per-session store
        iso_dir = tmp_path / "sessions" / "wx_dm_alice" / "memory"
        iso_dir.mkdir(parents=True)

        iso_store = MemoryStore.__new__(MemoryStore)
        iso_store.memory_dir = iso_dir
        iso_store.memory_file = iso_dir / "MEMORY.md"
        iso_store.history_file = iso_dir / "HISTORY.md"

        # Write via the isolated store
        iso_store.write_long_term("Alice's private data")
        iso_store.append_history("[2025-01-01 00:00] Alice asked about X")

        # Isolated store has the data
        assert "Alice's private data" in iso_store.read_long_term()
        assert "Alice asked about X" in iso_store.history_file.read_text()

        # Global store must NOT have it
        assert (global_mem_dir / "MEMORY.md").read_text() == ""
        assert (global_mem_dir / "HISTORY.md").read_text() == ""

    def test_process_message_passes_memory_store_to_consolidation_paths(self):
        """Verify that _process_message passes memory_store to both
        consolidation triggers (source code check)."""
        import ast
        from pathlib import Path

        loop_path = Path(__file__).parent.parent / "nanobot" / "agent" / "loop.py"
        source = loop_path.read_text()
        tree = ast.parse(source)

        # Find all calls to self._consolidate_memory inside _process_message
        # and verify they all pass memory_store=
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name != "_process_message":
                continue
            consolidate_calls = []
            for child in ast.walk(node):
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "_consolidate_memory"):
                    kw_names = {kw.arg for kw in child.keywords}
                    consolidate_calls.append(kw_names)

            assert len(consolidate_calls) == 2, (
                f"Expected 2 _consolidate_memory calls in _process_message, "
                f"found {len(consolidate_calls)}"
            )
            for i, kw_names in enumerate(consolidate_calls):
                assert "memory_store" in kw_names, (
                    f"_consolidate_memory call #{i+1} in _process_message "
                    f"missing memory_store= keyword argument"
                )


# ---------------------------------------------------------------------------
# Empty response retry + fallback tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_empty_response_retry_then_success(aiohttp_client):
    """First call returns empty → retry once → second call returns real text."""
    call_count = 0

    async def sometimes_empty(content, session_key="", channel="", chat_id="",
                              isolate_memory=False, disabled_tools=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ""
        return "recovered response"

    agent = MagicMock()
    agent.process_direct = sometimes_empty
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)

    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"x-session-key": "retry-test"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["choices"][0]["message"]["content"] == "recovered response"
    assert call_count == 2


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_empty_response_both_empty_returns_fallback(aiohttp_client):
    """Both calls return empty → must use the fallback text."""
    call_count = 0

    async def always_empty(content, session_key="", channel="", chat_id="",
                           isolate_memory=False, disabled_tools=None):
        nonlocal call_count
        call_count += 1
        return ""

    agent = MagicMock()
    agent.process_direct = always_empty
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)

    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"x-session-key": "fallback-test"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["choices"][0]["message"]["content"] == "I've completed processing but have no response to give."
    assert call_count == 2


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_whitespace_only_response_triggers_retry(aiohttp_client):
    """Whitespace-only response should be treated as empty and trigger retry."""
    call_count = 0

    async def whitespace_then_ok(content, session_key="", channel="", chat_id="",
                                 isolate_memory=False, disabled_tools=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "   \n  "
        return "real answer"

    agent = MagicMock()
    agent.process_direct = whitespace_then_ok
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)

    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"x-session-key": "ws-test"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["choices"][0]["message"]["content"] == "real answer"
    assert call_count == 2


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_none_response_triggers_retry(aiohttp_client):
    """None response should be treated as empty and trigger retry."""
    call_count = 0

    async def none_then_ok(content, session_key="", channel="", chat_id="",
                           isolate_memory=False, disabled_tools=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None
        return "got it"

    agent = MagicMock()
    agent.process_direct = none_then_ok
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)

    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"x-session-key": "none-test"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["choices"][0]["message"]["content"] == "got it"
    assert call_count == 2


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_nonempty_response_no_retry(aiohttp_client):
    """A normal non-empty response must NOT trigger a retry."""
    call_count = 0

    async def normal_response(content, session_key="", channel="", chat_id="",
                              isolate_memory=False, disabled_tools=None):
        nonlocal call_count
        call_count += 1
        return "immediate answer"

    agent = MagicMock()
    agent.process_direct = normal_response
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)

    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"x-session-key": "normal-test"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["choices"][0]["message"]["content"] == "immediate answer"
    assert call_count == 1
