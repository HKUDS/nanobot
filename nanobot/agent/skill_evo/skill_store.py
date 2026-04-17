"""SkillStore: controlled, auditable skill persistence layer."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_MAX_NAME_LEN = 64
_MAX_CONTENT_CHARS = 100_000
ALLOWED_SUPPORTING_DIRS = frozenset({"references", "templates", "scripts", "assets"})

_FRONTMATTER_RE = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    re.DOTALL,
)


def _parse_frontmatter(content: str) -> dict[str, str]:
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def _frontmatter_body(content: str) -> str:
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return content.strip()
    return content[match.end():].strip()


def _validate_name(name: str) -> str | None:
    """Return error message or None if valid."""
    if not name:
        return "Skill name is required."
    if len(name) > _MAX_NAME_LEN:
        return f"Skill name exceeds {_MAX_NAME_LEN} characters."
    if not _SKILL_NAME_RE.match(name):
        return (
            f"Invalid skill name '{name}'. "
            "Must be lowercase alphanumeric, hyphens, underscores, dots; "
            "start with letter or digit."
        )
    return None


def _validate_content(content: str) -> str | None:
    """Return error message or None if valid."""
    if len(content) > _MAX_CONTENT_CHARS:
        return f"Content exceeds {_MAX_CONTENT_CHARS} character limit."
    fm = _parse_frontmatter(content)
    if not fm.get("name") and not fm.get("description"):
        return "SKILL.md must have YAML frontmatter with at least 'name' or 'description'."
    body = _frontmatter_body(content)
    if not body:
        return "SKILL.md body (after frontmatter) must not be empty."
    return None


def _validate_supporting_path(file_path: str) -> str | None:
    """Return error message or None if valid."""
    parts = Path(file_path).parts
    if not parts:
        return "file_path is empty."
    if parts[0] not in ALLOWED_SUPPORTING_DIRS:
        return (
            f"file_path must start with one of: {', '.join(sorted(ALLOWED_SUPPORTING_DIRS))}. "
            f"Got '{parts[0]}'."
        )
    if ".." in parts:
        return "Path traversal ('..') is not allowed."
    return None


def _atomic_write(target: Path, content: str) -> None:
    """Write content atomically via tempfile + rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        fd = -1
        os.replace(tmp, str(target))
    except BaseException:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class SkillStore:
    """Controlled, auditable skill persistence.

    All writes go to ``workspace / skills / <name> / SKILL.md``.
    Builtin skills are cloned to workspace on first mutation.
    """

    def __init__(
        self,
        workspace: Path,
        builtin_skills_dir: Path | None = None,
        guard: Any | None = None,
        session_key: str = "",
    ) -> None:
        self._workspace = workspace
        self._skills_dir = workspace / "skills"
        self._builtin_dir = builtin_skills_dir
        self._guard = guard
        self._session_key = session_key

    @property
    def skills_dir(self) -> Path:
        return self._skills_dir

    def set_session_key(self, key: str) -> None:
        self._session_key = key

    # ------------------------------------------------------------------
    # Manifest & audit
    # ------------------------------------------------------------------

    def _manifest_path(self) -> Path:
        return self._skills_dir / ".skill-manifest.json"

    def _events_path(self) -> Path:
        return self._skills_dir / ".skill-events.jsonl"

    def _load_manifest(self) -> dict[str, Any]:
        path = self._manifest_path()
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt skill manifest, starting fresh")
        return {}

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        _atomic_write(self._manifest_path(), json.dumps(manifest, indent=2, ensure_ascii=False))

    def _update_manifest(self, name: str, *, action: str, origin: str | None = None) -> None:
        manifest = self._load_manifest()
        now = datetime.now(timezone.utc).isoformat()
        if action == "delete":
            manifest.pop(name, None)
        else:
            entry = manifest.get(name, {})
            if not entry:
                entry = {
                    "source": "workspace",
                    "created_by": self._session_key or "unknown",
                    "created_at": now,
                    "usage_count": 0,
                    "last_used": None,
                }
            entry["updated_at"] = now
            if origin:
                entry["origin_skill"] = origin
            manifest[name] = entry
        self._save_manifest(manifest)

    def record_usage(self, name: str) -> None:
        """Increment usage counter when a skill is loaded or viewed."""
        manifest = self._load_manifest()
        entry = manifest.get(name)
        if entry is None:
            return
        entry["usage_count"] = entry.get("usage_count", 0) + 1
        entry["last_used"] = datetime.now(timezone.utc).isoformat()
        self._save_manifest(manifest)

    def get_usage_summary(self) -> list[dict[str, Any]]:
        """Return skill usage stats for the review agent."""
        manifest = self._load_manifest()
        stats: list[dict[str, Any]] = []
        for name, entry in manifest.items():
            stats.append({
                "name": name,
                "created_by": entry.get("created_by", "unknown"),
                "usage_count": entry.get("usage_count", 0),
                "last_used": entry.get("last_used"),
                "created_at": entry.get("created_at"),
                "updated_at": entry.get("updated_at"),
            })
        return stats

    def _log_event(self, action: str, name: str, reason: str, result: str) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_key": self._session_key,
            "action": action,
            "skill_name": name,
            "reason": reason,
            "result": result,
        }
        path = self._events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Guard integration
    # ------------------------------------------------------------------

    def _run_guard(self, skill_dir: Path, *, trust: str = "agent_created") -> dict[str, Any] | None:
        """Run security guard scan. Returns error dict on blocked, None on allowed."""
        if self._guard is None:
            return None
        try:
            from nanobot.agent.skill_evo.skill_guard import TrustLevel
            trust_level = TrustLevel(trust)
            scan_result = self._guard.scan_skill(skill_dir)
            allowed, reason = self._guard.should_allow(scan_result, trust=trust_level)
            if not allowed:
                return {"success": False, "error": f"Security scan blocked: {reason}"}
        except Exception as e:
            logger.warning("Guard scan failed (allowing): {}", e)
        return None

    # ------------------------------------------------------------------
    # Builtin clone
    # ------------------------------------------------------------------

    def _ensure_workspace_copy(self, name: str) -> Path | None:
        """If skill only exists in builtin, clone to workspace. Returns workspace path."""
        ws_dir = self._skills_dir / name
        if ws_dir.is_dir() and (ws_dir / "SKILL.md").exists():
            return ws_dir
        if self._builtin_dir:
            bi_dir = self._builtin_dir / name
            if bi_dir.is_dir() and (bi_dir / "SKILL.md").exists():
                self._skills_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(str(bi_dir), str(ws_dir))
                self._update_manifest(name, action="clone", origin=f"builtin:{name}")
                self._log_event("clone", name, "Cloned from builtin for mutation", "ok")
                return ws_dir
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _infer_trust(self) -> str:
        """Infer trust level from the current session key."""
        sk = self._session_key
        if sk.startswith("review:") or sk == "dream":
            return "agent_created"
        if sk.startswith("upload:"):
            return "upload"
        return "human_curated"

    def create_skill(self, name: str, content: str) -> dict[str, Any]:
        if err := _validate_name(name):
            return {"success": False, "error": err}
        if err := _validate_content(content):
            return {"success": False, "error": err}

        skill_dir = self._skills_dir / name
        if skill_dir.exists() and (skill_dir / "SKILL.md").exists():
            return {"success": False, "error": f"Skill '{name}' already exists. Use 'edit' or 'patch' instead."}

        skill_dir.mkdir(parents=True, exist_ok=True)
        target = skill_dir / "SKILL.md"
        _atomic_write(target, content)

        if guard_err := self._run_guard(skill_dir, trust=self._infer_trust()):
            shutil.rmtree(str(skill_dir), ignore_errors=True)
            self._log_event("create", name, "guard_blocked", guard_err["error"])
            return guard_err

        self._update_manifest(name, action="create")
        self._log_event("create", name, "New skill created", "ok")
        return {"success": True, "action": "create", "name": name, "path": str(target)}

    def edit_skill(self, name: str, content: str) -> dict[str, Any]:
        if err := _validate_name(name):
            return {"success": False, "error": err}
        if err := _validate_content(content):
            return {"success": False, "error": err}

        ws_dir = self._ensure_workspace_copy(name)
        if ws_dir is None:
            return {"success": False, "error": f"Skill '{name}' not found."}

        target = ws_dir / "SKILL.md"
        _atomic_write(target, content)

        if guard_err := self._run_guard(ws_dir, trust=self._infer_trust()):
            self._log_event("edit", name, "guard_blocked", guard_err["error"])
            return guard_err

        self._update_manifest(name, action="edit")
        self._log_event("edit", name, "Skill rewritten", "ok")
        return {"success": True, "action": "edit", "name": name, "path": str(target)}

    def patch_skill(
        self,
        name: str,
        old_string: str,
        new_string: str,
        *,
        file_path: str | None = None,
        replace_all: bool = False,
    ) -> dict[str, Any]:
        if err := _validate_name(name):
            return {"success": False, "error": err}

        ws_dir = self._ensure_workspace_copy(name)
        if ws_dir is None:
            return {"success": False, "error": f"Skill '{name}' not found."}

        if file_path:
            if err := _validate_supporting_path(file_path):
                return {"success": False, "error": err}
            target = ws_dir / file_path
        else:
            target = ws_dir / "SKILL.md"

        if not target.exists():
            return {"success": False, "error": f"File not found: {target.name}"}

        try:
            current = target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            return {"success": False, "error": f"Cannot read file: {e}"}

        count = current.count(old_string)
        if count == 0:
            return {"success": False, "error": "old_string not found in file."}
        if count > 1 and not replace_all:
            return {
                "success": False,
                "error": f"old_string found {count} times. Set replace_all=true or provide more context.",
            }

        updated = current.replace(old_string, new_string) if replace_all else current.replace(old_string, new_string, 1)
        _atomic_write(target, updated)

        if guard_err := self._run_guard(ws_dir, trust=self._infer_trust()):
            _atomic_write(target, current)
            self._log_event("patch", name, "guard_blocked", guard_err["error"])
            return guard_err

        self._update_manifest(name, action="patch")
        self._log_event("patch", name, "Skill patched", "ok")
        return {"success": True, "action": "patch", "name": name, "path": str(target)}

    def delete_skill(self, name: str) -> dict[str, Any]:
        if err := _validate_name(name):
            return {"success": False, "error": err}

        skill_dir = self._skills_dir / name
        if not skill_dir.exists():
            return {"success": False, "error": f"Skill '{name}' not found in workspace."}

        shutil.rmtree(str(skill_dir))
        self._update_manifest(name, action="delete")
        self._log_event("delete", name, "Skill deleted", "ok")
        return {"success": True, "action": "delete", "name": name}

    def write_file(self, name: str, file_path: str, file_content: str) -> dict[str, Any]:
        if err := _validate_name(name):
            return {"success": False, "error": err}
        if err := _validate_supporting_path(file_path):
            return {"success": False, "error": err}
        if len(file_content) > _MAX_CONTENT_CHARS:
            return {"success": False, "error": f"File content exceeds {_MAX_CONTENT_CHARS} character limit."}

        ws_dir = self._ensure_workspace_copy(name)
        if ws_dir is None:
            skill_dir = self._skills_dir / name
            if not skill_dir.exists():
                return {"success": False, "error": f"Skill '{name}' not found. Create the skill first."}
            ws_dir = skill_dir

        target = ws_dir / file_path
        resolved = target.resolve()
        try:
            resolved.relative_to(ws_dir.resolve())
        except ValueError:
            return {"success": False, "error": "Path traversal detected."}

        _atomic_write(target, file_content)

        if guard_err := self._run_guard(ws_dir, trust=self._infer_trust()):
            target.unlink(missing_ok=True)
            self._log_event("write_file", name, "guard_blocked", guard_err["error"])
            return guard_err

        self._update_manifest(name, action="write_file")
        self._log_event("write_file", name, f"File written: {file_path}", "ok")
        return {"success": True, "action": "write_file", "name": name, "path": str(target)}

    def remove_file(self, name: str, file_path: str) -> dict[str, Any]:
        if err := _validate_name(name):
            return {"success": False, "error": err}
        if err := _validate_supporting_path(file_path):
            return {"success": False, "error": err}

        skill_dir = self._skills_dir / name
        if not skill_dir.exists():
            return {"success": False, "error": f"Skill '{name}' not found."}

        target = skill_dir / file_path
        resolved = target.resolve()
        try:
            resolved.relative_to(skill_dir.resolve())
        except ValueError:
            return {"success": False, "error": "Path traversal detected."}

        if not target.exists():
            return {"success": False, "error": f"File '{file_path}' not found."}

        target.unlink()
        self._log_event("remove_file", name, f"File removed: {file_path}", "ok")
        return {"success": True, "action": "remove_file", "name": name, "file_path": file_path}
