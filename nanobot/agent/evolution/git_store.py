"""Git-backed version control for active workspace skills (E2 Step 2)."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from nanobot.utils.gitstore import CommitInfo, GitStore

_EVOLUTION_GITIGNORE_MARKER = "# nanobot evolution skills"
_SKIP_DIRS = frozenset({".proposals", ".archive", ".rejected"})
_AUTHOR = b"nanobot <nanobot@evolve>"
_COMMITTER = b"nanobot <nanobot@evolve>"
_EVOLVE_PREFIX = "evolve:"

_EVOLUTION_GITIGNORE_LINES = (
    _EVOLUTION_GITIGNORE_MARKER,
    "/skills/*",
    "!/skills/*/",
    "!/skills/*/**",
    "/skills/.proposals/",
    "/skills/.rejected/",
    "/skills/.archive/",
)


class EvolutionGitStore:
    """Track active ``skills/<name>/`` files in the workspace git repo."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace.expanduser().resolve()
        self._skills_root = self._workspace / "skills"
        self._git = GitStore(self._workspace, tracked_files=[])

    @property
    def workspace(self) -> Path:
        return self._workspace

    def is_initialized(self) -> bool:
        """Return True when the workspace has a local ``.git`` directory."""
        return self._git.is_initialized()

    def init(self) -> bool:
        """Ensure git is ready and evolution skill paths can be tracked.

        Creates a new repo when none exists (same rules as Dream GitStore).
        When a repo already exists, only merges evolution ``.gitignore`` rules.
        """
        if self._git.is_initialized():
            self._merge_gitignore()
            return False

        if self._git._is_inside_git_repo():
            logger.warning(
                "Workspace {} is inside a parent git repo; "
                "skipping evolution git initialization",
                self._workspace,
            )
            return False

        try:
            from dulwich import porcelain

            porcelain.init(str(self._workspace))
            self._merge_gitignore(force_write=True)

            self._skills_root.mkdir(parents=True, exist_ok=True)
            porcelain.add(str(self._workspace), paths=[".gitignore"])
            porcelain.commit(
                str(self._workspace),
                message=b"init: nanobot evolution skill store",
                author=_AUTHOR,
                committer=_COMMITTER,
            )
            logger.info("Evolution git store initialized at {}", self._workspace)
            return True
        except Exception:
            logger.exception("Evolution git store init failed for {}", self._workspace)
            return False

    def head_sha(self) -> str | None:
        """Return the current HEAD short SHA, or ``None`` when uninitialized."""
        if not self.is_initialized():
            return None
        entries = self._git.log(max_entries=1)
        return entries[0].sha if entries else None

    def active_skill_paths(self) -> list[str]:
        """List workspace-relative paths for all active skill files."""
        if not self._skills_root.is_dir():
            return []
        paths: list[str] = []
        for skill_dir in sorted(self._skills_root.iterdir()):
            if not skill_dir.is_dir():
                continue
            if skill_dir.name.startswith(".") or skill_dir.name in _SKIP_DIRS:
                continue
            if not (skill_dir / "SKILL.md").is_file():
                continue
            for file_path in sorted(skill_dir.rglob("*")):
                if file_path.is_file():
                    paths.append(file_path.relative_to(self._workspace).as_posix())
        return paths

    def skill_paths(self, skill_name: str) -> list[str]:
        """List workspace-relative paths for one active skill directory."""
        skill_dir = self._skills_root / skill_name
        if not skill_dir.is_dir():
            return []
        return [
            file_path.relative_to(self._workspace).as_posix()
            for file_path in sorted(skill_dir.rglob("*"))
            if file_path.is_file()
        ]

    def commit_create(self, skill_name: str) -> str | None:
        """Commit files under ``skills/<skill_name>/`` after a create apply."""
        return self._commit_skill(skill_name, f"evolve: create skill {skill_name}")

    def commit_update(self, skill_name: str, *, source: str = "gepa") -> str | None:
        """Commit files under ``skills/<skill_name>/`` after an update."""
        return self._commit_skill(skill_name, f"evolve: update skill {skill_name} ({source})")

    def log(self, max_entries: int = 20) -> list[CommitInfo]:
        """Return evolve-tagged commits newest-first."""
        return [
            entry
            for entry in self._git.log(max_entries=max_entries * 4)
            if entry.message.lower().startswith(_EVOLVE_PREFIX)
        ][:max_entries]

    def find_commit(self, short_sha: str, max_entries: int = 50) -> CommitInfo | None:
        """Find an evolve commit by short SHA prefix."""
        for entry in self.log(max_entries=max_entries):
            if entry.sha.startswith(short_sha):
                return entry
        return None

    def restore(self, short_sha: str) -> str | None:
        """Revert skill files introduced/changed by an evolve commit.

        Restores paths under ``skills/`` touched by the commit to their parent
        state, then records a new revert commit. Returns the revert SHA.
        """
        if not self.is_initialized():
            return None

        try:
            from dulwich.repo import Repo

            full_sha = self._git._resolve_sha(short_sha)
            if not full_sha:
                logger.warning("Evolution restore: SHA not found: {}", short_sha)
                return None

            with Repo(str(self._workspace)) as repo:
                commit_obj = repo[full_sha]
                if commit_obj.type_name != b"commit":
                    return None
                if not commit_obj.parents:
                    logger.warning("Evolution restore: cannot revert root commit {}", short_sha)
                    return None

                message = commit_obj.message.decode("utf-8", errors="replace").strip()
                if not message.lower().startswith(_EVOLVE_PREFIX):
                    logger.warning(
                        "Evolution restore: refusing non-evolve commit {}",
                        short_sha,
                    )
                    return None

                parent_obj = repo[commit_obj.parents[0]]
                parent_tree = repo[parent_obj.tree]
                commit_tree = repo[commit_obj.tree]
                paths = self._skill_paths_in_tree(repo, commit_tree)
                if not paths:
                    return None

                restored = False
                for rel_path in paths:
                    parent_content = GitStore._read_blob_from_tree(repo, parent_tree, rel_path)
                    dest = self._workspace / rel_path
                    if parent_content is not None:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_text(parent_content, encoding="utf-8")
                        restored = True
                    elif dest.exists():
                        dest.unlink()
                        restored = True
                        self._prune_empty_dirs(dest.parent)

                if not restored:
                    return None

            return self._commit_paths(paths, f"evolve: revert {short_sha}")

        except Exception:
            logger.exception("Evolution restore failed for {}", short_sha)
            return None

    def _commit_skill(self, skill_name: str, message: str) -> str | None:
        self.init()
        if not self.is_initialized():
            return None

        paths = self.skill_paths(skill_name)
        if not paths:
            logger.debug("Evolution commit skipped: no files for skill {}", skill_name)
            return None

        try:
            from dulwich import porcelain

            porcelain.add(str(self._workspace), paths=paths)
            st = porcelain.status(str(self._workspace))
            if not any(st.staged.values()):
                logger.debug("Evolution commit skipped: no changes for skill {}", skill_name)
                return None

            sha_bytes = porcelain.commit(
                str(self._workspace),
                message=message.encode("utf-8"),
                author=_AUTHOR,
                committer=_COMMITTER,
            )
            if sha_bytes is None:
                return None
            sha = sha_bytes.hex()[:8]
            logger.info("Evolution git commit: {} ({})", sha, message)
            return sha
        except Exception:
            logger.exception("Evolution git commit failed: {}", message)
            return None

    def _commit_paths(self, paths: list[str], message: str) -> str | None:
        if not paths:
            return None

        try:
            from dulwich import porcelain

            add_paths = [path for path in paths if (self._workspace / path).exists()]
            remove_paths = [path for path in paths if not (self._workspace / path).exists()]
            if add_paths:
                porcelain.add(str(self._workspace), paths=add_paths)
            if remove_paths:
                porcelain.rm(str(self._workspace), paths=remove_paths)

            st = porcelain.status(str(self._workspace))
            if not st.unstaged and not any(st.staged.values()):
                return None

            sha_bytes = porcelain.commit(
                str(self._workspace),
                message=message.encode("utf-8"),
                author=_AUTHOR,
                committer=_COMMITTER,
            )
            if sha_bytes is None:
                return None
            return sha_bytes.hex()[:8]
        except Exception:
            logger.exception("Evolution git commit failed: {}", message)
            return None

    def _merge_gitignore(self, *, force_write: bool = False) -> None:
        gitignore = self._workspace / ".gitignore"
        block = "\n".join(_EVOLUTION_GITIGNORE_LINES) + "\n"
        if gitignore.exists():
            existing = gitignore.read_text(encoding="utf-8")
            if _EVOLUTION_GITIGNORE_MARKER in existing:
                return
            merged = existing.rstrip("\n") + "\n\n" + block
            gitignore.write_text(merged, encoding="utf-8")
        elif force_write:
            gitignore.write_text(block, encoding="utf-8")

    @staticmethod
    def _skill_paths_in_tree(repo, tree) -> list[str]:
        paths: list[str] = []

        def walk(current, parts: list[str]) -> None:
            for entry in current.iteritems():
                name = entry.path.decode()
                if name in _SKIP_DIRS or name.startswith("."):
                    continue
                rel_parts = parts + [name]
                rel = "/".join(rel_parts)
                obj = repo[entry.sha]
                if obj.type_name == b"tree":
                    walk(obj, rel_parts)
                elif rel.startswith("skills/"):
                    paths.append(rel)

        walk(tree, [])
        return sorted(paths)

    @staticmethod
    def _prune_empty_dirs(path: Path) -> None:
        current = path
        skills_root = path
        while current != current.parent:
            if current.name == "skills":
                skills_root = current
                break
            current = current.parent

        current = path
        while current != skills_root and current.is_dir():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
