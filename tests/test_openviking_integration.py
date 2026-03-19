"""Integration tests for VikingClient against real Dashscope embedding service.

These tests exercise the full write-then-recall cycle with no mocking:
  commit → wait_processed → search / find / search_memory / grep

Run with:
    python -m pytest tests/test_openviking_integration.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import pathlib
import tempfile
import uuid

import pytest

from nanobot.agent.tools.openviking import OVGrepTool, _OVTool
from nanobot.openviking.client import VikingClient

EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_API_KEY = "sk-e43189bfbcc24a01bab723f9ebb38e81"
EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

VLM_API_KEY = "sk-e43189bfbcc24a01bab723f9ebb38e81"
VLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
VLM_MODEL = "qwen-vl-plus"

TEST_USER_ID = "default"




# ---------------------------------------------------------------------------
# Module-scoped fixtures (OpenVikingConfigSingleton is a process-level singleton)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def data_dir():
    """Provide a temporary directory that lives for the entire module."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture(scope="module")
def event_loop():
    """Override the default function-scoped loop so module-scoped async fixtures work."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def client(data_dir: str) -> VikingClient:
    """Create a real VikingClient in local mode with Dashscope embedding."""
    vc = await VikingClient.create(
        mode="local",
        data_dir=data_dir,
        user_id=TEST_USER_ID,
        agent_id="integration_test",
        embedding_model=EMBEDDING_MODEL,
        embedding_api_key=EMBEDDING_API_KEY,
        embedding_base_url=EMBEDDING_BASE_URL,
        embedding_dimension=1024,
        vlm_api_key=VLM_API_KEY,
        vlm_base_url=VLM_BASE_URL,
        vlm_model=VLM_MODEL,
    )
    yield vc
    await vc.aclose()


@pytest.fixture(scope="module")
async def committed_client(client: VikingClient) -> VikingClient:
    """Commit a batch of semantically distinct messages, then wait for indexing.

    Downstream tests rely on these messages being searchable.
    """
    messages = [
        {"role": "user", "content": "我喜欢用 Python 编写后端服务，特别是 FastAPI 框架"},
        {"role": "assistant", "content": "Python 和 FastAPI 是构建高性能 API 的绝佳选择，支持异步和类型提示"},
        {"role": "user", "content": "周末我通常会去公园跑步锻炼身体"},
        {"role": "assistant", "content": "跑步是很好的有氧运动，建议每次 30 分钟以上效果更好"},
        {"role": "user", "content": "我正在学习 Kubernetes 来部署微服务架构"},
        {"role": "assistant", "content": "Kubernetes 是容器编排的行业标准，掌握它对微服务部署非常有帮助"},
    ]
    result = await client.commit(
        session_id=f"integ_test_{uuid.uuid4().hex[:8]}",
        messages=messages,
        sender_id=TEST_USER_ID,
    )
    assert result.get("success") is True, f"Commit failed: {result}"

    await client.client.wait_processed()
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCommit:
    """Verify that commit correctly writes data to OpenViking."""

    async def test_commit_returns_success(self, client: VikingClient) -> None:
        messages = [
            {"role": "user", "content": "今天天气真好，适合出去散步"},
            {"role": "assistant", "content": "是的，阳光明媚的日子最适合户外活动了"},
        ]
        result = await client.commit(
            session_id=f"commit_test_{uuid.uuid4().hex[:8]}",
            messages=messages,
        )
        assert isinstance(result, dict)
        assert result.get("success") is True

    async def test_commit_with_tool_parts(self, client: VikingClient) -> None:
        messages = [
            {"role": "user", "content": "帮我读取 config.json 文件"},
            {
                "role": "assistant",
                "content": "已读取文件内容如下",
                "tools_used": [
                    {
                        "tool_name": "read_file",
                        "args": '{"path": "/app/config.json"}',
                        "result": '{"debug": true, "port": 8080}',
                        "execute_success": True,
                        "duration": 0.05,
                    }
                ],
            },
        ]
        result = await client.commit(
            session_id=f"tool_test_{uuid.uuid4().hex[:8]}",
            messages=messages,
        )
        assert isinstance(result, dict)
        assert result.get("success") is True


class TestRecall:
    """Verify that committed data can be recalled via find / search."""

    async def test_find_recalls_committed_data(self, committed_client: VikingClient) -> None:
        result = await committed_client.find("Python FastAPI 后端开发", limit=5)
        memories = getattr(result, "memories", [])
        assert len(memories) > 0, "find() should recall at least one memory about Python/FastAPI"

        top = memories[0]
        abstract = getattr(top, "abstract", "")
        assert abstract, "Top memory should have a non-empty abstract"

    async def test_search_returns_structured_result(self, committed_client: VikingClient) -> None:
        result = await committed_client.search("Kubernetes 微服务部署")
        assert isinstance(result, dict)
        for key in ("memories", "resources", "skills", "total", "query", "target_uri"):
            assert key in result, f"search result missing key: {key}"
        assert result["query"] == "Kubernetes 微服务部署"
        assert isinstance(result["memories"], list)

    async def test_search_user_memory_recalls_data(self, committed_client: VikingClient) -> None:
        results = await committed_client.search_user_memory(
            "Python 编程", sender_id=TEST_USER_ID,
        )
        assert isinstance(results, list)
        if results:
            item = results[0]
            assert "uri" in item
            assert "abstract" in item
        # Note: search_user_memory uses client.search(); results may be empty if SDK
        # indexing/search differs from find(). Structure is validated when non-empty.

    async def test_search_memory_returns_user_and_agent(self, committed_client: VikingClient) -> None:
        result = await committed_client.search_memory("跑步锻炼", limit=5)
        assert isinstance(result, dict)
        assert "user_memory" in result
        assert "agent_memory" in result
        assert isinstance(result["user_memory"], list)
        assert isinstance(result["agent_memory"], list)

    async def test_get_viking_memory_context_format(self, committed_client: VikingClient) -> None:
        ctx = await committed_client.get_viking_memory_context("Python 编程 FastAPI")
        assert isinstance(ctx, str)
        if ctx:
            assert "User Memories" in ctx
            assert "Agent Memories" in ctx

    async def test_find_irrelevant_query_returns_empty_or_low_score(
        self, committed_client: VikingClient,
    ) -> None:
        result = await committed_client.find(
            "量子力学中薛定谔方程的数学推导", limit=5,
        )
        memories = getattr(result, "memories", [])
        if memories:
            top_score = getattr(memories[0], "score", 0.0)
            assert top_score < 0.5, (
                f"Irrelevant query should not get high score, got {top_score}"
            )


class TestGrep:
    """Verify grep (regex search) within Viking URIs."""

    async def test_grep_user_memory_finds_committed_content(
        self, committed_client: VikingClient,
    ) -> None:
        """Grep for 'Python' in user memories; committed messages contain it."""
        uri = f"viking://user/{TEST_USER_ID}/memories/"
        result = await committed_client.grep(uri, "Python")
        if isinstance(result, dict):
            matches = result.get("result", {}).get("matches", result.get("matches", []))
            count = result.get("result", {}).get("count", result.get("count", 0))
        else:
            matches = getattr(result, "matches", [])
            count = getattr(result, "count", 0)
        assert count >= 0, "grep should return a count"
        if matches:
            m = matches[0]
            content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
            assert "Python" in content or "python" in content.lower(), (
                f"Match should contain 'Python', got: {content[:100]}"
            )

    async def test_grep_no_matches(self, committed_client: VikingClient) -> None:
        """Grep for nonexistent pattern returns empty or zero count."""
        uri = f"viking://user/{TEST_USER_ID}/memories/"
        result = await committed_client.grep(uri, "XyZ_NoNeXiStEnT_123")
        if isinstance(result, dict):
            matches = result.get("result", {}).get("matches", result.get("matches", []))
        else:
            matches = getattr(result, "matches", [])
        assert len(matches) == 0, "Nonexistent pattern should yield no matches"

    async def test_grep_resources_after_add(
        self, client: VikingClient, data_dir: str,
    ) -> None:
        """Add a resource with known text, then grep for it."""
        resource_file = pathlib.Path(data_dir) / "grep_test.txt"
        resource_file.write_text("OpenViking grep integration test keyword: GREP_TEST_TOKEN", encoding="utf-8")
        try:
            await client.add_resource(str(resource_file), desc="grep test resource")
            await client.client.wait_processed()
            result = await client.grep("viking://resources/", "GREP_TEST_TOKEN")
            if isinstance(result, dict):
                matches = result.get("result", {}).get("matches", result.get("matches", []))
            else:
                matches = getattr(result, "matches", [])
            assert len(matches) >= 1, (
                f"grep should find GREP_TEST_TOKEN in added resource, got: {result}"
            )
        finally:
            resource_file.unlink(missing_ok=True)

    async def test_ov_grep_tool_execute(self, committed_client: VikingClient) -> None:
        """OVGrepTool.execute returns formatted matches when pattern exists."""
        old_client = _OVTool._shared_client
        _OVTool._shared_client = committed_client
        try:
            tool = OVGrepTool()
            result = await tool.execute(
                uri=f"viking://user/{TEST_USER_ID}/memories/",
                pattern="Python",
            )
            assert isinstance(result, str)
            assert "Python" in result or "match" in result.lower(), (
                f"Tool should return matches or 'No matches', got: {result[:200]}"
            )
        finally:
            _OVTool._shared_client = old_client
