"""Session management for conversation history."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_legacy_sessions_dir
from nanobot.utils.helpers import ensure_dir, safe_filename
from nanobot.workspace.layout import WorkspaceLayout


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """一个会话：append-only 消息列表 + 元数据。

    messages 仅追加，consolidation 写 MEMORY.md/HISTORY.md 但不删消息。
    """

    key: str                                                # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0                              # 已归档消息数
    file_path: Path | None = field(default=None, repr=False)  # 磁盘路径，由 SessionManager 管理

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    # --- History retrieval ---

    @staticmethod
    def _find_legal_start(messages: list[dict[str, Any]]) -> int:
        """Find first index where every tool result has a matching assistant tool_call."""
        declared: set[str] = set()
        start = 0
        for i, msg in enumerate(messages):
            role = msg.get("role")
            if role == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict) and tc.get("id"):
                        declared.add(str(tc["id"]))
            elif role == "tool":
                tid = msg.get("tool_call_id")
                if tid and str(tid) not in declared:
                    start = i + 1
                    declared.clear()
                    for prev in messages[start:i + 1]:
                        if prev.get("role") == "assistant":
                            for tc in prev.get("tool_calls") or []:
                                if isinstance(tc, dict) and tc.get("id"):
                                    declared.add(str(tc["id"]))
        return start

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input, aligned to a legal tool-call boundary."""
        unconsolidated = self.messages[self.last_consolidated:]
        sliced = unconsolidated[-max_messages:]

        for i, message in enumerate(sliced):
            if message.get("role") == "user":
                sliced = sliced[i:]
                break

        start = self._find_legal_start(sliced)
        if start:
            sliced = sliced[start:]

        out: list[dict[str, Any]] = []
        for message in sliced:
            entry: dict[str, Any] = {"role": message["role"], "content": message.get("content", "")}
            for key in ("tool_calls", "tool_call_id", "name"):
                if key in message:
                    entry[key] = message[key]
            out.append(entry)
        return out

    # --- Mutation ---

    def clear(self) -> None:
        self.messages = []
        runtime = self.metadata.get("runtime")
        self.metadata = {}
        if runtime:
            self.metadata["runtime"] = runtime
        self.last_consolidated = 0
        self.updated_at = datetime.now()

    def retain_recent_legal_suffix(self, max_messages: int) -> None:
        if max_messages <= 0:
            self.clear()
            return
        if len(self.messages) <= max_messages:
            return

        start_idx = max(0, len(self.messages) - max_messages)
        while start_idx > 0 and self.messages[start_idx].get("role") != "user":
            start_idx -= 1

        retained = self.messages[start_idx:]
        start = self._find_legal_start(retained)
        if start:
            retained = retained[start:]

        dropped = len(self.messages) - len(retained)
        self.messages = retained
        self.last_consolidated = max(0, self.last_consolidated - dropped)
        self.updated_at = datetime.now()


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------

class SessionManager:
    """管理 Session 的持久化与缓存。

    两套路径：
      - get_or_create(key)            → 平铺 workspace/sessions/  (旧)
      - get_or_create_from_layout(l)  → per-channel 层级目录       (新)
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: dict[str, Session] = {}

    # --- Path helpers ---

    def _get_session_path(self, key: str) -> Path:
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    @staticmethod
    def _session_key(layout: WorkspaceLayout) -> str:
        return f"{layout.channel}:{layout.chat_id}"

    # --- Core API (flat / legacy) ---

    def get_or_create(self, key: str) -> Session:
        """获取或创建 session（平铺目录）。"""
        if key in self._cache:
            return self._cache[key]
        session = self._load_flat(key)
        if session is None:
            session = Session(key=key)
        self._cache[key] = session
        return session

    # --- Core API (layout / per-channel) ---

    def get_or_create_from_layout(self, layout: WorkspaceLayout) -> Session:
        """获取或创建 session（per-channel 层级目录）。"""
        key = self._session_key(layout)
        if key in self._cache:
            return self._cache[key]
        session = self._load_layout(layout)
        if session is None:
            layout.ensure_dirs()
            today = date.today().isoformat()
            seq = layout.next_session_seq(today)
            session = Session(key=key, file_path=layout.session_path(today, seq))
        self._cache[key] = session
        return session

    def new_session(self, layout: WorkspaceLayout) -> Session:
        """归档当前 session（保留旧文件），创建下一个序号的新 session。"""
        key = self._session_key(layout)
        self._cache.pop(key, None)
        layout.ensure_dirs()
        today = date.today().isoformat()
        seq = layout.next_session_seq(today)
        session = Session(key=key, file_path=layout.session_path(today, seq))
        self._cache[key] = session
        return session

    def current_llm_log_path(self, layout: WorkspaceLayout) -> Path:
        """与当前 session 文件对应的 LLM 日志路径。"""
        today = date.today().isoformat()
        path = layout.current_session_path(today)
        if path:
            seq = int(path.stem.rsplit("_", 1)[-1])
        else:
            seq = layout.next_session_seq(today)
        return layout.llm_log_path(today, seq)

    # --- Load ---

    def _load_flat(self, key: str) -> Session | None:
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)
        if not path.exists():
            return None
        return self._parse_jsonl(path, key)

    def _load_layout(self, layout: WorkspaceLayout) -> Session | None:
        today = date.today().isoformat()
        path = layout.current_session_path(today)
        if not path:
            return None
        key = self._session_key(layout)
        session = self._parse_jsonl(path, key)
        if session:
            session.file_path = path
        return session

    @staticmethod
    def _parse_jsonl(path: Path, key: str) -> Session | None:
        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at = None
            last_consolidated = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = (datetime.fromisoformat(data["created_at"])
                                      if data.get("created_at") else None)
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    # --- Save ---

    def save(self, session: Session) -> None:
        path = session.file_path or self._get_session_path(session.key)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            metadata_line = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated,
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    # --- List ---

    def list_sessions(self) -> list[dict[str, Any]]:
        """列出所有 session（扫描 flat 目录 + per-channel 层级目录）。"""
        sessions: list[dict[str, Any]] = []

        # 扫平铺目录
        self._scan_dir(self.sessions_dir, sessions)

        # 扫 per-channel 层级目录
        channel_root = self.workspace / "discord"
        if channel_root.is_dir():
            for scope_dir in channel_root.iterdir():
                if scope_dir.is_dir():
                    sess_dir = scope_dir / "sessions"
                    if sess_dir.is_dir():
                        self._scan_dir(sess_dir, sessions)

        # CLI 层级目录
        cli_sessions = self.workspace / "cli" / "cli" / "sessions"
        if cli_sessions.is_dir():
            self._scan_dir(cli_sessions, sessions)

        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)

    @staticmethod
    def _scan_dir(directory: Path, out: list[dict[str, Any]]) -> None:
        for path in directory.glob("*.jsonl"):
            try:
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            key = data.get("key") or path.stem.replace("_", ":", 1)
                            out.append({
                                "key": key,
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "path": str(path),
                            })
            except Exception:
                continue
