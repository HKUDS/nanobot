"""Tests for MemoryWriteTool: lifecycle management and deduplication."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.memory import MemoryStore, DedupResult, SearchResult
from nanobot.agent.tools.memory import MemoryWriteTool
from nanobot.config.schema import MemoryConfig
from nanobot.providers.base import LLMResponse


# ============================================================================
# Helpers
# ============================================================================


def _make_store(workspace, **config_overrides):
    """Create a MemoryStore with default config and optional overrides."""
    config = MemoryConfig(**config_overrides)
    return MemoryStore(workspace, memory_config=config)


def _make_tool(store, provider=None, model="fake-model"):
    """Create a MemoryWriteTool with optional mock provider."""
    return MemoryWriteTool(
        memory_store=store,
        provider=provider,
        model=model,
    )


def _mock_provider(response_content: str):
    """Create a mock provider that returns a given string."""
    provider = MagicMock()
    provider.chat = AsyncMock(return_value=LLMResponse(content=response_content))
    return provider


# ============================================================================
# Tool schema
# ============================================================================


def test_write_tool_schema():
    """Tool has correct name, description, and parameter schema."""
    store = MagicMock(spec=MemoryStore)
    tool = _make_tool(store)

    assert tool.name == "memory_write"
    assert "write" in tool.description.lower() or "memory" in tool.description.lower()

    schema = tool.parameters
    assert schema["type"] == "object"
    assert "action" in schema["properties"]
    assert "text" in schema["properties"]
    assert "category" in schema["properties"]
    assert set(schema["required"]) == {"action", "text", "category"}

    # Valid categories
    assert "preference" in schema["properties"]["category"]["enum"]
    assert "fact" in schema["properties"]["category"]["enum"]
    assert "project" in schema["properties"]["category"]["enum"]
    assert "decision" in schema["properties"]["category"]["enum"]

    # OpenAI function schema
    fn_schema = tool.to_schema()
    assert fn_schema["type"] == "function"
    assert fn_schema["function"]["name"] == "memory_write"


# ============================================================================
# Add new entry
# ============================================================================


async def test_write_add_new_entry(memory_file):
    """Adding a new memory entry appends it to MEMORY.md under the correct section."""
    store = _make_store(memory_file)
    tool = _make_tool(store, provider=None)  # no provider = skip dedup

    result = await tool.execute(
        action="add", text="User likes tea", category="preference",
    )

    assert "Saved new memory" in result
    assert "[preference]" in result

    content = store.read_long_term()
    assert "- [preference] User likes tea" in content
    # Should be under ## Preferences section
    lines = content.splitlines()
    pref_idx = next(i for i, l in enumerate(lines) if l == "## Preferences")
    tea_idx = next(i for i, l in enumerate(lines) if "User likes tea" in l)
    assert tea_idx > pref_idx


async def test_write_add_with_category(workspace):
    """Entry is formatted with proper category tag in correct section."""
    store = _make_store(workspace)
    tool = _make_tool(store)

    await tool.execute(action="add", text="Migrate to PostgreSQL", category="decision")

    content = store.read_long_term()
    assert "- [decision] Migrate to PostgreSQL" in content
    assert "## Decisions" in content


async def test_write_add_entry_with_section_header_in_content(workspace):
    """Entry text containing a section header string doesn't corrupt the file."""
    # Set up a MEMORY.md that has a fact mentioning "## Preferences" in its text
    (workspace / "memory" / "MEMORY.md").write_text(
        "# Long-term Memory\n\n"
        "## User\n"
        "- [fact] See ## Preferences for user likes\n\n"
        "## Preferences\n"
        "- [preference] User likes dark mode\n"
    )

    store = _make_store(workspace)
    tool = _make_tool(store)

    # Add a new preference — should go under the real ## Preferences header,
    # not after the "## Preferences" substring in the fact entry
    await tool.execute(action="add", text="User likes tea", category="preference")

    content = store.read_long_term()
    lines = content.splitlines()

    # Find the real ## Preferences section header
    pref_header_idx = next(i for i, l in enumerate(lines) if l.strip() == "## Preferences")
    tea_idx = next(i for i, l in enumerate(lines) if "User likes tea" in l)

    # The new entry must appear after the real header, not after the fact line
    assert tea_idx == pref_header_idx + 1


async def test_write_add_creates_memory_file(workspace):
    """If MEMORY.md doesn't exist, it is bootstrapped on first add."""
    store = _make_store(workspace)
    assert not store.memory_file.exists()

    tool = _make_tool(store)
    await tool.execute(action="add", text="First fact", category="fact")

    assert store.memory_file.exists()
    content = store.read_long_term()
    assert "# Long-term Memory" in content
    assert "- [fact] First fact" in content


# ============================================================================
# Update existing entry
# ============================================================================


