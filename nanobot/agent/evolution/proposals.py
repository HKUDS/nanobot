"""Proposal directory CRUD for PostTask skill creation (E1 Step 3)."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.evolution.git_store import EvolutionGitStore

_PROPOSALS_DIR = ".proposals"
_REJECTED_DIR = ".rejected"
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

ERR_PROPOSAL_NOT_FOUND = "proposal not found"
ERR_PROPOSAL_NOT_PENDING = "proposal is not pending"
ERR_PROPOSAL_ALREADY_REJECTED = "proposal already rejected"
ERR_APPLY_ACTIVE_SKILL_EXISTS = "workspace skill already exists (update deferred to GEPA)"


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
    applied_at: str = ""
    rejected_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "proposal_id": self.proposal_id,
            "source": self.source,
            "trace_id": self.trace_id,
            "skill_name": self.skill_name,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "status": self.status,
        }
        if self.applied_at:
            payload["applied_at"] = self.applied_at
        if self.rejected_at:
            payload["rejected_at"] = self.rejected_at
        return payload

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
            applied_at=str(data.get("applied_at") or ""),
            rejected_at=str(data.get("rejected_at") or ""),
        )


@dataclass(frozen=True, slots=True)
class ProposalDetail:
    """Full proposal payload for inspection (E2 /evolve-show)."""

    meta: ProposalMeta
    skill_md: str
    proposal_dir: Path


@dataclass(frozen=True, slots=True)
class ProposalActionResult:
    """Outcome of apply/reject on a pending proposal."""

    ok: bool
    proposal_id: str = ""
    skill_name: str = ""
    skill_path: str = ""
    commit_sha: str = ""
    skip_reason: str = ""

    @classmethod
    def fail(
        cls,
        reason: str,
        *,
        proposal_id: str = "",
        skill_name: str = "",
    ) -> ProposalActionResult:
        return cls(
            ok=False,
            proposal_id=proposal_id,
            skill_name=skill_name,
            skip_reason=reason,
        )

    @classmethod
    def success(
        cls,
        *,
        proposal_id: str,
        skill_name: str,
        skill_path: str,
    ) -> ProposalActionResult:
        return cls(
            ok=True,
            proposal_id=proposal_id,
            skill_name=skill_name,
            skill_path=skill_path,
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

    @property
    def rejected_root(self) -> Path:
        return self._skills_root / _REJECTED_DIR

    @property
    def workspace(self) -> Path:
        return self._workspace

    def _active_skill_rel_path(self, skill_name: str) -> str:
        return f"skills/{skill_name}/SKILL.md"

    def _read_meta_file(self, meta_path: Path) -> ProposalMeta | None:
        if not meta_path.is_file():
            return None
        try:
            return ProposalMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Unreadable proposal meta {}: {}", meta_path, exc)
            return None

    def _write_meta(self, proposal_dir: Path, meta: ProposalMeta) -> None:
        proposal_dir.mkdir(parents=True, exist_ok=True)
        (proposal_dir / "meta.json").write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _proposal_dir(self, proposal_id: str) -> Path | None:
        pending_dir = self._proposals_root / proposal_id
        if pending_dir.is_dir():
            return pending_dir
        rejected_dir = self.rejected_root / proposal_id
        if rejected_dir.is_dir():
            return rejected_dir
        return None

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
        self._write_meta(proposal_dir, meta)
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
        proposal_dir = self._proposal_dir(proposal_id)
        if proposal_dir is None:
            return None
        return self._read_meta_file(proposal_dir / "meta.json")

    def get(self, proposal_id: str) -> ProposalDetail | None:
        """Load proposal meta + SKILL.md from ``.proposals/`` or ``.rejected/``."""
        proposal_dir = self._proposal_dir(proposal_id)
        if proposal_dir is None:
            return None
        meta = self._read_meta_file(proposal_dir / "meta.json")
        skill_path = proposal_dir / "SKILL.md"
        if meta is None or not skill_path.is_file():
            return None
        try:
            skill_md = skill_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Unreadable proposal SKILL.md {}: {}", skill_path, exc)
            return None
        return ProposalDetail(meta=meta, skill_md=skill_md, proposal_dir=proposal_dir)

    def apply(self, proposal_id: str) -> ProposalActionResult:
        """
        将指定 proposal_id 的待处理技能提案（pending proposal）应用到正式技能目录 ``skills/<name>/SKILL.md``。

        步骤如下：
        1. 检查 proposal 元数据（meta.json）是否存在，不存在则返回失败。
        2. 判断 proposal 状态：
           - 已应用（applied）：若 workspace 已存在同名技能，则直接返回成功，否则报错。
           - 已拒绝（rejected）：返回“提案已被拒绝”错误。
           - 非待处理（非 pending）：返回“提案不可用”错误。
        3. 检查 proposal 目录下 SKILL.md 是否存在，不存在则返回失败。
        4. 尝试读取 SKILL.md 内容，不可读则返回失败。
        5. 校验 SKILL.md 内容格式，若无效则返回失败。
        6. 再次检查民用空间（workspace）是否已有同名技能，若存在则返回失败（优先 GEPA 方案）。
        7. 尝试将 SKILL.md 写入正式技能目录（skills/<name>/SKILL.md）。
           - 若已存在则返回失败。
           - 若写入异常则警告并返回失败。
        8. 更新 proposal 元数据为已应用（applied），记录应用时间。
        9. 日志记录应用行为并返回成功，返回包括 proposal_id、技能名称和相对技能路径。

        注：本函数为自动化审核 / 通过提案时调用，未直接暴露于外部接口。
        """
        proposal_dir = self._proposals_root / proposal_id
        meta = self._read_meta_file(proposal_dir / "meta.json")
        if meta is None:
            return ProposalActionResult.fail(ERR_PROPOSAL_NOT_FOUND, proposal_id=proposal_id)

        # 已应用：若已存在技能直接返回成功，否则失败
        if meta.status == "applied":
            if self.workspace_skill_exists(meta.skill_name):
                return ProposalActionResult.success(
                    proposal_id=proposal_id,
                    skill_name=meta.skill_name,
                    skill_path=self._active_skill_rel_path(meta.skill_name),
                )
            return ProposalActionResult.fail(
                ERR_PROPOSAL_NOT_PENDING,
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        # 已拒绝：直接返回失败
        if meta.status == "rejected":
            return ProposalActionResult.fail(
                ERR_PROPOSAL_ALREADY_REJECTED,
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        # 不是“待处理”状态也不能继续应用
        if meta.status != "pending":
            return ProposalActionResult.fail(
                ERR_PROPOSAL_NOT_PENDING,
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        # 检查 proposal 下的 SKILL.md 文件是否存在
        skill_path = proposal_dir / "SKILL.md"
        if not skill_path.is_file():
            return ProposalActionResult.fail(
                "proposal SKILL.md invalid: missing SKILL.md",
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        # 读取 SKILL.md 文件内容
        try:
            skill_md = skill_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Unreadable proposal SKILL.md {}: {}", skill_path, exc)
            return ProposalActionResult.fail(
                "proposal SKILL.md invalid: unreadable",
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        # 校验 SKILL.md 内容合法性
        validation_error = validate_skill_md(skill_md, skill_name=meta.skill_name)
        if validation_error:
            return ProposalActionResult.fail(
                f"proposal SKILL.md invalid: {validation_error}",
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        # 防御性判断 —— 若已存在同名技能则返回失败
        if self.workspace_skill_exists(meta.skill_name):
            return ProposalActionResult.fail(
                ERR_APPLY_ACTIVE_SKILL_EXISTS,
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        # 写入正式技能目录
        try:
            active_path = self.write_active_skill(meta.skill_name, skill_md)
        except FileExistsError:
            return ProposalActionResult.fail(
                ERR_APPLY_ACTIVE_SKILL_EXISTS,
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )
        except OSError as exc:
            logger.warning("Proposal apply write failed: {}", exc)
            return ProposalActionResult.fail(
                "write failed",
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        # 标记提案已被应用，并更新 applied_at 时间戳
        applied_meta = replace(
            meta,
            status="applied",
            applied_at=datetime.now(UTC).isoformat(),
        )
        self._write_meta(proposal_dir, applied_meta)

        # 构造相对路径用于返回和日志
        rel = active_path.relative_to(self._workspace).as_posix()
        logger.info(
            "Proposal applied: id={} skill={} active={}",
            proposal_id,
            meta.skill_name,
            rel,
        )
        return ProposalActionResult.success(
            proposal_id=proposal_id,
            skill_name=meta.skill_name,
            skill_path=rel,
        )

    def apply_and_commit(
        self,
        proposal_id: str,
        git_store: EvolutionGitStore | None = None,
    ) -> ProposalActionResult:
        """Apply a pending proposal and record an evolve git commit."""
        from nanobot.agent.evolution.git_store import EvolutionGitStore

        result = self.apply(proposal_id)
        if not result.ok:
            return result

        gs = git_store or EvolutionGitStore(self._workspace)
        sha = gs.commit_create(result.skill_name)
        if not sha:
            return result
        return replace(result, commit_sha=sha)

    def reject(self, proposal_id: str) -> ProposalActionResult:
        """Move a pending proposal to ``skills/.rejected/<id>/``."""
        if self.rejected_root.is_dir() and (self.rejected_root / proposal_id).is_dir():
            return ProposalActionResult.fail(
                ERR_PROPOSAL_ALREADY_REJECTED,
                proposal_id=proposal_id,
            )

        proposal_dir = self._proposals_root / proposal_id
        meta = self._read_meta_file(proposal_dir / "meta.json")
        if meta is None:
            return ProposalActionResult.fail(ERR_PROPOSAL_NOT_FOUND, proposal_id=proposal_id)

        if meta.status == "applied":
            return ProposalActionResult.fail(
                ERR_PROPOSAL_NOT_PENDING,
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        if meta.status == "rejected":
            return ProposalActionResult.fail(
                ERR_PROPOSAL_ALREADY_REJECTED,
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        if meta.status != "pending":
            return ProposalActionResult.fail(
                ERR_PROPOSAL_NOT_PENDING,
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        rejected_meta = replace(
            meta,
            status="rejected",
            rejected_at=datetime.now(UTC).isoformat(),
        )
        self._write_meta(proposal_dir, rejected_meta)

        self.rejected_root.mkdir(parents=True, exist_ok=True)
        target_dir = self.rejected_root / proposal_id
        try:
            shutil.move(str(proposal_dir), str(target_dir))
        except OSError as exc:
            logger.warning("Proposal reject move failed: {}", exc)
            return ProposalActionResult.fail(
                "move failed",
                proposal_id=proposal_id,
                skill_name=meta.skill_name,
            )

        logger.info("Proposal rejected: id={} skill={}", proposal_id, meta.skill_name)
        return ProposalActionResult.success(
            proposal_id=proposal_id,
            skill_name=meta.skill_name,
            skill_path=str(target_dir.relative_to(self._workspace)),
        )


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
