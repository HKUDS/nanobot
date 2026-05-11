"""Per-user runtime context.

``UserContext`` is the single object threaded through the request lifecycle
(WebSocket inbound → AgentLoop → AgentRunner → tools) so every path lookup
resolves under the caller's isolated directory subtree:

    ~/.nanobot/users/<user_id>/
        profile.json
        workspace/
        sessions/
        memory/
        media/[<channel>/]
        tool-results/
        file_state/

CLI / channel-admin call sites that do not have a UserContext continue to
use the legacy global helpers in ``nanobot.config.paths`` — that branch is
left untouched in this slice and is wired per-tool in Slice C.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nanobot.auth.ids import assert_ulid
from nanobot.config.paths import get_user_root
from nanobot.utils.helpers import ensure_dir


@dataclass(frozen=True)
class UserContext:
    """Resolves per-user filesystem paths. Frozen + hashable so it's safe to
    pass through async boundaries.
    """

    user_id: str

    def __post_init__(self) -> None:
        assert_ulid(self.user_id)

    def root(self) -> Path:
        return get_user_root(self.user_id)

    def profile_path(self) -> Path:
        return self.root() / "profile.json"

    def workspace_path(self) -> Path:
        return ensure_dir(self.root() / "workspace")

    def sessions_dir(self) -> Path:
        return ensure_dir(self.root() / "sessions")

    def memory_dir(self) -> Path:
        return ensure_dir(self.root() / "memory")

    def media_dir(self, channel: str | None = None) -> Path:
        base = ensure_dir(self.root() / "media")
        return ensure_dir(base / channel) if channel else base

    def tool_results_dir(self) -> Path:
        return ensure_dir(self.root() / "tool-results")

    def file_state_dir(self) -> Path:
        return ensure_dir(self.root() / "file_state")
