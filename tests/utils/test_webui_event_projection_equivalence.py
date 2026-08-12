"""Shared characterization cases for live and persisted WebUI projection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.webui.transcript import replay_transcript_to_ui_messages

_FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "webui"
    / "src"
    / "tests"
    / "fixtures"
    / "live-replay-event-projection.json"
)
_SEMANTIC_MESSAGE_FIELDS = (
    "role",
    "content",
    "kind",
    "traces",
    "toolEvents",
    "fileEdits",
    "images",
    "media",
    "cliApps",
    "mcpPresets",
    "sessionMentions",
    "reasoning",
    "latencyMs",
    "source",
    "turnId",
    "turnPhase",
    "turnSeq",
)


def _normalize_projection(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segment_aliases: dict[str, str] = {}
    normalized: list[dict[str, Any]] = []
    for message in messages:
        row = {
            field: message[field]
            for field in _SEMANTIC_MESSAGE_FIELDS
            if field in message and message[field] is not None
        }
        segment_id = message.get("activitySegmentId")
        if isinstance(segment_id, str) and segment_id:
            row["activitySegmentId"] = segment_aliases.setdefault(
                segment_id,
                f"segment-{len(segment_aliases) + 1}",
            )
        normalized.append(row)
    return normalized


def test_replay_matches_shared_live_projection_before_canonical_revision_migration() -> None:
    """Lock the known-equivalent subset without defining the future snapshot protocol."""
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

    for case in fixture["cases"]:
        actual = replay_transcript_to_ui_messages(case["transcript"])
        assert _normalize_projection(actual) == case["expected"], case["name"]
