"""Proposal directory CRUD for PostTask skill creation (E1 Step 3)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from loguru import logger

_PROPOSALS_DIR = ".proposals"
_SKIP_DIRS = frozenset({".proposals", ".archive", ".rejected"})
_FRONTMATTER_RE = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", re.DOTALL)
_NAME_RE = re.compile(r"^name:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_DESC_RE = re.compile(r"^description:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_MD_FENCE_RE = re.compile(r"^```(?:markdown|md)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_MAX_SKILL_WORDS = 2000

ProposalStatus = Literal["pending", "applied", "rejected"]
ProposalSource = Literal["post_task", "gepa"]

SKIP_ACTIVE_SKILL_EXISTS = "workspace skill already exists"
SKIP_PENDING_PROPOSAL = "pending proposal with same skill_name"


@dataclass(frozen=True, slots=True)
class ProposalMeta:
    """Metadata stored beside a pending skill proposal."""

    proposal_id: str
    source: ProposalSource
    trace_id: str
    skill_name: str
    rationale: str
    confidence: float
    created_at: str
    status: ProposalStatus = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "source": self.source,
            "trace_id": self.trace_id,
            "skill_name": self.skill_name,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProposalMeta:
        return cls(
            proposal_id=str(data.get("proposal_id") or ""),
            source=data.get("source") or "post_task",  # type: ignore[arg-type]
            trace_id=str(data.get("trace_id") or ""),
            skill_name=str(data.get("skill_name") or ""),
            rationale=str(data.get("rationale") or ""),
            confidence=float(data.get("confidence") or 0.0),
            created_at=str(data.get("created_at") or ""),
            status=data.get("status") or "pending",  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class PostTaskCreateResult:
    """Outcome of writing a PostTask skill proposal or auto-applied skill."""

    created: bool
    proposal_id: str = ""
    skill_name: str = ""
    skill_path: str = ""
    auto_applied: bool = False
    skip_reason: str = ""

    @classmethod
    def skipped(cls, reason: str, *, skill_name: str = "") -> PostTaskCreateResult:
        return cls(created=False, skill_name=skill_name, skip_reason=reason)

    @classmethod
    def ok(
        cls,
        *,
        skill_name: str,
        skill_path: str,
        proposal_id: str = "",
        auto_applied: bool = False,
    ) -> PostTaskCreateResult:
        return cls(
            created=True,
            proposal_id=proposal_id,
            skill_name=skill_name,
            skill_path=skill_path,
            auto_applied=auto_applied,
        )


class ProposalStore:
    """Manage ``skills/.proposals/`` and workspace skill dedup checks."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace.expanduser().resolve()
        self._skills_root = self._workspace / "skills"
        self._proposals_root = self._skills_root / _PROPOSALS_DIR

    @property
    def skills_root(self) -> Path:
        return self._skills_root

    @property
    def proposals_root(self) -> Path:
        return self._proposals_root

    def workspace_skill_exists(self, skill_name: str) -> bool:
        """Return True when ``skills/<skill_name>/SKILL.md`` exists in workspace."""
        return (self._skills_root / skill_name / "SKILL.md").is_file()

    def pending_proposal_exists(self, skill_name: str) -> bool:
        """Return True when a pending proposal already targets *skill_name*."""
        if not self._proposals_root.is_dir():
            return False
        for proposal_dir in self._proposals_root.iterdir():
            if not proposal_dir.is_dir():
                continue
            meta_path = proposal_dir / "meta.json"
            if not meta_path.is_file():
                continue
            try:
                meta = ProposalMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if meta.status == "pending" and meta.skill_name == skill_name:
                return True
        return False

    def check_dedup(self, skill_name: str) -> str | None:
        """Return a skip reason when *skill_name* cannot be created, else ``None``."""
        if self.workspace_skill_exists(skill_name):
            return SKIP_ACTIVE_SKILL_EXISTS
        if self.pending_proposal_exists(skill_name):
            return SKIP_PENDING_PROPOSAL
        return None

    def list_workspace_skill_summaries(self) -> list[str]:
        """List workspace skills as ``name — description`` for dedup context."""
        if not self._skills_root.is_dir():
            return []
        entries: list[str] = []
        for skill_dir in sorted(self._skills_root.iterdir()):
            if not skill_dir.is_dir():
                continue
            if skill_dir.name.startswith(".") or skill_dir.name in _SKIP_DIRS:
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            content = skill_md.read_text(encoding="utf-8")[:500]
            match = _DESC_RE.search(content)
            desc = match.group(1).strip() if match else "(no description)"
            entries.append(f"{skill_dir.name} — {desc}")
        return entries

    def list_pending(self) -> list[ProposalMeta]:
        """Return all pending proposals sorted by ``created_at``."""
        if not self._proposals_root.is_dir():
            return []
        pending: list[ProposalMeta] = []
        for proposal_dir in self._proposals_root.iterdir():
            if not proposal_dir.is_dir():
                continue
            meta_path = proposal_dir / "meta.json"
            if not meta_path.is_file():
                continue
            try:
                meta = ProposalMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning("Unreadable proposal meta {}: {}", meta_path, exc)
                continue
            if meta.status == "pending":
                pending.append(meta)
        pending.sort(key=lambda item: item.created_at)
        return pending

    def write_proposal(
        self,
        *,
        skill_name: str,
        skill_md: str,
        trace_id: str,
        rationale: str,
        confidence: float,
        source: ProposalSource = "post_task",
    ) -> str:
        """Write ``skills/.proposals/<uuid>/SKILL.md`` + ``meta.json``; return proposal_id."""
        proposal_id = str(uuid4())
        proposal_dir = self._proposals_root / proposal_id
        proposal_dir.mkdir(parents=True, exist_ok=False)
        meta = ProposalMeta(
            proposal_id=proposal_id,
            source=source,
            trace_id=trace_id,
            skill_name=skill_name,
            rationale=rationale,
            confidence=confidence,
            created_at=datetime.now(UTC).isoformat(),
            status="pending",
        )
        (proposal_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        (proposal_dir / "meta.json").write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(
            "PostTask proposal written: id={} skill={} path={}",
            proposal_id,
            skill_name,
            proposal_dir,
        )
        return proposal_id

    def write_active_skill(self, skill_name: str, skill_md: str) -> Path:
        """Write ``skills/<skill_name>/SKILL.md`` directly (auto_apply)."""
        skill_dir = self._skills_root / skill_name
        skill_dir.mkdir(parents=True, exist_ok=False)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(skill_md, encoding="utf-8")
        logger.info("PostTask auto-applied skill: name={} path={}", skill_name, skill_path)
        return skill_path

    def read_meta(self, proposal_id: str) -> ProposalMeta | None:
        meta_path = self._proposals_root / proposal_id / "meta.json"
        if not meta_path.is_file():
            return None
        try:
            return ProposalMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Unreadable proposal meta {}: {}", meta_path, exc)
            return None


def normalize_skill_md_content(content: str | None) -> str:
    """Strip markdown fences and surrounding whitespace from LLM output."""
    if not content:
        return ""
    text = content.strip()
    text = _MD_FENCE_RE.sub("", text).strip()
    return text


def validate_skill_md(content: str, *, skill_name: str) -> str | None:
    """Return an error message when *content* is invalid, else ``None``."""
    if not content.strip():
        return "empty skill content"
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return "missing YAML frontmatter"
    frontmatter = match.group(1)
    if not _NAME_RE.search(frontmatter):
        return "frontmatter missing name"
    if not _DESC_RE.search(frontmatter):
        return "frontmatter missing description"
    name_match = _NAME_RE.search(frontmatter)
    if name_match and name_match.group(1).strip().lower() != skill_name:
        return f"frontmatter name mismatch (expected {skill_name})"
    body = content[match.end() :]
    word_count = len(body.split())
    if word_count > _MAX_SKILL_WORDS:
        return f"skill body exceeds {_MAX_SKILL_WORDS} words"
    return None
