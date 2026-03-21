"""Agent registry for multi-agent routing.

Maps role names to ``AgentRoleConfig`` instances so the coordinator
can look up which agent should handle a given message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import AgentRoleConfig


class AgentRegistry:
    """Registry of named agent roles.

    Thin wrapper around a dict that maps role names to their configs.
    The coordinator uses this to resolve classification results to
    concrete agent configurations.
    """

    def __init__(self, default_role: str = "general") -> None:
        self._roles: dict[str, AgentRoleConfig] = {}
        self._default_role = default_role
        self._cached_roles: list[AgentRoleConfig] | None = None
        self._cached_role_names: list[str] | None = None

    def _invalidate_cache(self) -> None:
        """Invalidate cached role lists after any write operation."""
        self._cached_roles = None
        self._cached_role_names = None

    def register(self, role: AgentRoleConfig) -> None:
        """Register an agent role config by its name."""
        if role.name in self._roles:
            logger.debug("Overriding existing agent role: {}", role.name)
        self._roles[role.name] = role
        self._invalidate_cache()

    def merge_register(self, role: AgentRoleConfig) -> None:
        """Register a role, merging explicitly-set fields into any existing entry.

        If *role.name* already exists, only fields the caller explicitly set
        (tracked via Pydantic's ``model_fields_set``) overwrite the existing
        values — unset fields keep the previous defaults.

        If the role is new, it is registered as-is.
        """
        existing = self._roles.get(role.name)
        if existing is None:
            self._roles[role.name] = role
            return
        overrides = {f: getattr(role, f) for f in role.model_fields_set if f != "name"}
        if overrides:
            merged = existing.model_copy(update=overrides)
            self._roles[role.name] = merged
            logger.debug("Merged config into role '{}': {}", role.name, list(overrides))
        self._invalidate_cache()

    def get(self, name: str) -> AgentRoleConfig | None:
        """Look up a role by name. Returns None if not found."""
        return self._roles.get(name)

    def get_default(self) -> AgentRoleConfig | None:
        """Return the default (fallback) role."""
        return self._roles.get(self._default_role)

    def list_roles(self) -> list[AgentRoleConfig]:
        """Return all registered roles (enabled only)."""
        if self._cached_roles is None:
            self._cached_roles = [r for r in self._roles.values() if r.enabled]
        return self._cached_roles

    def role_names(self) -> list[str]:
        """Return names of all enabled roles."""
        if self._cached_role_names is None:
            self._cached_role_names = [r.name for r in self._roles.values() if r.enabled]
        return self._cached_role_names

    def __len__(self) -> int:
        return len(self._roles)

    def __contains__(self, name: str) -> bool:
        # Respect the enabled flag so disabled roles cannot be routed to (LAN-123).
        role = self._roles.get(name)
        return role is not None and role.enabled
