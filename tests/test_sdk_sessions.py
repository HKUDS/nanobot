"""Session import preserves existing state when input validation fails."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.sdk.clients import SessionClient
from nanobot.session.manager import SessionManager


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_batch_without_partial_mutation(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    client = SessionClient(cast(AgentLoop, SimpleNamespace(sessions=sessions)))
    key = "cli:import"
    await client.ingest(key, [{"role": "user", "content": "existing"}], metadata={"title": "existing"})
    before = client.export(key)
    with pytest.raises(ValueError, match="include a role"):
        await client.ingest(
            key,
            iter([{"role": "user", "content": "partial"}, {"content": "invalid"}]),
            metadata={"title": "changed"},
        )
    assert client.export(key) == before
    client.flush()
    sessions.invalidate(key)
    assert client.export(key) == before
