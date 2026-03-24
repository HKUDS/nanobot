from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from . import board, mailbox
from .state import Task, TeamRuntime, TeamState, Teammate
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ExecToolConfig, WebSearchConfig
from nanobot.providers.base import LLMProvider
from nanobot.session.manager import Session, SessionManager
from nanobot.utils.helpers import ensure_dir, parse_json_from_llm, safe_filename, timestamp


class TeamManager:
    """Session-scoped nano team runtime."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        sessions: SessionManager,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
        web_search_config: "WebSearchConfig | None" = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        restrict_to_workspace: bool = False,
        max_workers: int = 5,
        worker_max_iterations: int = 25,
    ):
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.sessions = sessions
        self.model = model or provider.get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.web_search_config = web_search_config or WebSearchConfig()
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self.max_workers = max_workers
        self.worker_max_iterations = worker_max_iterations
        self.teams_dir = ensure_dir(workspace / "teams")

        self._active_by_session: dict[str, TeamRuntime] = {}
        self._runtime_lock = asyncio.Lock()
        self._worker_semaphore = asyncio.Semaphore(max_workers)

    # ------------------------------------------------------------------
    # Context/session helpers
    # ------------------------------------------------------------------
    def is_active(self, session_key: str) -> bool:
        rt = self._active_by_session.get(session_key)
        return rt is not None and rt.state.status != "completed"

    def has_unfinished_run(self, session_key: str) -> bool:
        if self.is_active(session_key):
            return True
        latest = self._latest_unfinished_dir(session_key)
        return latest is not None

    def has_active_team(self, session_key: str) -> bool:
        return self._runtime(session_key) is not None

    def active_team_id(self, session_key: str) -> str | None:
        runtime = self._runtime(session_key)
        return runtime.state.team_id if runtime else None

    def get_team_dir(self, session_key: str) -> Path | None:
        runtime = self._runtime(session_key)
        return runtime.run_dir if runtime else None

    def get_team_state(self, session_key: str) -> TeamState | None:
        runtime = self._runtime(session_key)
        return runtime.state if runtime else None

    def _session_dir(self, session_key: str) -> Path:
        return ensure_dir(self.teams_dir / safe_filename(session_key))

    def _runtime(self, session_key: str, auto_attach: bool = False) -> TeamRuntime | None:
        runtime = self._active_by_session.get(session_key)
        if runtime and runtime.state.status != "completed":
            return runtime
        if auto_attach:
            return self._auto_attach(session_key)
        return None

    def _latest_unfinished_dir(self, session_key: str) -> Path | None:
        base = self._session_dir(session_key)
        runs = [p for p in base.iterdir() if p.is_dir()]
        runs.sort(key=lambda p: p.name, reverse=True)
        for run_dir in runs:
            cfg = run_dir / "config.json"
            if not cfg.exists():
                continue
            try:
                state = TeamState.load(cfg)
            except Exception:
                continue
            if state.status != "completed":
                return run_dir
        return None

    def _auto_attach(self, session_key: str) -> TeamRuntime | None:
        if session_key in self._active_by_session:
            return self._active_by_session[session_key]
        run_dir = self._latest_unfinished_dir(session_key)
        if not run_dir:
            return None
        state = TeamState.load(run_dir / "config.json")
        if state.status == "completed":
            return None
        state.status = "active"
        state.save(run_dir / "config.json")
        runtime = TeamRuntime(session_key=session_key, run_dir=run_dir, state=state)
        self._active_by_session[session_key] = runtime
        for mate in state.members:
            if mate.status != "stopped":
                self._ensure_worker(runtime, mate.name)
        self._append_event(runtime, "team_auto_attach", f"Auto-attached run {state.run_id}")
        return runtime

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------
    def _append_event(self, runtime: TeamRuntime, kind: str, message: str, **extra: Any) -> None:
        ensure_dir(runtime.run_dir)
        record = {
            "ts": timestamp(),
            "kind": kind,
            "message": message,
        }
        if extra:
            record["data"] = extra
        with open(runtime.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def _emit_lead_update(self, runtime: TeamRuntime, text: str) -> None:
        channel, chat_id = runtime.session_key.split(":", 1) if ":" in runtime.session_key else ("cli", runtime.session_key)
        if channel == "cli":
            # In CLI team mode, keep team updates inside the board/event stream.
            self._append_event(runtime, "lead_user_sync", text)
            return
        await self.bus.publish_outbound(OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=text,
            metadata={"team_event": True},
        ))

    def log_text(self, session_key: str, n: int = 20) -> str:
        runtime = self._runtime(session_key, auto_attach=True)
        if not runtime:
            return "No team logs."
        if not runtime.events_path.exists():
            return "No team logs."
        lines = runtime.events_path.read_text(encoding="utf-8").splitlines()[-n:]
        rendered: list[str] = []
        for line in lines:
            try:
                row = json.loads(line)
            except Exception:
                continue
            rendered.append(f"- [{row.get('ts', '?')}] {row.get('kind', 'event')}: {row.get('message', '')}")
        return "\n".join(rendered) or "No team logs."

    def status_text(self, session_key: str) -> str:
        runtime = self._runtime(session_key, auto_attach=True)
        if not runtime:
            return "No active nano team. Start with `/team <goal>`."
        tasks = board.load(runtime.run_dir)
        members = board.member_rows(tasks, runtime.state.members)
        completed = sum(1 for t in tasks if t.status == "completed")
        active = sum(1 for t in tasks if t.status in {"planning", "in_progress"})
        pending_approval = sum(1 for t in tasks if t.status == "awaiting_approval")
        recent = self._recent_updates(runtime, n=2)
        member_text = ", ".join(f"{m['name']}={m['status']}" for m in members) or "none"
        approvals = [a["id"] for a in board.approval_rows(tasks)]
        lines = [
            f"Team `{runtime.state.team_id}` · {runtime.state.status}",
            f"Mission: {runtime.state.mission or '(none)'}",
            f"Members: {member_text}",
            f"Tasks: {completed}/{len(tasks)} completed · {active} active · {pending_approval} awaiting approval",
        ]
        if approvals:
            lines.append(f"Approval queue: {', '.join(approvals[:5])}")
            lines.append("Approve with `/team approve <id>` or `/team reject <id> <reason>`.")
        if recent:
            lines.append(f"Recent: {recent[-1]}")
        return "\n".join(lines)

    def _snapshot_text(self, runtime: TeamRuntime) -> str:
        tasks = board.load(runtime.run_dir)
        members = board.member_rows(tasks, runtime.state.members)
        header = (
            f"## Team: {runtime.state.team_id}\n"
            f"- Mission: {runtime.state.mission or '(none)'}\n"
            f"- Run ID: {runtime.state.run_id}\n"
            f"- Status: {runtime.state.status}\n"
        )
        member_lines = "\n".join(
            f"- {m['name']} ({m['role']}): {m['status']} | {m['task']}"
            for m in members
        ) or "- none"
        return f"{header}\n### Members\n{member_lines}\n\n{board.render_text(tasks, runtime.state.members)}"

    # ------------------------------------------------------------------
    # Public nano-team mode API
    # ------------------------------------------------------------------
    async def start_or_route_goal(self, session_key: str, goal: str) -> str:
        async with self._runtime_lock:
            runtime = self._runtime(session_key, auto_attach=True)
            if runtime:
                return await self._route_instruction(runtime, goal, source="team_command")

            normalized = await self._build_initial_plan(goal)
            runtime = self._create_runtime_from_plan(session_key, normalized)
            self._active_by_session[session_key] = runtime
            self._append_event(runtime, "team_started", f"Started nano team for goal: {goal}")
            for mate in runtime.state.members:
                self._ensure_worker(runtime, mate.name)
            await self._emit_lead_update(
                runtime,
                f"Team lead: started `{runtime.state.team_id}` with {len(runtime.state.members)} workers for `{goal}`.",
            )
            return (
                f"Nano team started: `{runtime.state.team_id}` ({len(runtime.state.members)} workers).\n"
                f"Use `/team status`, `/team log`, `/team stop`."
            )

    async def route_user_message(self, session_key: str, message: str) -> str:
        async with self._runtime_lock:
            runtime = self._runtime(session_key, auto_attach=True)
            if not runtime:
                return "No active nano team. Start with `/team <goal>`."
            return await self._route_instruction(runtime, message, source="plain_message")

    async def stop_mode(self, session_key: str, *, with_snapshot: bool = False) -> str:
        async with self._runtime_lock:
            runtime = self._runtime(session_key)
            if not runtime:
                return "No active team."
            if with_snapshot:
                tasks = board.load(runtime.run_dir)
                completed = sum(1 for t in tasks if t.status == "completed")
                total = len(tasks)
                awaiting = sum(1 for t in tasks if t.status == "awaiting_approval")
                in_progress = sum(1 for t in tasks if t.status in {"planning", "in_progress"})
                summary = (
                    f"Completed {completed}/{total} tasks, "
                    f"{in_progress} in progress, {awaiting} awaiting approval."
                )
                self._append_event(runtime, "team_final_summary", summary)
            await self._stop_runtime(runtime)
            self._active_by_session.pop(session_key, None)
            if not with_snapshot:
                return f"Team `{runtime.state.team_id}` stopped."
            snapshot = self._snapshot_text(runtime)
            updates = self._recent_updates(runtime, n=6)
            update_lines = "\n".join(f"- {u}" for u in updates) or "- (no recent updates)"
            return (
                f"{snapshot}\n\n"
                "### Team Lead Final Summary\n"
                f"- {summary}\n\n"
                "### Recent Updates\n"
                f"{update_lines}"
            )

    # ------------------------------------------------------------------
    # Compatibility API for CLI panel and command handlers
    # ------------------------------------------------------------------
    async def create(
        self,
        session_key: str,
        team_id: str,
        members: list[dict],
        tasks: list[dict],
        notes: str = "",
        mission: str = "",
    ) -> str:
        async with self._runtime_lock:
            if self._runtime(session_key):
                return "Error: active team already exists for this session"
            payload = {
                "mission": mission or team_id,
                "members": members,
                "tasks": tasks,
                "notes": notes,
            }
            normalized, err = self._validate_plan_payload(payload, mission or team_id)
            if err:
                return f"Error: {err}"
            runtime = self._create_runtime_from_plan(session_key, normalized, team_id=team_id)
            self._active_by_session[session_key] = runtime
            self._append_event(runtime, "team_created", "Created team via internal tool")
            for mate in runtime.state.members:
                self._ensure_worker(runtime, mate.name)
            return f"Team '{runtime.state.team_id}' started with {len(runtime.state.members)} teammates."

    async def resume(self, session_key: str, team_id: str) -> str:
        async with self._runtime_lock:
            if self._runtime(session_key):
                return "Error: active team already exists for this session"
            base = self._session_dir(session_key)
            for run_dir in sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True):
                cfg = run_dir / "config.json"
                if not cfg.exists():
                    continue
                state = TeamState.load(cfg)
                if state.team_id == team_id or state.run_id == team_id:
                    state.status = "active"
                    state.save(cfg)
                    runtime = TeamRuntime(session_key=session_key, run_dir=run_dir, state=state)
                    self._active_by_session[session_key] = runtime
                    for mate in state.members:
                        if mate.status != "stopped":
                            self._ensure_worker(runtime, mate.name)
                    self._append_event(runtime, "team_resumed", f"Resumed team {team_id}")
                    return f"Resumed team '{state.team_id}'."
            return f"Error: team '{team_id}' not found"

    async def cancel_by_session(self, session_key: str) -> int:
        async with self._runtime_lock:
            runtime = self._runtime(session_key)
            if not runtime:
                return 0
            count = await self._cancel_worker_tasks(runtime)
            runtime.state.status = "paused"
            runtime.state.save(runtime.run_dir / "config.json")
            self._append_event(runtime, "team_cancelled", f"Cancelled {count} worker tasks")
            self._active_by_session.pop(session_key, None)
            return count

    async def message_worker(self, session_key: str, to: str, content: str) -> str:
        runtime = self._runtime(session_key)
        if not runtime:
            return "Error: no active team"
        result = mailbox.send(runtime.run_dir, "lead", to, content)
        self._append_event(runtime, "lead_message", f"Lead -> {to}: {content[:120]}")
        self._ensure_worker(runtime, to)
        return result

    def render_board(self, session_key: str) -> str:
        runtime = self._runtime(session_key)
        if not runtime:
            return "No active team."
        tasks = board.load(runtime.run_dir)
        text = board.render_text(tasks, runtime.state.members)
        recent = mailbox.render_recent(runtime.run_dir)
        return f"## Team: {runtime.state.team_id}\n\n{text}\n\n## Recent Messages\n{recent}"

    def list_members(self, session_key: str) -> list[str]:
        runtime = self._runtime(session_key)
        if not runtime:
            return []
        return [runtime.state.lead] + [m.name for m in runtime.state.members]

    def get_member_snapshot(self, session_key: str, name: str) -> dict[str, Any] | None:
        runtime = self._runtime(session_key)
        if not runtime:
            return None
        if name == runtime.state.lead:
            return {
                "name": runtime.state.lead,
                "role": "team leader",
                "status": "active",
                "task": None,
                "recent_messages": mailbox.recent_for(runtime.run_dir, runtime.state.lead),
            }
        mate = next((m for m in runtime.state.members if m.name == name), None)
        if not mate:
            return None
        current = board.get_current(runtime.run_dir, name)
        task = None if not current else {
            "id": current.id,
            "title": current.title,
            "status": current.status,
            "plan": current.plan or "",
            "result": current.result or "",
        }
        return {
            "name": mate.name,
            "role": mate.role,
            "status": mate.status,
            "task": task,
            "recent_messages": mailbox.recent_for(runtime.run_dir, name),
        }

    def get_board_snapshot(self, session_key: str) -> dict[str, Any] | None:
        runtime = self._runtime(session_key)
        if not runtime:
            return None
        tasks = board.load(runtime.run_dir)
        worker_rows = board.member_rows(tasks, runtime.state.members)
        approval_rows = board.approval_rows(tasks)
        recent_lead = mailbox.recent_for(runtime.run_dir, runtime.state.lead, n=1)
        lead_action = f"msg -> {recent_lead[-1].to_agent}" if recent_lead else "coordinating"
        lead_row = {"name": runtime.state.lead, "role": "team leader", "status": "active", "task": lead_action}
        return {
            "team_id": runtime.state.team_id,
            "status": runtime.state.status,
            "members": [lead_row] + worker_rows,
            "tasks": board.task_rows(tasks),
            "approvals": approval_rows,
            "approval_focus": approval_rows[0] if approval_rows else None,
            "recent_messages": mailbox.recent(runtime.run_dir),
            "recent_updates": self._recent_updates(runtime),
        }

    def add_task(self, session_key: str, task: dict[str, Any]) -> str:
        runtime = self._runtime(session_key)
        if not runtime:
            return "Error: no active team"
        task = dict(task)
        task.setdefault("id", self._next_task_id(runtime))
        result = board.add_task(runtime.run_dir, Task(**task))
        self._append_event(runtime, "task_added", f"Added task {task['id']}: {task.get('title', '')}")
        if owner := task.get("owner"):
            self._ensure_worker(runtime, owner)
        return result

    def has_pending_approval(self, session_key: str) -> bool:
        runtime = self._runtime(session_key, auto_attach=True)
        if not runtime:
            return False
        return any(t.status == "awaiting_approval" for t in board.load(runtime.run_dir))

    def approve_for_session(self, session_key: str, task_id: str) -> str:
        runtime = self._runtime(session_key, auto_attach=True)
        if not runtime:
            return "Error: no active team"
        result = board.approve(runtime.run_dir, task_id)
        if result.startswith("Error:"):
            return result
        task = next((t for t in board.load(runtime.run_dir) if t.id == task_id), None)
        if task and task.owner:
            self._ensure_worker(runtime, task.owner)
        runtime.prompted_approvals.discard(task_id)
        self._append_event(runtime, "task_approved", f"Approved task {task_id}")
        return result

    def reject_for_session(self, session_key: str, task_id: str, reason: str) -> str:
        runtime = self._runtime(session_key, auto_attach=True)
        if not runtime:
            return "Error: no active team"
        result = board.reject(runtime.run_dir, task_id, reason)
        if result.startswith("Error:"):
            return result
        runtime.prompted_approvals.discard(task_id)
        self._append_event(runtime, "task_rejected", f"Rejected task {task_id}: {reason[:100]}")
        return result

    def request_changes_for_session(self, session_key: str, task_id: str, instruction: str) -> str:
        runtime = self._runtime(session_key, auto_attach=True)
        if not runtime:
            return "Error: no active team"
        result = board.reject(runtime.run_dir, task_id, instruction)
        if result.startswith("Error:"):
            return result
        task = next((t for t in board.load(runtime.run_dir) if t.id == task_id), None)
        if task and task.owner:
            mailbox.send(runtime.run_dir, runtime.state.lead, task.owner, f"Please revise {task_id}: {instruction}")
            self._ensure_worker(runtime, task.owner)
        runtime.prompted_approvals.discard(task_id)
        self._append_event(runtime, "task_change_requested", f"Requested changes on {task_id}: {instruction[:100]}")
        return f"Requested changes for {task_id}."

    @staticmethod
    def _extract_task_id(text: str, pending_ids: list[str]) -> str | None:
        matched = re.search(r"\b[tT]\d+\b", text)
        if matched and matched.group(0).lower() in {p.lower() for p in pending_ids}:
            candidate = matched.group(0).lower()
            for tid in pending_ids:
                if tid.lower() == candidate:
                    return tid
        if len(pending_ids) == 1:
            return pending_ids[0]
        return None

    @staticmethod
    def _clean_feedback(text: str, task_id: str) -> str:
        cleaned = text
        cleaned = re.sub(rf"\b{re.escape(task_id)}\b", "", cleaned, flags=re.IGNORECASE)
        for token in (
            "批准", "同意", "通过", "approve", "approved",
            "拒绝", "驳回", "reject", "decline",
            "补充", "调整", "修改", "指示", "manual", "change",
        ):
            cleaned = re.sub(token, "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" \t\r\n:：,，.。")

    def handle_approval_reply(self, session_key: str, text: str) -> str | None:
        runtime = self._runtime(session_key, auto_attach=True)
        if not runtime:
            return None
        tasks = board.load(runtime.run_dir)
        pending = [t for t in tasks if t.status == "awaiting_approval"]
        if not pending:
            return None
        pending_ids = [t.id for t in pending]
        task_id = self._extract_task_id(text, pending_ids)
        if not task_id:
            return (
                "I found pending approvals but couldn't map your reply to a task. "
                f"Pending: {', '.join(pending_ids)}. Please mention the task id in natural language."
            )
        lowered = text.lower()
        approve_hit = any(k in lowered for k in ("批准", "同意", "通过", "approve", "approved", "accept", "ok"))
        reject_hit = any(k in lowered for k in ("拒绝", "驳回", "reject", "decline"))
        manual_hit = any(k in lowered for k in ("补充", "调整", "修改", "指示", "manual", "change", "revise"))
        if approve_hit and not reject_hit:
            return self.approve_for_session(session_key, task_id)
        feedback = self._clean_feedback(text, task_id)
        if reject_hit and not manual_hit:
            if not feedback:
                return "I can reject it, but I still need a reason in natural language."
            return self.reject_for_session(session_key, task_id, feedback)
        if manual_hit or reject_hit:
            if not feedback:
                return "I can send change instructions, but I still need your guidance text."
            return self.request_changes_for_session(session_key, task_id, feedback)
        return (
            "I detected approval context but couldn't infer intent. "
            "Reply naturally with approve/reject/change + task id."
        )

    # ------------------------------------------------------------------
    # Planning and instruction routing
    # ------------------------------------------------------------------
    async def _route_instruction(self, runtime: TeamRuntime, instruction: str, source: str) -> str:
        normalized = instruction.strip()
        if not normalized:
            return "Please provide an instruction."

        if self._looks_risky(normalized) and not normalized.lower().startswith("confirm "):
            runtime.state.status = "paused"
            runtime.state.save(runtime.run_dir / "config.json")
            self._append_event(runtime, "risk_gate", f"Paused risky instruction: {normalized[:140]}")
            return (
                "Risk gate paused this instruction because it may be destructive.\n"
                "Re-send with `/team confirm <instruction>` to continue."
            )

        if normalized.lower().startswith("confirm "):
            normalized = normalized[8:].strip()
            runtime.state.status = "active"
            runtime.state.save(runtime.run_dir / "config.json")

        task_specs = await self._build_incremental_tasks(runtime, normalized)
        created: list[str] = []
        for spec in task_specs:
            task = Task(
                id=self._next_task_id(runtime),
                title=spec["title"],
                description=spec.get("description", ""),
                owner=spec.get("owner"),
                depends_on=spec.get("depends_on", []),
                requires_approval=False,
            )
            board.add_task(runtime.run_dir, task)
            created.append(task.id)
            self._append_event(runtime, "task_added", f"{task.id}: {task.title}", source=source)
            if task.owner:
                self._ensure_worker(runtime, task.owner)

        mailbox.broadcast(runtime.run_dir, runtime.state.lead, f"New instruction: {normalized}")
        for mate in runtime.state.members:
            self._ensure_worker(runtime, mate.name)

        self._append_lead_session(runtime, normalized, f"Queued {len(created)} tasks: {', '.join(created)}")
        await self._emit_lead_update(
            runtime,
            f"Team lead: queued {len(created)} task(s) from your instruction.",
        )
        return f"Queued {len(created)} task(s): {', '.join(created)}."

    async def _build_initial_plan(self, goal: str) -> dict[str, Any]:
        prompt = (
            "You are planning a tiny execution team. Return strict JSON only.\n"
            "Schema:\n"
            "{"
            "\"mission\": string,"
            "\"members\": [{\"name\": string, \"role\": string, \"model\": string?}],"
            "\"tasks\": [{\"id\": string, \"title\": string, \"description\": string, \"owner\": string?, \"depends_on\": [string]?, \"requires_approval\": boolean?}],"
            "\"notes\": string"
            "}\n"
            "Rules: 2-3 members only. Tasks must be actionable and coherent."
        )
        repair_error = ""
        for _ in range(2):
            user = f"Goal:\n{goal}"
            if repair_error:
                user += f"\n\nPrevious output error: {repair_error}\nFix and output valid JSON only."
            response = await self.provider.chat_with_retry(
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                model=self.model,
                max_tokens=min(self.max_tokens, 1400),
                temperature=0.1,
                reasoning_effort=self.reasoning_effort,
            )
            payload = parse_json_from_llm(response.content or "")
            if payload is None:
                repair_error = "Malformed JSON."
                continue
            normalized, err = self._validate_plan_payload(payload, goal)
            if not err:
                return normalized
            repair_error = err
        return self._fallback_plan(goal)

    async def _build_incremental_tasks(self, runtime: TeamRuntime, instruction: str) -> list[dict[str, Any]]:
        member_lines = "\n".join(f"- {m.name}: {m.role}" for m in runtime.state.members)
        current_tasks = board.task_rows(board.load(runtime.run_dir))
        prompt = (
            "You are a pragmatic team lead. Return strict JSON only.\n"
            "Schema: {\"tasks\": [{\"title\": string, \"description\": string, \"owner\": string?, \"depends_on\": [string]?}]}\n"
            "Keep it compact (1-3 tasks). Owner must be one of the listed members when provided."
        )
        user = (
            f"Mission: {runtime.state.mission}\n"
            f"Members:\n{member_lines}\n\n"
            f"Current tasks: {json.dumps(current_tasks[-12:], ensure_ascii=False)}\n\n"
            f"New instruction: {instruction}"
        )
        response = await self.provider.chat_with_retry(
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user}],
            model=self.model,
            max_tokens=min(self.max_tokens, 1000),
            temperature=0.1,
            reasoning_effort=self.reasoning_effort,
        )
        payload = parse_json_from_llm(response.content or "")
        members = {m.name for m in runtime.state.members}
        if not isinstance(payload, dict):
            return [{"title": instruction[:80], "description": instruction, "owner": None, "depends_on": []}]
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            return [{"title": instruction[:80], "description": instruction, "owner": None, "depends_on": []}]
        out: list[dict[str, Any]] = []
        for t in raw_tasks[:3]:
            if not isinstance(t, dict):
                continue
            title = str(t.get("title", "")).strip()
            if not title:
                continue
            owner = str(t.get("owner", "")).strip() or None
            if owner and owner not in members:
                owner = None
            deps = t.get("depends_on")
            if not isinstance(deps, list):
                deps = []
            out.append({
                "title": title,
                "description": str(t.get("description", "")).strip(),
                "owner": owner,
                "depends_on": [str(d).strip() for d in deps if str(d).strip()],
            })
        return out or [{"title": instruction[:80], "description": instruction, "owner": None, "depends_on": []}]

    def _create_runtime_from_plan(
        self,
        session_key: str,
        plan: dict[str, Any],
        team_id: str | None = None,
    ) -> TeamRuntime:
        session_dir = self._session_dir(session_key)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        while (session_dir / run_id).exists():
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_dir = ensure_dir(session_dir / run_id)
        state = TeamState(
            team_id=team_id or f"nano-{run_id[-6:]}",
            run_id=run_id,
            mission=plan.get("mission", ""),
            members=[Teammate(**m) for m in plan["members"]],
            status="active",
            session_key=session_key,
        )
        state.save(run_dir / "config.json")
        board.save(run_dir, [Task(**t) for t in plan["tasks"]])
        (run_dir / "NOTES.md").write_text(plan.get("notes", "# Team Notes\n"), encoding="utf-8")
        ensure_dir(run_dir / "workers")
        for m in state.members:
            ensure_dir(run_dir / "workers" / safe_filename(m.name))
        (run_dir / "events.jsonl").touch(exist_ok=True)
        return TeamRuntime(session_key=session_key, run_dir=run_dir, state=state)

    def _next_task_id(self, runtime: TeamRuntime) -> str:
        tasks = board.load(runtime.run_dir)
        max_idx = 0
        for t in tasks:
            m = re.match(r"t(\d+)$", t.id)
            if m:
                max_idx = max(max_idx, int(m.group(1)))
        return f"t{max_idx + 1}"

    def _validate_plan_payload(self, payload: dict[str, Any], goal: str = "") -> tuple[dict[str, Any] | None, str | None]:
        members_raw = payload.get("members")
        if not isinstance(members_raw, list):
            return None, "members must be a list"
        members: list[dict[str, Any]] = []
        seen_members: set[str] = set()
        for item in members_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            role = str(item.get("role", "")).strip()
            if not name or not role:
                continue
            key = name.lower()
            if key in seen_members:
                return None, "duplicate member names"
            seen_members.add(key)
            members.append({"name": name, "role": role, "model": item.get("model")})
        if len(members) < 2:
            return None, "at least 2 members are required"
        if len(members) > 3:
            members = members[:3]

        tasks_raw = payload.get("tasks")
        if not isinstance(tasks_raw, list) or not tasks_raw:
            return None, "tasks must be a non-empty list"
        member_names = {m["name"] for m in members}
        tasks: list[dict[str, Any]] = []
        seen_task_ids: set[str] = set()
        for idx, item in enumerate(tasks_raw, start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            task_id = str(item.get("id", f"t{idx}")).strip() or f"t{idx}"
            if task_id in seen_task_ids:
                return None, "duplicate task ids"
            seen_task_ids.add(task_id)
            owner = str(item.get("owner", "")).strip() or None
            if owner and owner not in member_names:
                owner = None
            deps_raw = item.get("depends_on")
            deps = [str(d).strip() for d in deps_raw] if isinstance(deps_raw, list) else []
            tasks.append({
                "id": task_id,
                "title": title,
                "description": str(item.get("description", "")).strip(),
                "owner": owner,
                "depends_on": [d for d in deps if d],
                "requires_approval": bool(item.get("requires_approval", False)),
            })
        if not tasks:
            return None, "no valid tasks found"
        task_ids = {t["id"] for t in tasks}
        for t in tasks:
            t["depends_on"] = [d for d in t["depends_on"] if d in task_ids]
        if self._has_cycle(tasks):
            return None, "task dependency graph has a cycle"
        mission = str(payload.get("mission", "")).strip() or goal or "Complete the requested mission."
        notes = str(payload.get("notes", "")).strip() or "# Team Notes\n"
        return {
            "mission": mission,
            "members": members,
            "tasks": tasks,
            "notes": notes,
        }, None

    @staticmethod
    def _has_cycle(tasks: list[dict[str, Any]]) -> bool:
        graph = {t["id"]: list(t.get("depends_on", [])) for t in tasks}
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node: str) -> bool:
            if node in visited:
                return False
            if node in visiting:
                return True
            visiting.add(node)
            for dep in graph.get(node, []):
                if dep in graph and dfs(dep):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(dfs(node) for node in graph)

    def _fallback_plan(self, goal: str) -> dict[str, Any]:
        return {
            "mission": goal,
            "members": [
                {"name": "researcher", "role": "research and analysis", "model": None},
                {"name": "builder", "role": "execution and synthesis", "model": None},
            ],
            "tasks": [
                {
                    "id": "t1",
                    "title": "Analyze the request",
                    "description": f"Break down the objective: {goal}",
                    "owner": "researcher",
                    "depends_on": [],
                    "requires_approval": False,
                },
                {
                    "id": "t2",
                    "title": "Execute and report",
                    "description": "Implement the solution and summarize concrete outcomes.",
                    "owner": "builder",
                    "depends_on": ["t1"],
                    "requires_approval": False,
                },
            ],
            "notes": "# Team Notes\n- Keep changes minimal and reliable.\n",
        }

    def _recent_updates(self, runtime: TeamRuntime, n: int = 4) -> list[str]:
        if not runtime.events_path.exists():
            return []
        lines = runtime.events_path.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except Exception:
                continue
            kind = str(row.get("kind", ""))
            if kind not in {
                "lead_user_sync",
                "worker_update",
                "risk_gate",
                "team_started",
                "team_stopped",
                "task_approved",
                "task_rejected",
                "task_change_requested",
            }:
                continue
            msg = str(row.get("message", "")).strip()
            if msg:
                out.append(msg)
            if len(out) >= n:
                break
        out.reverse()
        return out

    @staticmethod
    def _looks_risky(text: str) -> bool:
        lowered = text.lower()
        tokens = (
            "rm -rf",
            "delete",
            "drop table",
            "truncate",
            "reset --hard",
            "format disk",
            "wipe",
            "shutdown",
            "destroy",
        )
        return any(t in lowered for t in tokens)

    # ------------------------------------------------------------------
    # Worker runtime
    # ------------------------------------------------------------------
    def _set_member_status(self, runtime: TeamRuntime, name: str, status: str) -> None:
        for mate in runtime.state.members:
            if mate.name == name:
                mate.status = status
                break
        runtime.state.save(runtime.run_dir / "config.json")

    def _ensure_worker(self, runtime: TeamRuntime, name: str) -> None:
        running = runtime.worker_tasks.get(name)
        if running and not running.done():
            return
        mate = next((m for m in runtime.state.members if m.name == name), None)
        if not mate:
            return
        task = asyncio.create_task(self._run_worker(runtime.session_key, mate.name))
        runtime.worker_tasks[name] = task
        task.add_done_callback(lambda _t, key=runtime.session_key, worker=name: self._cleanup_worker(key, worker))

    def _cleanup_worker(self, session_key: str, worker: str) -> None:
        runtime = self._active_by_session.get(session_key)
        if not runtime:
            return
        runtime.worker_tasks.pop(worker, None)

    async def _cancel_worker_tasks(self, runtime: TeamRuntime) -> int:
        tasks = [t for t in runtime.worker_tasks.values() if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        runtime.worker_tasks.clear()
        return len(tasks)

    async def _stop_runtime(self, runtime: TeamRuntime) -> None:
        await self._cancel_worker_tasks(runtime)
        current_tasks = board.load(runtime.run_dir)
        completed = bool(current_tasks) and all(t.status == "completed" for t in current_tasks)
        runtime.state.status = "completed" if completed else "paused"
        for mate in runtime.state.members:
            mate.status = "stopped" if completed else "idle"
        runtime.state.save(runtime.run_dir / "config.json")
        self._append_event(runtime, "team_stopped", f"Stopped team with status {runtime.state.status}")

    def _build_worker_tools(self, runtime: TeamRuntime, mate: Teammate) -> "ToolRegistry":
        from nanobot.agent.tools.registry import build_base_tools

        tools = build_base_tools(
            workspace=self.workspace,
            exec_config=self.exec_config,
            web_search_config=self.web_search_config,
            web_proxy=self.web_proxy,
            restrict_to_workspace=self.restrict_to_workspace,
        )
        from .tools import TeamWorkerTool

        tools.register(TeamWorkerTool(manager=self, worker_name=mate.name, session_key=runtime.session_key))
        return tools

    def _build_worker_prompt(self, runtime: TeamRuntime, mate: Teammate) -> str:
        notes = (runtime.run_dir / "NOTES.md").read_text(encoding="utf-8") if (runtime.run_dir / "NOTES.md").exists() else ""
        roster = "\n".join(f"- {m.name}: {m.role}" for m in runtime.state.members)
        current = board.get_current(runtime.run_dir, mate.name)
        current_text = f"{current.id} - {current.title} ({current.status})" if current else "No current task."
        return f"""# Team Worker

