from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from nanobot.utils.helpers import timestamp


def _filter_fields(cls, data: dict) -> dict:
    """Return only the keys that ``cls`` accepts, so extra JSON fields don't crash."""
    valid = {f.name for f in cls.__dataclass_fields__.values()}
    return {k: v for k, v in data.items() if k in valid}


@dataclass
class Task:
    id: str
    title: str
    description: str = ""
    owner: str | None = None
    status: str = "pending"
    depends_on: list[str] = field(default_factory=list)
    plan: str | None = None
    result: str | None = None
    requires_approval: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(**_filter_fields(cls, data))


@dataclass
class Teammate:
    name: str
    role: str
    model: str | None = None
    status: str = "idle"

    @classmethod
    def from_dict(cls, data: dict) -> "Teammate":
        return cls(**_filter_fields(cls, data))


@dataclass
class Mail:
    id: str
    from_agent: str
    to_agent: str
    content: str
    timestamp: str
    read_by: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Mail":
        return cls(**_filter_fields(cls, data))


@dataclass
class TeamState:
    team_id: str
    run_id: str = ""
    mission: str = ""
    lead: str = "lead"
    members: list[Teammate] = field(default_factory=list)
    status: str = "active"
    created_at: str = field(default_factory=timestamp)
    session_key: str = "cli:direct"

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict) -> "TeamState":
        return cls(
            team_id=data["team_id"],
            run_id=data.get("run_id", data.get("team_id", "")),
            mission=data.get("mission", ""),
            lead=data.get("lead", "lead"),
            members=[Teammate.from_dict(m) for m in data.get("members", [])],
            status=data.get("status", "active"),
            created_at=data.get("created_at", timestamp()),
            session_key=data.get("session_key", "cli:direct"),
        )

    @classmethod
    def load(cls, path: Path) -> "TeamState":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


@dataclass
class TeamRuntime:
    """In-memory runtime state for an active team session."""

    session_key: str
    run_dir: Path
    state: TeamState
    worker_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    prompted_approvals: set[str] = field(default_factory=set)

    @property
    def events_path(self) -> Path:
        return self.run_dir / "events.jsonl"
