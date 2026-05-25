"""REGISTRY.md read/write.

Plain markdown table — a human can edit by hand. The parser tolerates
extra columns, surrounding sections, and freeform text.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path


_HEADER = "# Agent Fleet Registry"
_COLUMNS = ("Name", "Repo", "Host", "Created", "Status", "Description")
_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")


@dataclass
class AgentRecord:
    name: str
    repo: str = ""           # e.g. "phelps-sg/agent-peewee"
    host: str = ""           # e.g. "sphelps.net"
    created: str = ""        # ISO date
    status: str = "active"   # active | archived
    description: str = ""

    def as_row(self) -> list[str]:
        return [
            self.name, self.repo, self.host, self.created,
            self.status, self.description,
        ]

    @classmethod
    def from_row(cls, header: list[str], row: list[str]) -> AgentRecord:
        idx = {h.lower(): i for i, h in enumerate(header)}
        def get(key: str, default: str = "") -> str:
            i = idx.get(key.lower())
            return row[i].strip() if i is not None and i < len(row) else default
        return cls(
            name=get("name"),
            repo=get("repo"),
            host=get("host"),
            created=get("created"),
            status=get("status") or "active",
            description=get("description"),
        )


class Registry:
    """In-memory view of REGISTRY.md, with read/write."""

    def __init__(self, path: Path):
        self.path = Path(path).expanduser()
        self.agents: list[AgentRecord] = []
        self._trailing: str = ""   # anything after the table, preserved verbatim
        if self.path.exists():
            self.load()

    # ---- io ----

    def load(self) -> None:
        content = self.path.read_text(encoding="utf-8")
        self.agents, self._trailing = self._parse(content)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.render(), encoding="utf-8")

    def render(self) -> str:
        header = "| " + " | ".join(_COLUMNS) + " |"
        divider = "|" + "|".join(["---"] * len(_COLUMNS)) + "|"
        rows = [
            "| " + " | ".join(_cell(c) for c in a.as_row()) + " |"
            for a in self.agents
        ]
        table = "\n".join([header, divider, *rows])
        return f"{_HEADER}\n\n{table}\n{self._trailing}".rstrip() + "\n"

    # ---- queries ----

    def get(self, name: str) -> AgentRecord | None:
        for a in self.agents:
            if a.name == name:
                return a
        return None

    def active(self) -> list[AgentRecord]:
        return [a for a in self.agents if a.status == "active"]

    # ---- mutations ----

    def add(self, record: AgentRecord) -> None:
        if self.get(record.name) is not None:
            raise ValueError(f"agent {record.name!r} already registered")
        if not record.created:
            record.created = date.today().isoformat()
        self.agents.append(record)

    def update(self, name: str, **changes) -> AgentRecord:
        rec = self.get(name)
        if rec is None:
            raise KeyError(f"no agent named {name!r}")
        for k, v in changes.items():
            if not hasattr(rec, k):
                raise KeyError(f"AgentRecord has no field {k!r}")
            setattr(rec, k, v)
        return rec

    def remove(self, name: str) -> AgentRecord:
        rec = self.get(name)
        if rec is None:
            raise KeyError(f"no agent named {name!r}")
        self.agents.remove(rec)
        return rec

    # ---- internals ----

    @staticmethod
    def _parse(content: str) -> tuple[list[AgentRecord], str]:
        lines = content.splitlines()
        # Find the first markdown table.
        header_idx = None
        for i in range(len(lines) - 1):
            if "|" in lines[i] and _DIVIDER_RE.match(lines[i + 1] or ""):
                header_idx = i
                break
        if header_idx is None:
            return [], "\n".join(lines)

        header = _split_row(lines[header_idx])
        rows: list[AgentRecord] = []
        end = header_idx + 2
        while end < len(lines):
            line = lines[end]
            if not line.strip().startswith("|"):
                break
            cells = _split_row(line)
            if not cells or not cells[0]:
                end += 1
                continue
            rows.append(AgentRecord.from_row(header, cells))
            end += 1

        trailing = "\n".join(lines[end:]).strip()
        return rows, ("\n\n" + trailing if trailing else "")


def _split_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [c.strip() for c in stripped.split("|")]


def _cell(value: str) -> str:
    """Escape pipe characters so a description with `|` doesn't corrupt the table."""
    return (value or "").replace("|", "\\|")
