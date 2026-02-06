"""End-to-end tests for the memory extraction pipeline through AgentLoop.

These tests exercise the full lifecycle: message processing -> fact extraction
-> consolidation -> storage -> retrieval, using mocked LLM responses and
deterministic embeddings.
"""

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.memory.consolidator import MemoryConsolidator, Operation
from nanobot.agent.memory.extractor import ExtractedFact, MemoryExtractor
from nanobot.agent.memory.store import (
    LEARNINGS_NAMESPACE,
    TOOLS_NAMESPACE,
    USER_NAMESPACE,
    EmbeddingService,
    VectorMemoryStore,
)
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.compaction import CompactionConfig as SessionCompactionConfig
from nanobot.session.compaction import SessionCompactor

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeLLMProvider(LLMProvider):
    """Deterministic LLM provider that echoes user messages."""

    def __init__(self) -> None:
        super().__init__(api_key="fake-key", api_base=None)
        self.call_count = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.call_count += 1
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content", "")
                break
        return LLMResponse(content=f"Understood: {last_user[:80]}")

    def get_default_model(self) -> str:
        return "fake-model"


class FakeEmbeddingService(EmbeddingService):
    """Deterministic word-based embedding service for testing.

    Produces sparse vectors where dimensions are set by word hashes.
    Texts sharing words will have higher cosine similarity.
    """

    DIMENSION = 64

    def __init__(self) -> None:
        self.model = "fake-embedding"
        self._dimension = self.DIMENSION

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        for word in text.lower().split():
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            idx = h % self._dimension
            vec[idx] += 1.0
        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    @property
    def dimension(self) -> int:
        return self._dimension

    # Override cached method to avoid calling litellm
    def _embed_cached(self, text: str) -> tuple[float, ...]:
        return tuple(self.embed(text))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def fake_embedding() -> FakeEmbeddingService:
    return FakeEmbeddingService()


@pytest.fixture()
def extraction_store(workspace: Path, fake_embedding: FakeEmbeddingService) -> VectorMemoryStore:
    store = VectorMemoryStore(
        db_path=Path("memory/e2e_vectors.db"),
        base_dir=workspace,
        embedding_service=fake_embedding,
        max_memories=200,
    )
    yield store
    store.close()


@pytest.fixture()
def extractor() -> MemoryExtractor:
    return MemoryExtractor(model="gpt-4o-mini", max_facts=5)


@pytest.fixture()
def consolidator(extraction_store: VectorMemoryStore) -> MemoryConsolidator:
    return MemoryConsolidator(
        store=extraction_store,
        model="gpt-4o-mini",
        candidate_threshold=0.3,
    )


def _make_llm_response(content: str) -> MagicMock:
    """Build a mock litellm completion response."""
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


def _make_extraction_response(facts: list[dict]) -> MagicMock:
    return _make_llm_response(json.dumps(facts))


def _make_consolidation_response(
    operation: str = "ADD",
    memory_id: str | None = None,
    content: str | None = None,
    reason: str = "test",
) -> MagicMock:
    payload = {"operation": operation, "reason": reason}
    if memory_id:
        payload["memory_id"] = memory_id
    if content:
        payload["content"] = content
    return _make_llm_response(json.dumps(payload))


# ---------------------------------------------------------------------------
# Pipeline tests (extractor -> consolidator -> store)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_extract_consolidate_store(
    extractor: MemoryExtractor,
    consolidator: MemoryConsolidator,
    extraction_store: VectorMemoryStore,
) -> None:
    """Full pipeline: LLM extraction -> consolidation -> stored in vector DB."""
    messages = [
        {"role": "user", "content": "My name is Alice and I work at Acme."},
        {"role": "assistant", "content": "Nice to meet you, Alice!"},
        {"role": "user", "content": "I prefer short, direct answers."},
        {"role": "assistant", "content": "Got it."},
        {"role": "user", "content": "Our project uses FastAPI and PostgreSQL."},
    ]

    extraction_resp = _make_extraction_response([
        {"type": "user", "fact": "User name is Alice", "importance": "high"},
        {"type": "user", "fact": "User works at Acme", "importance": "medium"},
        {
            "type": "preference",
            "fact": "User prefers short direct answers",
            "importance": "medium",
        },
        {
            "type": "project",
            "fact": "Project uses FastAPI and PostgreSQL",
            "importance": "high",
        },
    ])

    with patch("litellm.acompletion", new=AsyncMock(return_value=extraction_resp)):
        facts = await extractor.extract(messages, max_facts=5)

    assert len(facts) == 4
    assert facts[0].fact_type == "user"

    # Consolidation with no existing memories -> all ADDs
    results = await consolidator.consolidate(facts, namespace="test-session")
    assert len(results) == 4
    assert all(r.operation == Operation.ADD for r in results)

    # Verify stored in correct namespaces
    user_count = extraction_store.count(namespace=USER_NAMESPACE)
    assert user_count >= 2, f"Expected >=2 user facts, got {user_count}"

    # Search should find Alice
    search_results = extraction_store.search(
        "Alice", top_k=3, threshold=0.1, namespace=USER_NAMESPACE
    )
    assert len(search_results) >= 1
    contents = [item.content for item, _ in search_results]
    assert any("Alice" in c for c in contents)


