"""Workspace sandbox management — all artifacts stay under workspace root."""

from __future__ import annotations

from pathlib import Path


class WorkspaceManager:
    """Enforces workspace isolation for GeoClaw file operations."""

    def __init__(self, workspace: Path):
        self._root = workspace.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def runs_dir(self) -> Path:
        d = self._root / "runs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def skills_dir(self) -> Path:
        d = self._root / "skills"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def resolve_path(self, user_path: str) -> Path:
        """Resolve a user-supplied path, enforcing sandbox boundaries.

        Relative paths are resolved against the workspace root.
        Absolute paths are allowed only if they fall under the workspace.
        """
        p = Path(user_path).expanduser()
        if not p.is_absolute():
            p = self._root / p
        resolved = p.resolve()
        if not self._is_under(resolved, self._root):
            raise PermissionError(
                f"Path '{user_path}' resolves to '{resolved}' which is outside "
                f"workspace '{self._root}'"
            )
        return resolved

    def resolve_input_path(self, user_path: str) -> Path:
        """Resolve an input file path — allows reading from anywhere that exists."""
        p = Path(user_path).expanduser()
        if not p.is_absolute():
            p = self._root / p
        resolved = p.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Input path does not exist: {resolved}")
        return resolved

    def new_run_dir(self, run_id: str) -> Path:
        """Create and return a run directory."""
        d = self.runs_dir / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _is_under(path: Path, directory: Path) -> bool:
        try:
            path.relative_to(directory)
            return True
        except ValueError:
            return False
