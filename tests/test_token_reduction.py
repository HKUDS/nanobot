from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from nanobot.agent.tools.result_cache import _heuristic_summary

# ── Helpers ──────────────────────────────────────────────────────────────────


def make_store():
    """Minimal MemoryStore with mocked I/O for unit tests."""
    from nanobot.agent.memory.store import MemoryStore

    store = MemoryStore.__new__(MemoryStore)
    store.workspace = MagicMock()
    store.config = MagicMock()
    store._mem0 = None
    store._graph = None
    store._reranker = None
    return store


# ── Task 1: Remove redundant _cap_long_term_text call ───────────────────────


def test_cap_long_term_text_called_once(monkeypatch):
    """_cap_long_term_text must be called at most once per get_memory_context call."""
    store = make_store()
    call_count = 0
    original = store._cap_long_term_text

    def counting_cap(text: str, cap: int, query: str) -> str:
        nonlocal call_count
        call_count += 1
        return original(text, cap, query)

    monkeypatch.setattr(store, "_cap_long_term_text", counting_cap)

    long_term_text = "fact. " * 300  # ~300 tokens, well within the 1500 cap

    with (
        patch.object(store, "read_long_term", return_value=long_term_text),
        patch.object(store, "read_profile", return_value={}),
        patch.object(store, "retrieve", return_value=[]),
        patch.object(store, "read_events", return_value=[]),
        patch.object(store, "_build_graph_context_lines", return_value=[]),
    ):
        store.get_memory_context(query="test query", token_budget=900, memory_md_token_cap=1500)

    assert call_count == 1, f"_cap_long_term_text called {call_count} times; expected exactly 1"


# ── Task 2: Heuristic summary preview length ─────────────────────────────────

_PREVIEW_MAX_CHARS = 400


def test_heuristic_summary_preview_length():
    """Heuristic summary preview must not exceed _PREVIEW_MAX_CHARS characters."""
    large_output = "x" * 50_000
    summary = _heuristic_summary("shell", large_output, "cache-key-abc")

    assert "Preview:\n" in summary
    preview_start = summary.index("Preview:\n") + len("Preview:\n")
    preview_end = summary.index("\n...\n", preview_start)
    preview = summary[preview_start:preview_end]

    assert len(preview) <= _PREVIEW_MAX_CHARS, (
        f"Preview is {len(preview)} chars; expected ≤{_PREVIEW_MAX_CHARS}"
    )


# ── Task 3: Scratchpad injection cap ─────────────────────────────────────────

_SCRATCHPAD_INJECTION_LIMIT = 4000


def test_scratchpad_injection_is_capped():
    """_cap_scratchpad_for_injection must truncate content over _SCRATCHPAD_INJECTION_LIMIT chars."""
    from nanobot.agent.delegation import _cap_scratchpad_for_injection

    large_content = "data. " * 5000  # ~30,000 chars
    result = _cap_scratchpad_for_injection(large_content, limit=_SCRATCHPAD_INJECTION_LIMIT)
    assert "[truncated" in result
    assert len(result) <= _SCRATCHPAD_INJECTION_LIMIT + 200  # +200 for truncation notice


def test_scratchpad_injection_unchanged_when_small():
    """_cap_scratchpad_for_injection must not modify content under the limit."""
    from nanobot.agent.delegation import _cap_scratchpad_for_injection

    small_content = "short content"
    result = _cap_scratchpad_for_injection(small_content, limit=_SCRATCHPAD_INJECTION_LIMIT)
    assert result == small_content
    assert "[truncated" not in result


# ── Task 4: Gate unresolved events scan on intent ────────────────────────────


def test_read_events_not_called_for_fact_lookup(monkeypatch):
    """read_events must not be called when the inferred intent is 'fact_lookup'."""
    store = make_store()
    read_events_called = False

    def mock_read_events(limit: int = 60) -> list:
        nonlocal read_events_called
        read_events_called = True
        return []

    with (
        patch.object(store, "read_long_term", return_value=""),
        patch.object(store, "read_profile", return_value={}),
        patch.object(store, "retrieve", return_value=[]),
        patch.object(store, "read_events", side_effect=mock_read_events),
        patch.object(store, "_build_graph_context_lines", return_value=[]),
    ):
        store.get_memory_context(query="what is the capital of France", token_budget=900)

    assert not read_events_called, "read_events was called for a fact_lookup query"


def test_read_events_called_for_planning(monkeypatch):
    """read_events must be called when the query infers a planning intent."""
    store = make_store()
    read_events_called = False

    def mock_read_events(limit: int = 60) -> list:
        nonlocal read_events_called
        read_events_called = True
        return []

    with (
        patch.object(store, "read_long_term", return_value=""),
        patch.object(store, "read_profile", return_value={}),
        patch.object(store, "retrieve", return_value=[]),
        patch.object(store, "read_events", side_effect=mock_read_events),
        patch.object(store, "_build_graph_context_lines", return_value=[]),
    ):
        store.get_memory_context(query="plan the sprint tasks for next week", token_budget=900)

    assert read_events_called, "read_events was NOT called for a planning query"


# ── Task 5: Trim _get_identity() memory block ────────────────────────────────


def test_identity_memory_block_under_token_limit():
    """The memory instructions in _get_identity() must be ≤60 tokens (~240 chars)."""
    from nanobot.agent.context import ContextBuilder

    builder = ContextBuilder.__new__(ContextBuilder)
    builder.workspace = Path("/tmp")
    identity = builder._get_identity()

    marker = "## Using Your Memory Context"
    assert marker in identity, "Memory context instructions section not found"

    start = identity.index(marker) + len(marker)
    rest = identity[start:]
    next_section = rest.find("\n## ")
    section_text = rest[:next_section].strip() if next_section != -1 else rest.strip()

    char_count = len(section_text)
    assert char_count <= 240, (
        f"Memory instructions are {char_count} chars (~{char_count // 4} tokens); "
        f"expected ≤240 chars (~60 tokens)."
    )


# ── Task 6: Skills summary format ────────────────────────────────────────────


def test_skills_summary_is_compact(tmp_path, monkeypatch):
    """Skills summary must use one line per skill, not multi-line XML."""
    from nanobot.agent.skills import SkillsLoader

    loader = SkillsLoader(workspace=tmp_path)

    fake_skills = [
        {"name": "weather", "path": str(tmp_path / "weather/SKILL.md"), "available": True},
        {"name": "github", "path": str(tmp_path / "github/SKILL.md"), "available": False},
    ]
    monkeypatch.setattr(loader, "list_skills", lambda filter_unavailable=True: fake_skills)
    monkeypatch.setattr(loader, "_get_skill_description", lambda name: f"{name} description")
    monkeypatch.setattr(loader, "_get_skill_meta", lambda name: {})
    monkeypatch.setattr(loader, "_check_requirements", lambda meta: True)

    summary = loader.build_skills_summary()

    assert "<skill" not in summary, "Skills summary must not use XML <skill> tags"
    assert "<skills>" not in summary, "Skills summary must not use <skills> root element"

    weather_lines = [line for line in summary.splitlines() if "weather" in line]
    github_lines = [line for line in summary.splitlines() if "github" in line]
    assert len(weather_lines) == 1, f"'weather' appears on {len(weather_lines)} lines"
    assert len(github_lines) == 1, f"'github' appears on {len(github_lines)} lines"