@pytest.mark.asyncio
async def test_pipeline_lesson_extraction_to_learnings_namespace(
    extractor: MemoryExtractor,
    consolidator: MemoryConsolidator,
    extraction_store: VectorMemoryStore,
) -> None:
    """Lessons from corrections end up in the learnings namespace."""
    messages = [
        {"role": "assistant", "content": "I used tabs for indentation."},
        {"role": "user", "content": "Actually, use spaces. That was wrong."},
    ]

    lesson_resp = _make_llm_response(json.dumps({
        "lesson": "When formatting code, prefer spaces over tabs",
        "category": "tool_usage",
        "importance": "high",
    }))

    with patch("litellm.acompletion", new=AsyncMock(return_value=lesson_resp)):
        lessons = await extractor.extract_lessons(messages, max_facts=3)

    assert len(lessons) >= 1
    assert lessons[0].fact_type == "lesson"

    results = await consolidator.consolidate(lessons, namespace="test-session")
    assert len(results) >= 1

    learnings_count = extraction_store.count(namespace=LEARNINGS_NAMESPACE)
    assert learnings_count >= 1


@pytest.mark.asyncio
async def test_pipeline_tool_lessons_to_tools_namespace(
    extractor: MemoryExtractor,
    consolidator: MemoryConsolidator,
    extraction_store: VectorMemoryStore,
) -> None:
    """Tool failure lessons end up in the tools namespace."""
    messages = [
        {
            "role": "tool",
            "name": "exec",
            "content": "Error: command 'foo' not found in PATH",
        },
        {
            "role": "tool",
            "name": "read_file",
            "content": "Error: permission denied for /etc/shadow",
        },
    ]

    tool_lessons = extractor.extract_tool_lessons(messages, max_lessons=5)
    assert len(tool_lessons) >= 1

    await consolidator.consolidate(tool_lessons, namespace="test-session")

    tools_count = extraction_store.count(namespace=TOOLS_NAMESPACE)
    assert tools_count >= 1


@pytest.mark.asyncio
async def test_consolidation_update_deduplicates(
    extractor: MemoryExtractor,
    consolidator: MemoryConsolidator,
    extraction_store: VectorMemoryStore,
) -> None:
    """Consolidation UPDATEs instead of adding duplicates."""
    # First: add a fact
    fact1 = ExtractedFact(
        content="User name is Alice",
        importance=0.9,
        source="llm",
        fact_type="user",
    )
    results1 = await consolidator.consolidate([fact1], namespace="dedup-test")
    assert results1[0].operation == Operation.ADD
    first_id = results1[0].memory_id

    # Second: similar fact -> LLM should decide UPDATE
    fact2 = ExtractedFact(
        content="User name is Alice Smith",
        importance=0.9,
        source="llm",
        fact_type="user",
    )

    update_resp = _make_consolidation_response(
        operation="UPDATE",
        memory_id=first_id,
        content="User full name is Alice Smith",
        reason="Merging name info",
    )
    with patch("litellm.acompletion", new=AsyncMock(return_value=update_resp)):
        results2 = await consolidator.consolidate([fact2], namespace="dedup-test")

    assert results2[0].operation == Operation.UPDATE
    # Should still have 1 entry, not 2
    assert extraction_store.count(namespace=USER_NAMESPACE) == 1


