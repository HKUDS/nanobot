from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nanobot.agent.dream_writer import (
    WriteMemoryConceptsTool,
    infer_writer_provider_capability,
    repair_memory_concepts,
    validate_memory_concepts,
)
from nanobot.agent.memory_wiki import MemoryWikiStore

CONTROLLED = """
[history:cursor:1] [2026-06-01 10:00] [durable] RLV-HOLDOUT-PORT-OLD: Gateway port 8765 was used.
[history:cursor:4] [2026-06-02 10:00] [correction] RLV-HOLDOUT-PORT-CURRENT: Current gateway port is port 8877.
[history:cursor:6] [2026-06-03 10:00] [permanent] RLV-HOLDOUT-PHONE: User phone number is 555-0100.
[history:cursor:7] [2026-06-03 10:05] [correction] User asked to forget RLV-HOLDOUT-PHONE.
[history:cursor:8] [2026-05-01 09:00] [ephemeral] RLV-HOLDOUT-DEMO-OLD: Ship demo on 2026-05-01.
""".strip()


def test_repair_memory_concepts_resolves_corrections_forgets_and_expiry() -> None:
    repaired = repair_memory_concepts(
        [
            {
                "id": "rlv-holdout-port-current",
                "title": "Current port",
                "body": "The model summarized this without the exact port.",
                "type": "project_decision",
                "status": "active",
                "tags": [],
                "source": ["history:cursor:4"],
            }
        ],
        CONTROLLED,
        now=datetime(2026, 6, 17, tzinfo=timezone.utc),
    )
    by_id = {item["id"]: item for item in repaired}

    assert by_id["rlv-holdout-port-old"]["status"] == "invalidated"
    assert by_id["rlv-holdout-port-current"]["status"] == "active"
    assert "port 8877" in by_id["rlv-holdout-port-current"]["body"]
    assert by_id["rlv-holdout-port-current"]["source"] == ["history:cursor:4"]
    assert by_id["rlv-holdout-phone"]["status"] == "forgotten"
    assert by_id["rlv-holdout-demo-old"]["status"] == "expired"

    validation = validate_memory_concepts(repaired, now=datetime(2026, 6, 17, tzinfo=timezone.utc))
    assert validation.ok


def test_validator_rejects_duplicate_active_group_and_missing_source() -> None:
    validation = validate_memory_concepts(
        [
            {
                "id": "project-port-old",
                "title": "Old port",
                "body": "Use port 8765.",
                "type": "project_decision",
                "status": "active",
                "tags": [],
                "source": ["history:cursor:1"],
            },
            {
                "id": "project-port-current",
                "title": "Current port",
                "body": "Use port 8877.",
                "type": "project_decision",
                "status": "active",
                "tags": [],
                "source": [],
            },
        ]
    )

    assert not validation.ok
    assert any("multiple active concepts" in error for error in validation.errors)
    assert any("must include source" in error for error in validation.errors)


@pytest.mark.asyncio
async def test_write_memory_concepts_tool_repairs_and_writes(tmp_path) -> None:
    wiki = MemoryWikiStore(tmp_path / "memory" / "wiki")
    tool = WriteMemoryConceptsTool(
        wiki,
        history_text=CONTROLLED,
        now=datetime(2026, 6, 17, tzinfo=timezone.utc),
    )

    result = await tool.execute(concepts=[])

    assert '"status": "ok"' in result
    context = wiki.get_context("current port phone demo", now=datetime(2026, 6, 17, tzinfo=timezone.utc))
    assert "port 8877" in context
    assert "555-0100" not in context
    assert "2026-05-01" not in context


def test_provider_capability_marks_deepseek_thinking_required_tool_incompatible() -> None:
    capability = infer_writer_provider_capability(
        provider="deepseek",
        model="deepseek-v4-flash",
        reasoning_effort="medium",
    )

    assert capability.supports_required_tool_choice is False
    assert capability.selected_tool_choice == "auto"


def test_provider_capability_allows_required_tool_when_thinking_disabled() -> None:
    capability = infer_writer_provider_capability(
        provider="zhipu",
        model="glm-5.1",
        reasoning_effort="high",
    )

    assert capability.supports_required_tool_choice is True
    assert capability.selected_tool_choice == "required"
