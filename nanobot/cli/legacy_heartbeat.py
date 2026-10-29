"""One-time import of retired Heartbeat instructions into ordinary automations."""

import json
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from loguru import logger

from nanobot.config.schema import Config
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY, default_workspace_scope
from nanobot.session.manager import SessionManager

_IMPORT_KEY = "heartbeat-to-scheduled-task-v1"


def _legacy_enabled(config_path: Path) -> bool:
    """Read only the retired opt-out, without retaining a runtime config API."""
    if not config_path.exists():
        return True
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return data.get("gateway", {}).get("heartbeat", {}).get("enabled", True) is not False


async def import_heartbeat_task(
    config: Config, config_path: Path, cron: CronService, sessions: SessionManager,
) -> None:
    """Import once before scheduling; keep source files and normal user edits intact."""
    if cron.has_completed_import(_IMPORT_KEY):
        return
    workspace = config.workspace_path.resolve()
    sources = [path for name in ("HEARTBEAT.md", "heartbeat.md") if (path := workspace / name).exists()]
    if len(sources) > 1:
        if not sources[0].samefile(sources[1]):
            raise ValueError("Both HEARTBEAT.md and heartbeat.md exist; keep one source before upgrading")
        sources = sources[:1]
    job = None
    if sources:
        source = sources[0]
        if config.tools.restrict_to_workspace and not source.resolve().is_relative_to(workspace):
            raise ValueError("Heartbeat instructions resolve outside the restricted workspace")
        content = source.read_text(encoding="utf-8")
        # Old bundled templates contain headings/comments but no instructions.
        # This is an import decision only; ordinary jobs have no special evaluator.
        visible = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
        has_instructions = any(line.strip() and not line.lstrip().startswith("#") for line in visible.splitlines())
        enabled = has_instructions and _legacy_enabled(config_path)
        chat_id = str(uuid5(NAMESPACE_URL, f"nanobot:heartbeat-import:{workspace}"))
        session_key = f"websocket:{chat_id}"
        scope = default_workspace_scope(
            workspace, config.tools.restrict_to_workspace, source_channel="websocket",
        ).metadata()

        def initialize(metadata: dict[str, Any]) -> None:
            metadata.setdefault("title", "Imported Heartbeat")
            metadata.setdefault(WORKSPACE_SCOPE_METADATA_KEY, scope)

        # Create the ordinary destination before publishing a runnable job. A
        # failed cron commit can leave this harmless empty topic, never a job
        # pointing at a missing or less restricted session.
        await sessions.state.mutate_metadata(session_key, initialize, create_if_missing=True)
        now_ms = int(time.time() * 1000)
        previous = cron.get_job("heartbeat")
        previous_state = (
            deepcopy(previous.state)
            if previous is not None and previous.payload.kind == "system_event" else CronJobState()
        )
        for record in previous_state.run_history:
            record.session_key = record.session_key or "heartbeat"
        job = CronJob(
            id=f"import-{chat_id[:8]}",
            name="Imported Heartbeat",
            enabled=enabled,
            schedule=CronSchedule(kind="every", every_ms=30 * 60 * 1000),
            payload=CronPayload(
                message=content if content.strip() else "Add instructions before enabling this imported task.",
                session_key=session_key,
                origin_channel="websocket",
                origin_chat_id=chat_id,
                origin_metadata={"webui": True, WORKSPACE_SCOPE_METADATA_KEY: scope},
            ),
            state=previous_state,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
    cron.import_job_once(_IMPORT_KEY, job, replace_system_job_id="heartbeat")
    if job is not None:
        logger.info(
            "Imported {} as ordinary automation {} (every 30 minutes, enabled={}); source preserved",
            sources[0].name, job.id, job.enabled,
        )
