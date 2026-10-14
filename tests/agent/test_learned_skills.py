"""The Dream-to-prompt path for compact learned workflows."""

import json

import pytest

from nanobot.agent.context import ContextBuilder, TranscriptInput
from nanobot.agent.memory import MemoryStore


@pytest.mark.asyncio
async def test_dream_record_is_retrieved_for_matching_query(tmp_path):
    store = MemoryStore(tmp_path)
    dream_tools = store.build_dream_tools()
    result = await dream_tools.execute("save_learned_skill", {
        "task": "Deploy a release with Git",
        "steps": ["Check the release branch", "Run tests", "Publish the tag"],
        "tools": ["git", "pytest"],
        "tags": ["git", "release"],
    })
    assert result == "Saved learned skill."
    assert json.loads(store.skills_file.read_text(encoding="utf-8"))["task"] == (
        "Deploy a release with Git"
    )

    builder = ContextBuilder(tmp_path)
    matching = builder.build_transcript(TranscriptInput(
        history=[], current_message="How do I release with git?",
    ))[0]["content"]
    unrelated = builder.build_transcript(TranscriptInput(
        history=[], current_message="What is the weather?",
    ))[0]["content"]
    without_memory = builder.build_transcript(TranscriptInput(
        history=[], current_message="How do I release with git?",
    ), include_memory=False)[0]["content"]
    assert "Publish the tag" in matching
    assert "Publish the tag" not in unrelated
    assert "Publish the tag" not in without_memory


@pytest.mark.asyncio
async def test_dream_record_rejects_invalid_and_duplicate_workflows(tmp_path):
    store = MemoryStore(tmp_path)
    dream_tools = store.build_dream_tools()
    skill = {
        "task": "Inspect a release",
        "steps": ["Fetch tags", "Compare the code"],
        "tools": ["git"],
        "tags": ["git", "release"],
    }
    assert await dream_tools.execute("save_learned_skill", skill) == "Saved learned skill."
    assert await dream_tools.execute("save_learned_skill", {
        **skill, "task": "Another release workflow",
    }) == "Skipped similar learned skill."
    assert len(store.load_skills()) == 1

    invalid = await dream_tools.execute("save_learned_skill", {
        **skill, "steps": ["Only one step"],
    })
    assert invalid.is_error
    assert len(store.load_skills()) == 1