async def test_write_update_existing(memory_file):
    """Explicit update replaces the old entry text."""
    store = _make_store(memory_file)
    tool = _make_tool(store)

    result = await tool.execute(
        action="update",
        text="User is based in Beijing",
        category="fact",
        old_text="User is based in Shanghai",
    )

    assert "Updated memory" in result
    content = store.read_long_term()
    assert "- [fact] User is based in Beijing" in content
    assert "User is based in Shanghai" not in content


async def test_write_update_does_not_match_substring(memory_file):
    """Update with a substring should not match a longer entry."""
    store = _make_store(memory_file)
    tool = _make_tool(store)

    # "User is based in Shanghai" exists, but "Shanghai" alone should NOT match
    # because we require exact line matching, not substring
    result = await tool.execute(
        action="update",
        text="Shanghai is nice",
        category="fact",
        old_text="Shanghai",
    )

    # The update should fail because "Shanghai" is not an exact line
    assert "Could not find" in result
    # Original entry should be unchanged
    content = store.read_long_term()
    assert "- [fact] User is based in Shanghai" in content


async def test_write_update_exact_line_match(memory_file):
    """Update matches the exact stripped line content."""
    store = _make_store(memory_file)
    tool = _make_tool(store)

    # This matches the exact line "- [fact] User is based in Shanghai"
    result = await tool.execute(
        action="update",
        text="User is based in Beijing",
        category="fact",
        old_text="- [fact] User is based in Shanghai",
    )

    assert "Updated memory" in result
    content = store.read_long_term()
    assert "Beijing" in content
    assert "Shanghai" not in content


async def test_write_update_not_found(memory_file):
    """Update with non-existent old_text returns failure message."""
    store = _make_store(memory_file)
    tool = _make_tool(store)

    result = await tool.execute(
        action="update",
        text="Something new",
        category="fact",
        old_text="This entry does not exist anywhere",
    )

    assert "Could not find" in result


# ============================================================================
# Deduplication
# ============================================================================


async def test_write_dedup_no_candidates(workspace):
    """When no similar entries exist, directly adds without LLM call."""
    store = _make_store(workspace)
    provider = _mock_provider("")  # Should not be called
    tool = _make_tool(store, provider=provider)

    result = await tool.execute(
        action="add", text="Brand new fact", category="fact",
    )

    assert "Saved new memory" in result
    provider.chat.assert_not_called()


async def test_write_dedup_with_candidates_calls_llm(memory_file):
    """When similar entries found, LLM is called to judge."""
    store = _make_store(memory_file)
    llm_response = json.dumps({
        "action": "add",
        "reason": "genuinely new information",
        "update_target": "",
    })
    provider = _mock_provider(llm_response)
    tool = _make_tool(store, provider=provider)

    result = await tool.execute(
        action="add", text="User also likes coffee", category="preference",
    )

    assert "Saved new memory" in result
    provider.chat.assert_called_once()


async def test_write_noop_duplicate(memory_file):
    """LLM judges entry as duplicate, write is skipped."""
    store = _make_store(memory_file)
    llm_response = json.dumps({
        "action": "noop",
        "reason": "already captured by existing preference",
        "update_target": "",
    })
    provider = _mock_provider(llm_response)
    tool = _make_tool(store, provider=provider)

    original_content = store.read_long_term()

    result = await tool.execute(
        action="add",
        text="User prefers Python over JavaScript",
        category="preference",
    )

    assert "already exists" in result or "skipped" in result
    # MEMORY.md should not have changed
    assert store.read_long_term() == original_content


async def test_write_dedup_update_via_llm(memory_file):
    """LLM judges entry as update, old entry is replaced."""
    store = _make_store(memory_file)
    llm_response = json.dumps({
        "action": "update",
        "reason": "user moved cities",
        "update_target": "- [fact] User is based in Shanghai",
    })
    provider = _mock_provider(llm_response)
    tool = _make_tool(store, provider=provider)

    result = await tool.execute(
        action="add",
        text="User is based in Beijing",
        category="fact",
    )

    assert "Updated existing memory" in result
    content = store.read_long_term()
    assert "Beijing" in content
    assert "Shanghai" not in content


async def test_write_dedup_llm_parse_error_fallback(memory_file):
    """LLM returns invalid JSON, falls back to add."""
    store = _make_store(memory_file)
    provider = _mock_provider("This is not JSON at all!")
    tool = _make_tool(store, provider=provider)

    result = await tool.execute(
        action="add", text="Fallback entry", category="fact",
    )

    # Should still succeed via fallback
    assert "Saved new memory" in result
    assert "- [fact] Fallback entry" in store.read_long_term()


async def test_write_invalid_category(memory_file):
    """Invalid category returns error message."""
    store = _make_store(memory_file)
    tool = _make_tool(store)

    result = await tool.execute(
        action="add", text="Test", category="invalid_cat",
    )

    assert "Invalid category" in result
