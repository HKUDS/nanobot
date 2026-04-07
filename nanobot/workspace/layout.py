"""Workspace directory layout — single source of truth for all workspace paths.

所有消费方（SessionManager、TraceHook、ContextBuilder）只问 layout，不自己拼路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    """每个 session 上下文的路径计算器。"""

    workspace: Path
    channel: str          # "discord"
    channel_name: str     # "develop", "dm-haibin", "cli" — 人类可读名
    chat_id: str          # Discord channel/thread ID, or "direct" for CLI
    scope_id: str = ""    # Parent channel ID — 用于目录命名，保证全局唯一

    # --- 目录 ---

    @property
    def _dir_name(self) -> str:
        """目录名：{channel_name}_{scope_id} 或纯 channel_name（无 scope_id 时）。"""
        if self.scope_id and self.scope_id != self.channel_name:
            return f"{self.channel_name}_{self.scope_id}"
        return self.channel_name

    @property
    def channel_dir(self) -> Path:
        return self.workspace / self.channel

    @property
    def scope_dir(self) -> Path:
        return self.channel_dir / self._dir_name

    @property
    def sessions_dir(self) -> Path:
        return self.scope_dir / "sessions"

    @property
    def llm_logs_dir(self) -> Path:
        return self.scope_dir / "llm_logs"

    @property
    def people_dir(self) -> Path:
        return self.channel_dir / "people"

    # --- 文件 ---

    @property
    def agent_md(self) -> Path:
        return self.scope_dir / "AGENT.md"

    def session_path(self, date: str, seq: int) -> Path:
        return self.sessions_dir / f"{date}_{self.chat_id}_{seq:02d}.jsonl"

    def llm_log_path(self, date: str, seq: int) -> Path:
        return self.llm_logs_dir / f"{date}_{self.chat_id}_{seq:02d}.jsonl"

    def current_session_path(self, date: str) -> Path | None:
        """当天最新（序号最大）的 session 文件，不存在返回 None。"""
        if not self.sessions_dir.exists():
            return None
        prefix = f"{date}_{self.chat_id}_"
        matches = sorted(self.sessions_dir.glob(f"{prefix}*.jsonl"))
        return matches[-1] if matches else None

    def next_session_seq(self, date: str) -> int:
        """当天下一个可用序号。"""
        if not self.sessions_dir.exists():
            return 1
        prefix = f"{date}_{self.chat_id}_"
        existing = []
        for p in self.sessions_dir.glob(f"{prefix}*.jsonl"):
            try:
                existing.append(int(p.stem.rsplit("_", 1)[-1]))
            except ValueError:
                continue
        return max(existing, default=0) + 1

    def ensure_dirs(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.llm_logs_dir.mkdir(parents=True, exist_ok=True)


def make_layout(
    workspace: Path,
    channel: str,
    channel_name: str | None,
    chat_id: str,
    scope_id: str = "",
) -> WorkspaceLayout:
    """构造 layout。channel_name 未知时 fallback 到 chat_id。"""
    return WorkspaceLayout(
        workspace=workspace,
        channel=channel,
        channel_name=channel_name or chat_id,
        chat_id=chat_id,
        scope_id=scope_id,
    )
