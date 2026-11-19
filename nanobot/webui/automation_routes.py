from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from loguru import logger
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.cron.binding import CronBindingError, binding_revision
from nanobot.cron.session_turns import is_bound_cron_job
from nanobot.cron.types import CronJob, CronSchedule
from nanobot.triggers.local_types import LocalTrigger
from nanobot.webui.automation_chats import AutomationChat, automation_chats
from nanobot.webui.automation_results import cron_run_response, trigger_run_response
from nanobot.webui.http_utils import http_error as _http_error
from nanobot.webui.http_utils import http_json_response as _http_json_response
from nanobot.webui.http_utils import parse_query as _parse_query
from nanobot.webui.http_utils import query_first as _query_first
from nanobot.webui.mutation import MutationResult
from nanobot.webui.session_automations import (
    all_automations_payload,
    session_automation_jobs,
    session_automations_payload,
)
from nanobot.webui.settings_contracts import MutationParams
from nanobot.webui.settings_contracts import query_first as _mutation_text

if TYPE_CHECKING:
    from nanobot.cron.service import CronService
    from nanobot.session.manager import SessionManager
    from nanobot.triggers.local_store import LocalTriggerStore
    from nanobot.webui.workspaces import WebUIWorkspaceController


class WebUIAutomationRoutes:
    """Own automation reads, WebSocket writes, and session-deletion integration."""

    def __init__(
        self,
        *,
        session_manager: SessionManager | None,
        workspaces: WebUIWorkspaceController,
        cron_service: CronService | None,
        local_trigger_store: LocalTriggerStore | None,
        cron_pending_job_ids: Callable[[str], set[str]] | None,
        local_trigger_pending_ids: Callable[[str], set[str]] | None,
        channel_runtime_status: Callable[[], dict[str, Any]] | None,
        log: Any = logger,
    ) -> None:
        self.session_manager = session_manager
        self.workspaces = workspaces
        self.cron_service = cron_service
        self.local_trigger_store = local_trigger_store
        self.cron_pending_job_ids = cron_pending_job_ids
        self.local_trigger_pending_ids = local_trigger_pending_ids
        self.channel_runtime_status = channel_runtime_status
        self._log = log

    async def dispatch_read(
        self, request: WsRequest, path: str, authorize: Callable[[WsRequest], bool],
    ) -> Response | None:
        if path not in {"/api/webui/automations", "/api/webui/automations/result", "/api/webui/automations/chats"}:
            return None
        if not authorize(request):
            return _http_error(401, "Unauthorized")
        if path == "/api/webui/automations/result":
            return await self._handle_webui_automation_result(request)
        if path == "/api/webui/automations/chats":
            return await self._handle_webui_automation_chats(request)
        return _http_json_response(self._automations_payload())

    def session_payload(self, key: str) -> dict[str, Any]:
        return session_automations_payload(
            self.cron_service,
            key,
            local_trigger_store=self.local_trigger_store,
            session_manager=self.session_manager,
            pending_job_ids=self._pending_automation_ids_for_session(key),
        )

    def session_jobs(self, key: str) -> list[CronJob | LocalTrigger]:
        return session_automation_jobs(self.cron_service, key, local_trigger_store=self.local_trigger_store)

    async def remove_session_jobs(self, jobs: list[CronJob | LocalTrigger]) -> None:
        for job in jobs:
            if isinstance(job, LocalTrigger):
                if self.local_trigger_store is not None:
                    await asyncio.to_thread(self.local_trigger_store.delete, job.id)
            elif self.cron_service is not None:
                self.cron_service.remove_job(job.id)

    def _pending_cron_job_ids_for_all(self) -> set[str]:
        if self.cron_service is None or self.cron_pending_job_ids is None:
            return set()
        pending: set[str] = set()
        for job in self.cron_service.list_jobs(include_disabled=True):
            session_key = job.payload.session_key
            if not session_key and job.payload.origin_channel and job.payload.origin_chat_id:
                session_key = f"{job.payload.origin_channel}:{job.payload.origin_chat_id}"
            if session_key:
                pending.update(self.cron_pending_job_ids(session_key))
        return pending

    def _pending_local_trigger_ids_for_all(self) -> set[str]:
        if self.local_trigger_store is None or self.local_trigger_pending_ids is None:
            return set()
        pending: set[str] = set()
        for trigger in self.local_trigger_store.list_triggers(include_disabled=True):
            session_key = trigger.session_key
            if not session_key and trigger.channel and trigger.chat_id:
                session_key = f"{trigger.channel}:{trigger.chat_id}"
            if session_key:
                pending.update(self.local_trigger_pending_ids(session_key))
        return pending

    def _pending_automation_ids_for_session(self, session_key: str) -> set[str]:
        pending: set[str] = set()
        if self.cron_pending_job_ids is not None:
            pending.update(self.cron_pending_job_ids(session_key))
        if self.local_trigger_pending_ids is not None:
            pending.update(self.local_trigger_pending_ids(session_key))
        return pending

    def _automations_payload(self) -> dict[str, Any]:
        pending_job_ids = self._pending_cron_job_ids_for_all()
        pending_job_ids.update(self._pending_local_trigger_ids_for_all())
        return all_automations_payload(
            self.cron_service,
            local_trigger_store=self.local_trigger_store,
            session_manager=self.session_manager,
            pending_job_ids=pending_job_ids,
        )

    async def _automation_chats(self, job: CronJob) -> list[AutomationChat]:
        if self.session_manager is None:
            return []
        return await automation_chats(
            job, self.session_manager, self.workspaces,
            self.channel_runtime_status() if self.channel_runtime_status else {},
        )

    async def _handle_webui_automation_chats(self, request: WsRequest) -> Response:
        job_id = _query_first(_parse_query(request.path), "id") or ""
        job = self.cron_service.get_job(job_id) if self.cron_service else None
        if job is None or not is_bound_cron_job(job):
            return _http_error(404, "automation has no movable chat")
        chats = await self._automation_chats(job)
        current = next((chat for chat in chats
                        if chat.binding.session_key == job.payload.session_key), None)
        return _http_json_response({
            "revision": binding_revision(job),
            "current": current.public_payload() if current else None,
            "chats": [chat.public_payload() for chat in chats],
        })

    async def _handle_webui_automation_result(self, request: WsRequest) -> Response:
        query = _parse_query(request.path)
        job_id = (_query_first(query, "id") or "").strip()
        try:
            run_at_ms = int(_query_first(query, "run_at_ms") or "")
        except ValueError:
            return _http_error(400, "invalid run timestamp")
        if not job_id or run_at_ms < 0:
            return _http_error(400, "invalid automation run")
        kind = _query_first(query, "kind") or "cron"
        try:
            if kind == "local_trigger":
                trigger = self.local_trigger_store.get(job_id) if self.local_trigger_store else None
                if trigger is None or self.local_trigger_store is None:
                    return _http_error(404, "automation not found")
                deliveries = [item for item in trigger.run_history if item.run_at_ms == run_at_ms]
                if len(deliveries) != 1:
                    return _http_error(404, "run not found")
                response = await asyncio.to_thread(
                    trigger_run_response, self.local_trigger_store.runs_dir, trigger, deliveries[0],
                )
            elif kind == "cron":
                job = self.cron_service.get_job(job_id) if self.cron_service else None
                if job is None or self.cron_service is None:
                    return _http_error(404, "automation not found")
                if job.payload.kind == "system_event":
                    return _http_error(403, "system automation is protected")
                runs = [item for item in job.state.run_history if item.run_at_ms == run_at_ms]
                if len(runs) != 1:
                    return _http_error(404, "run not found")
                response = await asyncio.to_thread(
                    cron_run_response, self.cron_service.store_path.parent / "runs", job, runs[0],
                )
            else:
                return _http_error(400, "invalid automation kind")
        except OSError:
            self._log.exception("Could not read automation run result")
            return _http_error(500, "Could not read run result")
        return _http_json_response({"response": response})

    async def mutate(
        self,
        params: MutationParams,
        action: str,
    ) -> MutationResult:
        if self.cron_service is None and self.local_trigger_store is None:
            return MutationResult.failure(503, "automation service unavailable")

        job_id = (_mutation_text(params, "id") or _mutation_text(params, "job_id") or "").strip()
        if not job_id:
            return MutationResult.failure(400, "missing automation id")
        trigger = self.local_trigger_store.get(job_id) if self.local_trigger_store else None
        if trigger is not None:
            return self._handle_local_trigger_action(params, action, trigger)

        if self.cron_service is None:
            return MutationResult.failure(404, "automation not found")
        job = self.cron_service.get_job(job_id)
        if job is None:
            return MutationResult.failure(404, "automation not found")
        if job.payload.kind == "system_event":
            return MutationResult.failure(403, "system automation is protected")
        if action in {"enable", "run"} and not is_bound_cron_job(job):
            return MutationResult.failure(409, "automation has no linked chat")

        if action == "enable":
            if self.cron_service.enable_job(job_id, enabled=True) is None:
                return MutationResult.failure(404, "automation not found")
        elif action == "disable":
            if self.cron_service.enable_job(job_id, enabled=False) is None:
                return MutationResult.failure(404, "automation not found")
        elif action == "delete":
            result = self.cron_service.remove_job(job_id)
            if result == "not_found":
                return MutationResult.failure(404, "automation not found")
            if result == "protected":
                return MutationResult.failure(403, "system automation is protected")
        elif action == "run":
            if not job.enabled:
                return MutationResult.failure(409, "automation is disabled")
            task = asyncio.create_task(self.cron_service.run_job(job_id, force=False))
            task.add_done_callback(self._log_automation_run_result)
        elif action == "change-chat":
            values = _automation_values(params.values)
            if (not isinstance(values, dict)
                    or set(values) != {"target_id", "revision", "message"}
                    or not all(isinstance(v, str) for v in values.values())):
                return MutationResult.failure(400, "invalid automation chat payload")
            if job.id in self._pending_cron_job_ids_for_all():
                return MutationResult.failure(409, "automation_chat_busy")
            target = next((chat for chat in await self._automation_chats(job)
                           if chat.id == values["target_id"]), None)
            if target is None or not target.available:
                return MutationResult.failure(409, "automation_chat_unavailable")
            if target.binding.session_key == job.payload.session_key:
                return MutationResult.failure(400, "choose a different chat")
            try:
                self.cron_service.change_binding(
                    job_id, revision=values["revision"], binding=target.binding,
                    message=values["message"],
                )
            except CronBindingError as exc:
                return MutationResult.failure(409, f"automation_chat_{exc.reason}")
            except OSError:
                logger.exception("WebUI automation chat save failed")
                return MutationResult.failure(500, "could not save the chat; try again")
        elif action == "update":
            values = _automation_values(params.values)
            if values is None:
                return MutationResult.failure(400, "invalid automation update payload")
            parsed = _parse_automation_update(values, current_job=job)
            if isinstance(parsed, str):
                return MutationResult.failure(400, parsed)
            try:
                result = self.cron_service.update_job(job_id, **parsed)
            except ValueError as exc:
                return MutationResult.failure(400, str(exc))
            if result == "not_found":
                return MutationResult.failure(404, "automation not found")
            if result == "protected":
                return MutationResult.failure(403, "system automation is protected")
        else:
            return MutationResult.failure(404, "unknown automation action")

        return MutationResult.success(self._automations_payload())

    def _handle_local_trigger_action(
        self,
        params: MutationParams,
        action: str,
        trigger: LocalTrigger,
    ) -> MutationResult:
        if self.local_trigger_store is None:
            return MutationResult.failure(503, "trigger service unavailable")
        if action == "enable":
            if self.local_trigger_store.enable(trigger.id, enabled=True) is None:
                return MutationResult.failure(404, "automation not found")
        elif action == "disable":
            if self.local_trigger_store.enable(trigger.id, enabled=False) is None:
                return MutationResult.failure(404, "automation not found")
        elif action == "delete":
            if not self.local_trigger_store.delete(trigger.id):
                return MutationResult.failure(404, "automation not found")
        elif action == "run":
            return MutationResult.failure(409, "local trigger requires a CLI message")
        elif action == "update":
            values = _automation_values(params.values)
            if values is None:
                return MutationResult.failure(400, "invalid automation update payload")
            parsed = _parse_local_trigger_update(values)
            if isinstance(parsed, str):
                return MutationResult.failure(400, parsed)
            if parsed:
                if self.local_trigger_store.update(trigger.id, **parsed) is None:
                    return MutationResult.failure(404, "automation not found")
        else:
            return MutationResult.failure(404, "unknown automation action")

        return MutationResult.success(self._automations_payload())

    @staticmethod
    def _log_automation_run_result(task: asyncio.Task[bool]) -> None:
        try:
            ran = task.result()
        except Exception:
            logger.exception("WebUI automation run-now task failed")
            return
        if not ran:
            logger.warning("WebUI automation run-now task did not execute")