@pytest.mark.asyncio
async def test_pre_compaction_extraction(
    extractor: MemoryExtractor,
    consolidator: MemoryConsolidator,
    extraction_store: VectorMemoryStore,
) -> None:
    """Pre-compaction flush extracts facts before history is truncated."""
    messages = [
        {"role": "user", "content": "My name is Bob and I prefer Python."},
        {"role": "assistant", "content": "Noted!"},
        {"role": "user", "content": "The project uses Django and Redis."},
        {"role": "assistant", "content": "Good stack!"},
        {"role": "user", "content": "Remember that deployments go through Kubernetes."},
    ]

    pre_compact_resp = _make_extraction_response([
        {"fact": "User name is Bob", "importance": "high"},
        {"fact": "User prefers Python", "importance": "medium"},
        {"fact": "Project uses Django and Redis", "importance": "high"},
    ])

    with patch("litellm.acompletion", new=AsyncMock(return_value=pre_compact_resp)):
        facts = await extractor.extract_for_pre_compaction(messages)

    assert len(facts) == 3
    assert all(f.source == "pre_compaction" for f in facts)

    results = await consolidator.consolidate(facts, namespace="pre-compact-test")
    assert len(results) == 3

    total = sum(
        extraction_store.count(ns)
        for ns in [USER_NAMESPACE, "pre-compact-test"]
    )
    assert total >= 1


@pytest.mark.asyncio
async def test_fact_type_persisted_in_metadata(
    consolidator: MemoryConsolidator,
    extraction_store: VectorMemoryStore,
) -> None:
    """fact_type is stored in metadata for every ADD and UPDATE."""
    fact = ExtractedFact(
        content="User prefers dark mode",
        importance=0.7,
        source="llm",
        fact_type="preference",
    )

    results = await consolidator.consolidate([fact], namespace="meta-test")
    memory_id = results[0].memory_id
    assert memory_id is not None

    # Retrieve and check metadata
    # Preference facts go to session namespace (no dedicated ns)
    item = extraction_store.get(memory_id, namespace="meta-test")
    assert item is not None
    assert item.metadata.get("fact_type") == "preference"
    assert item.metadata.get("importance") == 0.7


@pytest.mark.asyncio
async def test_search_finds_stored_facts(
    extraction_store: VectorMemoryStore,
) -> None:
    """Stored facts are retrievable via semantic search."""
    extraction_store.add(
        "User works at Acme Corporation",
        metadata={"fact_type": "user", "importance": 0.9},
        namespace=USER_NAMESPACE,
    )
    extraction_store.add(
        "Project uses Python and FastAPI",
        metadata={"fact_type": "project", "importance": 0.8},
        namespace="session:test",
    )

    # Search in user namespace
    results = extraction_store.search(
        "Where does the user work?",
        top_k=3,
        threshold=0.0,
        namespace=USER_NAMESPACE,
    )
    assert len(results) >= 1
    assert "Acme" in results[0][0].content


