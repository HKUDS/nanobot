from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.utils.helpers import ensure_dir, get_data_path, safe_filename


def get_trace_dir() -> Path:
    return ensure_dir(get_data_path() / "trace")


def new_trace_id(seed: str | None = None) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    if seed:
        safe = safe_filename(seed.replace(":", "_"))
        return f"{stamp}_{safe}_{suffix}"
    return f"{stamp}_{suffix}"


def extract_skill_from_path(path: str) -> dict[str, str] | None:
    try:
        p = Path(path).expanduser().resolve()
    except Exception:
        return None
    if p.name != "SKILL.md":
        return None
    parts = list(p.parts)
    if "skills" not in parts:
        return None
    idx = parts.index("skills")
    if idx + 1 >= len(parts):
        return None
    name = parts[idx + 1]
    source = "workspace" if str(p).startswith(str(Path.home() / ".nanobot")) else "builtin"
    return {"name": name, "path": str(p), "source": source}


class TraceRecorder:
    def __init__(
        self,
        trace_id: str,
        *,
        parent_trace_id: str | None,
        session_key: str,
        channel: str,
        chat_id: str,
        message_id: str | None,
        workspace: Path,
        trace_type: str = "agent",
    ):
        self.trace_id = trace_id
        self._saved = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self.path = get_trace_dir() / f"{safe_filename(trace_id)}.json"
        self.trace: dict[str, Any] = {
            "trace_id": trace_id,
            "parent_trace_id": parent_trace_id,
            "trace_type": trace_type,
            "session_key": session_key,
            "channel": channel,
            "chat_id": chat_id,
            "message_id": message_id,
            "workspace": str(workspace),
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
            "records": [],
        }
        self._autosave_thread = threading.Thread(target=self._autosave_loop, daemon=True)
        self._autosave_thread.start()

    @property
    def saved(self) -> bool:
        return self._saved

    def add_event(self, event_type: str, **data: Any) -> dict[str, Any]:
        event = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            **data,
        }
        with self._lock:
            self.trace["records"].append(event)
        return event

    def record_input(self, role: str, content: Any, media: list[str] | None = None) -> None:
        payload = {
            "role": role,
            "content": content,
            "media": media or [],
        }
        self.add_event("input", **payload)

    def record_model_call(
        self,
        call_id: int,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        response: Any,
    ) -> None:
        system_prompt = None
        for m in messages:
            if m.get("role") == "system":
                system_prompt = m.get("content")
                break
        snapshot = []
        for m in messages:
            entry = {"role": m.get("role"), "content": m.get("content")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            snapshot.append(entry)
        tool_calls = []
        for tc in response.tool_calls:
            tool_calls.append({"id": tc.id, "name": tc.name, "arguments": tc.arguments})
        entry = {
            "call_id": call_id,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "system_prompt": system_prompt,
            "messages": snapshot,
            "output": {
                "content": response.content,
                "reasoning_content": response.reasoning_content,
                "finish_reason": response.finish_reason,
                "usage": response.usage,
                "tool_calls": tool_calls,
            },
        }
        self.add_event("model_call", **entry)

    def record_tool_call(
        self,
        tool_call_id: str,
        name: str,
        arguments: dict[str, Any],
        result: str,
    ) -> None:
        entry = {
            "id": tool_call_id,
            "name": name,
            "arguments": arguments,
            "result": result,
        }
        self.add_event("tool_call", **entry)

    def record_skill_use(self, name: str, path: str, source: str) -> None:
        entry = {
            "name": name,
            "path": path,
            "source": source,
            "timestamp": datetime.now().isoformat(),
        }
        self.add_event("skill_use", **entry)

    def record_subagent_spawn(
        self,
        task_id: str,
        trace_id: str,
        label: str,
        task: str,
    ) -> None:
        entry = {
            "task_id": task_id,
            "trace_id": trace_id,
            "label": label,
            "task": task,
            "timestamp": datetime.now().isoformat(),
        }
        self.add_event("subagent_spawn", **entry)

    def record_final_response(self, content: str | None) -> None:
        payload = {
            "content": content,
        }
        self.add_event("response", **payload)

    def finalize(self) -> None:
        self._stop_event.set()
        if self._autosave_thread.is_alive():
            self._autosave_thread.join(timeout=1.5)
        if self.trace["completed_at"] is None:
            self.trace["completed_at"] = datetime.now().isoformat()
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = json.dumps(self.trace, ensure_ascii=False, indent=2)
        self.path.write_text(payload, encoding="utf-8")
        self._saved = True

    def _autosave_loop(self) -> None:
        while not self._stop_event.wait(1.0):
            try:
                self.save()
            except Exception:
                continue