You are teammate '{mate.name}'.
Role: {mate.role}

## Team Members
{roster}

## Shared Notes
{notes or "(empty)"}

## Current Task
{current_text}

Use the `team_worker` tool to inspect the board, claim tasks, submit plans, complete tasks, and message teammates.
Work autonomously and coordinate through the board and mailbox."""

    def _save_worker_session(self, session: Session, messages: list[dict], skip: int) -> None:
        for m in messages[skip:]:
            entry = dict(m)
            if entry.get("role") == "assistant" and not entry.get("content") and not entry.get("tool_calls"):
                continue
            if entry.get("role") == "tool" and isinstance(entry.get("content"), str) and len(entry["content"]) > 500:
                entry["content"] = entry["content"][:500] + "\n... (truncated)"
            entry.setdefault("timestamp", timestamp())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    def _append_lead_session(self, runtime: TeamRuntime, user_text: str, assistant_text: str) -> None:
        session = self.sessions.get_or_create(f"team:{runtime.state.run_id}:lead")
        session.add_message("user", user_text)
        session.add_message("assistant", assistant_text)
        self.sessions.save(session)

    async def _maybe_emit_approval_prompt(self, runtime: TeamRuntime, task: Task | None) -> None:
        if not task or task.status != "awaiting_approval":
            return
        if task.id in runtime.prompted_approvals:
            return
        channel, chat_id = runtime.session_key.split(":", 1) if ":" in runtime.session_key else ("cli", runtime.session_key)
        if channel == "cli":
            return
        runtime.prompted_approvals.add(task.id)
        plan = (task.plan or "").strip() or "No plan submitted."
        text = (
            f"Approval needed for `{task.id}: {task.title}` by `{task.owner or 'unknown'}`.\n"
            f"Plan: {plan[:260]}\n\n"
            "Reply naturally with your decision (approve / reject / change) and include the task id."
        )
        await self.bus.publish_outbound(OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=text,
            metadata={"team_text": True, "team_event": True},
        ))

    async def _notify_lead(self, runtime: TeamRuntime, mate: Teammate, task: Task | None, result: str, status: str) -> None:
        task_text = f"{task.id}: {task.title}" if task else "No active task"
        compact = (result or "").strip().replace("\n", " ")
        compact = compact[:220] + ("..." if len(compact) > 220 else "")
        self._append_event(runtime, "worker_update", f"{mate.name} {status} | {task_text}", result=compact)
        await self._emit_lead_update(runtime, f"Team lead: {mate.name} {status}. Task `{task_text}`. {compact}")
        await self._maybe_emit_approval_prompt(runtime, task)

    async def _run_worker(self, session_key: str, worker_name: str) -> None:
        runtime = self._active_by_session.get(session_key)
        if not runtime:
            return
        mate = next((m for m in runtime.state.members if m.name == worker_name), None)
        if not mate:
            return
        async with self._worker_semaphore:
            await self._run_worker_loop(runtime, mate)

    async def _run_worker_loop(self, runtime: TeamRuntime, mate: Teammate) -> None:
        session_key = runtime.session_key
        logger.info("Team worker [{}] starting for session {}", mate.name, session_key)
        self._set_member_status(runtime, mate.name, "working")
        session = self.sessions.get_or_create(f"team:{runtime.state.run_id}:{mate.name}")
        history = session.get_history(max_messages=60)
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._build_worker_prompt(runtime, mate)}]
        if history:
            messages.extend(history)
        else:
            messages.append({"role": "user", "content": "Inspect the board, claim a task if appropriate, and start working."})
        tools = self._build_worker_tools(runtime, mate)
        final_result = "No result."
        skip = 1 + len(history)

        try:
            for _ in range(self.worker_max_iterations):
                if runtime.session_key not in self._active_by_session:
                    final_result = "Team runtime ended."
                    break

                unread = mailbox.read_unread(runtime.run_dir, mate.name)
                if unread:
                    mail_text = "\n".join(f"[{m.from_agent}]: {m.content}" for m in unread)
                    messages.append({"role": "user", "content": f"New messages:\n{mail_text}"})

                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=mate.model or self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    reasoning_effort=self.reasoning_effort,
                )
                if response.has_tool_calls:
                    tool_calls = [{
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                    } for tc in response.tool_calls]
                    messages.append({"role": "assistant", "content": response.content or "", "tool_calls": tool_calls})
                    for tool_call in response.tool_calls:
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    final_result = response.content or "Worker completed."
                    break

                current = board.get_current(runtime.run_dir, mate.name)
                if current and current.status == "awaiting_approval":
                    final_result = current.plan or "Awaiting plan approval."
                    self._set_member_status(runtime, mate.name, "waiting_approval")
                    break
                if not current and not board.get_claimable(runtime.run_dir, mate.name):
                    final_result = "No more claimable tasks."
                    self._set_member_status(runtime, mate.name, "idle")
                    break
            else:
                final_result = f"Reached worker max iterations ({self.worker_max_iterations})."

            self._save_worker_session(session, messages, skip)
            self.sessions.save(session)
            current = board.get_current(runtime.run_dir, mate.name)
            if not current:
                self._set_member_status(runtime, mate.name, "idle")
            await self._notify_lead(runtime, mate, current, final_result, "status update")
        except asyncio.CancelledError:
            self._set_member_status(runtime, mate.name, "stopped")
            raise
        except Exception as e:
            logger.exception("Team worker [{}] failed", mate.name)
            self._set_member_status(runtime, mate.name, "stopped")
            await self._notify_lead(runtime, mate, board.get_current(runtime.run_dir, mate.name), f"Error: {e}", "failed")