def _automation_values(payload: dict[str, Any]) -> dict[str, Any] | None:
    if "values" not in payload:
        return {}
    values = payload.get("values")
    return cast(dict[str, Any], values) if isinstance(values, dict) else None


def _parse_automation_update(
    values: dict[str, Any],
    *,
    current_job: CronJob | None = None,
) -> dict[str, Any] | str:
    update: dict[str, Any] = {}
    if "name" in values:
        raw_name = values.get("name")
        if not isinstance(raw_name, str):
            return "name must be a string"
        name = raw_name.strip()
        if not name:
            return "name cannot be empty"
        update["name"] = name
    if "message" in values:
        raw_message = values.get("message")
        if not isinstance(raw_message, str):
            return "message must be a string"
        message = raw_message.strip()
        if not message:
            return "message cannot be empty"
        update["message"] = message
    if "schedule" in values:
        raw_schedule = values.get("schedule")
        if not isinstance(raw_schedule, dict):
            return "schedule must be an object"
        parsed_schedule = _parse_automation_schedule(cast(dict[str, Any], raw_schedule))
        if isinstance(parsed_schedule, str):
            return parsed_schedule
        if current_job is not None and _schedule_matches_job(parsed_schedule, current_job):
            return update
        schedule_error = _validate_automation_schedule(parsed_schedule)
        if schedule_error:
            return schedule_error
        update["schedule"] = parsed_schedule
        update["delete_after_run"] = parsed_schedule.kind == "at"
    return update