# ---------------------------------------------------------------------------
# AgentLoop integration tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent_loop(
    workspace: Path,
    extractor: MemoryExtractor,
    extraction_store: VectorMemoryStore,
) -> Any:
    """Create an AgentLoop with memory extraction wired up."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.config.schema import MemoryExtractionConfig

    provider = FakeLLMProvider()
    bus = MessageBus()

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        memory_extraction=MemoryExtractionConfig(
            enabled=True,
            **{"extractionInterval": 3},
        ),
    )

    # Wire up extraction components with fake embedding service
    loop._extractor = extractor
    loop._consolidator = MemoryConsolidator(
        store=extraction_store,
        model="gpt-4o-mini",
        candidate_threshold=0.3,
    )
    loop._session_compactor = SessionCompactor(
        config=SessionCompactionConfig(),
        extractor=extractor,
    )

    return loop


@pytest.mark.asyncio
async def test_agent_loop_processes_message(agent_loop: Any) -> None:
    """AgentLoop processes a message and returns a response."""
    msg = InboundMessage(
        channel="test",
        sender_id="user1",
        chat_id="chat1",
        content="Hello, my name is Tim.",
    )
    response = await agent_loop._process_message(msg)
    assert response is not None
    assert response.content is not None
    assert len(response.content) > 0


@pytest.mark.asyncio
async def test_agent_loop_triggers_extraction_on_interval(
    agent_loop: Any,
    extraction_store: VectorMemoryStore,
) -> None:
    """Extraction triggers after extraction_interval user messages.

    The extractor requires >=3 user messages to proceed, and our
    extraction_interval is 3, so we send exactly 3 messages.
    """
    extraction_resp = _make_extraction_response([
        {"type": "user", "fact": "User name is Tim", "importance": "high"},
        {"type": "technical", "fact": "User uses TypeScript", "importance": "medium"},
    ])

    # Process 3 messages (extraction_interval=3, extractor needs >=3 user msgs)
    for content in [
        "My name is Tim and I work at a startup.",
        "I prefer using TypeScript for frontend work.",
        "Our project uses PostgreSQL for the database.",
    ]:
        msg = InboundMessage(
            channel="test",
            sender_id="user1",
            chat_id="chat1",
            content=content,
        )
        with patch(
            "litellm.acompletion",
            new=AsyncMock(return_value=extraction_resp),
        ):
            await agent_loop._process_message(msg)

    # After 3 messages, extraction should have stored facts
    total = sum(
        extraction_store.count(ns)
        for ns in [USER_NAMESPACE, "test:chat1"]
    )
    assert total >= 1, "Expected at least 1 stored fact after extraction interval"


@pytest.mark.asyncio
async def test_agent_loop_pre_compaction_flush(
    agent_loop: Any,
    extraction_store: VectorMemoryStore,
) -> None:
    """Pre-compaction flush extracts facts from long history."""
    # Build up a history manually
    history = []
    for i in range(15):
        history.append(
            {"role": "user", "content": f"My name is User{i} and I work at Company{i}."}
        )
        history.append(
            {"role": "assistant", "content": f"Nice to meet you, User{i}."}
        )

    pre_compact_resp = _make_extraction_response([
        {"fact": "User name is User0", "importance": "high"},
        {"fact": "User works at Company0", "importance": "medium"},
    ])

    with patch("litellm.acompletion", new=AsyncMock(return_value=pre_compact_resp)):
        await agent_loop._pre_compaction_flush(history, namespace="flush-test")

    total = sum(
        extraction_store.count(ns)
        for ns in [USER_NAMESPACE, "flush-test"]
    )
    assert total >= 1


@pytest.mark.asyncio
async def test_agent_loop_extract_and_consolidate(
    agent_loop: Any,
    extraction_store: VectorMemoryStore,
) -> None:
    """_extract_and_consolidate runs full extraction pipeline."""
    messages = [
        {"role": "user", "content": "My name is Carol."},
        {"role": "assistant", "content": "Hi Carol!"},
        {"role": "user", "content": "I prefer dark themes."},
        {"role": "assistant", "content": "Noted."},
        {"role": "user", "content": "Actually, you were wrong about that config."},
    ]

    fact_resp = _make_extraction_response([
        {"type": "user", "fact": "User name is Carol", "importance": "high"},
    ])
    lesson_resp = _make_llm_response(json.dumps({
        "lesson": "Always verify config before applying",
        "category": "reasoning",
        "importance": "high",
    }))

    # Mock acompletion to return different responses for different calls
    call_count = 0

    async def mock_acompletion(**kwargs):
        nonlocal call_count
        call_count += 1
        # First call is fact extraction, subsequent are lesson extraction
        if call_count == 1:
            return fact_resp
        return lesson_resp

    with patch("litellm.acompletion", new=AsyncMock(side_effect=mock_acompletion)):
        await agent_loop._extract_and_consolidate(messages, namespace="e2e-test")

    # Should have facts and/or lessons stored
    total = sum(
        extraction_store.count(ns)
        for ns in [USER_NAMESPACE, LEARNINGS_NAMESPACE, TOOLS_NAMESPACE, "e2e-test"]
    )
    assert total >= 1


# ---------------------------------------------------------------------------
# Session compactor integration
# ---------------------------------------------------------------------------


def test_session_compactor_uses_extractor_heuristic() -> None:
    """SessionCompactor delegates to extractor.extract_heuristic when available."""
    ext = MemoryExtractor(model="gpt-4o-mini", max_facts=5)
    config = SessionCompactionConfig(threshold=10, recent_turns_keep=2)
    compactor = SessionCompactor(config=config, extractor=ext)

    messages = []
    for i in range(12):
        messages.append(
            {"role": "user", "content": f"My name is User{i} and I work at Company{i}."}
        )
        messages.append({"role": "assistant", "content": f"Hello User{i}!"})

    compacted = compactor.compact(messages)
    assert len(compacted) < len(messages)

    # The recall section should contain extracted facts
    recall = compacted[0]["content"]
    assert "Key facts" in recall or "Recalling" in recall
