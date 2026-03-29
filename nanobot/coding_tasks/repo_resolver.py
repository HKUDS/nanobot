"""Repo reference resolution for coding-task entrypoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class RepoRefResolver:
    """Resolve a repo alias or path into a local absolute repository path."""

    aliases: dict[str, str] = field(default_factory=dict)

    def resolve(self, repo_ref: str) -> Path:
        """Resolve a repo reference to a local candidate path."""
        raw = repo_ref.strip()
        if not raw:
            return Path(raw)
        if _looks_like_repo_path(raw):
            return Path(raw).expanduser()

        alias_match = self.aliases.get(raw)
        if alias_match is None:
            alias_match = self.aliases.get(raw.lower())
        if alias_match is not None:
            return Path(alias_match).expanduser()

        return Path.home() / "Documents" / raw

    def can_resolve_existing(self, repo_ref: str) -> bool:
        """Return True when the repo reference resolves to an existing directory."""
        candidate = self.resolve(repo_ref)
        return candidate.exists() and candidate.is_dir()


def _looks_like_repo_path(token: str) -> bool:
    return token.startswith(("/", "~", "./", "../")) or "/" in token
