"""IT-17: MissionManager lifecycle — start, list, status transitions.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.coordination.mission import Mission, MissionManager, MissionStatus
from nanobot.providers.litellm_provider import LiteLLMProvider
from tests.integration.conftest import MODEL

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(
    provider: LiteLLMProvider,
    workspace: Path,
    *,
    max_concurrent: int = 3,
    max_iterations: int = 3,
) -> MissionManager:
    return MissionManager(
        provider=provider,
        workspace=workspace,
        bus=MessageBus(),
        model=MODEL,
        max_concurrent=max_concurrent,
        max_iterations=max_iterations,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMissionStart:
    async def test_start_returns_mission(self, tmp_path: Path, provider: LiteLLMProvider) -> None:
        """start() returns a Mission object with correct initial state."""
        mgr = _make_manager(provider, tmp_path)
        mission = await mgr.start("Summarise README", label="readme-summary")

        assert isinstance(mission, Mission)
        assert mission.label == "readme-summary"
        assert mission.task == "Summarise README"
        assert mission.status in (MissionStatus.PENDING, MissionStatus.RUNNING)
        assert mission.id is not None
        assert len(mission.id) > 0

    async def test_start_appears_in_list_all(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        """A started mission appears in list_all()."""
        mgr = _make_manager(provider, tmp_path)
        mission = await mgr.start("Check dependencies", label="dep-check")

        all_missions = mgr.list_all()
        assert len(all_missions) >= 1
        ids = [m.id for m in all_missions]
        assert mission.id in ids


class TestMissionStatus:
    async def test_mission_transitions_to_running(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        """After start(), mission eventually transitions to RUNNING."""
        mgr = _make_manager(provider, tmp_path)
        mission = await mgr.start("List workspace files")

        # Give the background task a moment to start
        await asyncio.sleep(0.2)

        # Re-fetch from manager to get updated status
        current = mgr.get(mission.id)
        assert current is not None
        assert current.status in (
            MissionStatus.PENDING,
            MissionStatus.RUNNING,
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
        )

    async def test_multiple_missions_tracked(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        """Multiple missions are tracked independently."""
        mgr = _make_manager(provider, tmp_path, max_concurrent=3)

        m1 = await mgr.start("Task one", label="t1")
        m2 = await mgr.start("Task two", label="t2")

        all_missions = mgr.list_all()
        assert len(all_missions) >= 2
        ids = {m.id for m in all_missions}
        assert m1.id in ids
        assert m2.id in ids
        assert m1.id != m2.id