def _parse_local_trigger_update(values: dict[str, Any]) -> dict[str, Any] | str:
    update: dict[str, Any] = {}
    if "name" in values:
        raw_name = values.get("name")
        if not isinstance(raw_name, str):
            return "name must be a string"
        name = raw_name.strip()
        if not name:
            return "name cannot be empty"
        update["name"] = name
    forbidden = [key for key in ("message", "schedule") if key in values]
    if forbidden:
        return "local trigger updates only support name"
    return update


def _parse_automation_schedule(values: dict[str, Any]) -> CronSchedule | str:
    raw_kind = values.get("kind")
    if not isinstance(raw_kind, str):
        return "schedule kind must be a string"
    kind = raw_kind.strip()
    if kind == "every":
        every_ms = _positive_int(values.get("every_ms"))
        if every_ms is None:
            return "every schedule requires positive every_ms"
        return CronSchedule(kind="every", every_ms=every_ms)
    if kind == "cron":
        raw_expr = values.get("expr")
        if not isinstance(raw_expr, str):
            return "cron schedule requires expr"
        expr = raw_expr.strip()
        if not expr:
            return "cron schedule requires expr"
        raw_tz = values.get("tz")
        if raw_tz is not None and not isinstance(raw_tz, str):
            return "cron schedule timezone must be a string"
        tz = raw_tz.strip() if isinstance(raw_tz, str) else ""
        return CronSchedule(kind="cron", expr=expr, tz=tz or None)
    if kind == "at":
        at_ms = _positive_int(values.get("at_ms"))
        if at_ms is None:
            return "one-time schedule requires positive at_ms"
        return CronSchedule(kind="at", at_ms=at_ms)
    return "unknown schedule kind"


def _schedule_matches_job(schedule: CronSchedule, job: CronJob) -> bool:
    current = job.schedule
    if schedule.kind != current.kind:
        return False
    if schedule.kind == "at":
        return schedule.at_ms == current.at_ms
    if schedule.kind == "every":
        return schedule.every_ms == current.every_ms
    if schedule.kind == "cron":
        return (schedule.expr or "") == (current.expr or "") and (
            schedule.tz or None
        ) == (current.tz or None)
    return False


def _validate_automation_schedule(schedule: CronSchedule) -> str | None:
    if schedule.kind == "at":
        if not schedule.at_ms or schedule.at_ms <= int(time.time() * 1000):
            return "one-time schedule must be in the future"
        return None
    if schedule.kind != "cron":
        return None

    try:
        tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
    except (ZoneInfoNotFoundError, ValueError):
        return "cron schedule timezone is invalid"
    try:
        croniter(cast(str, schedule.expr), datetime.now(tz=tz)).get_next(datetime)
    except ValueError:
        return "cron schedule is invalid"
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None
