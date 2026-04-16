"""Append-only per-session transcript logs (verbatim, independent of LLM context trimming)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.utils.helpers import ensure_dir, safe_filename, truncate_text as truncate_text_fn


class SessionTranscriptWriter:
    """Writes JSONL lines to ``workspace/transcripts/{safe_key}.jsonl``."""

    def __init__(
        self,
        workspace: Path,
        *,
        enabled: bool,
        include_full_tool_results: bool,
        max_tool_result_chars: int,
    ) -> None:
        self._workspace = workspace
        self.enabled = enabled
        self.include_full_tool_results = include_full_tool_results
        self.max_tool_result_chars = max_tool_result_chars
        self._dir = ensure_dir(workspace / "transcripts") if enabled else None

    def _path(self, session_key: str) -> Path:
        assert self._dir is not None
        safe_key = safe_filename(session_key.replace(":", "_"))
        return self._dir / f"{safe_key}.jsonl"

    def _append_jsonl(self, session_key: str, record: dict[str, Any]) -> None:
        if not self.enabled or self._dir is None:
            return
        path = self._path(session_key)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def raw_turn_message_to_record(self, m: dict[str, Any]) -> dict[str, Any]:
        """Build a storable record from an agent-loop message (before session truncation)."""
        role = m.get("role")
        entry: dict[str, Any] = {"role": role, "content": m.get("content")}
        for key in ("tool_calls", "tool_call_id", "name", "reasoning_content", "thinking_blocks"):
            if key in m:
                entry[key] = m[key]
        if m.get("timestamp"):
            entry["timestamp"] = m["timestamp"]
        else:
            entry["timestamp"] = datetime.now().isoformat()

        if role == "tool" and not self.include_full_tool_results:
            content = entry.get("content")
            if isinstance(content, str) and len(content) > self.max_tool_result_chars:
                entry["content"] = truncate_text_fn(content, self.max_tool_result_chars)
            elif isinstance(content, list):
                entry["content"] = self._truncate_tool_blocks(content)
        return entry

    def _truncate_tool_blocks(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                out.append(block)
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text = block["text"]
                if len(text) > self.max_tool_result_chars:
                    out.append({**block, "text": truncate_text_fn(text, self.max_tool_result_chars)})
                else:
                    out.append(dict(block))
            else:
                out.append(dict(block))
        return out

    def append_raw_turn_message(self, session_key: str, m: dict[str, Any]) -> None:
        """Append one message from the agent run (pre-session transforms)."""
        self._append_jsonl(session_key, self.raw_turn_message_to_record(m))

    def append_session_message_snapshot(self, session_key: str, msg: dict[str, Any]) -> None:
        """Append a message as stored on the Session (e.g. early-persisted user turn)."""
        if not self.enabled:
            return
        snap = {k: msg[k] for k in msg if not k.startswith("_")}
        self._append_jsonl(session_key, snap)

    def append_evicted(
        self,
        session_key: str,
        event: str,
        messages: list[dict[str, Any]],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record messages removed by compaction / retain-suffix (destructive ops)."""
        if not self.enabled or not messages:
            return
        record: dict[str, Any] = {
            "_event": event,
            "timestamp": datetime.now().isoformat(),
            "messages": messages,
        }
        if metadata:
            record["metadata"] = metadata
        self._append_jsonl(session_key, record)
