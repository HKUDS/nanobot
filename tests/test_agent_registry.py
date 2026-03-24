"""Tests for the AgentRegistry."""

from __future__ import annotations

from nanobot.config.schema import AgentRoleConfig
from nanobot.coordination.registry import AgentRegistry


def _role(name: str, *, enabled: bool = True, description: str = "") -> AgentRoleConfig:
    return AgentRoleConfig(name=name, description=description, enabled=enabled)


class TestAgentRegistry:
    def test_register_and_get(self) -> None:
        reg = AgentRegistry()
        role = _role("code", description="Coding tasks")
        reg.register(role)
        assert reg.get("code") is role

    def test_get_missing_returns_none(self) -> None:
        reg = AgentRegistry()
        assert reg.get("nonexistent") is None

    def test_contains(self) -> None:
        reg = AgentRegistry()
        reg.register(_role("research"))
        assert "research" in reg
        assert "writing" not in reg

    def test_len(self) -> None:
        reg = AgentRegistry()
        assert len(reg) == 0
        reg.register(_role("a"))
        reg.register(_role("b"))
        assert len(reg) == 2

    def test_override_existing_role(self) -> None:
        reg = AgentRegistry()
        old = _role("code", description="old")
        new = _role("code", description="new")
        reg.register(old)
        reg.register(new)
        assert len(reg) == 1
        assert reg.get("code") is new

    def test_get_default(self) -> None:
        reg = AgentRegistry(default_role="general")
        general = _role("general")
        reg.register(general)
        reg.register(_role("code"))
        assert reg.get_default() is general

    def test_get_default_missing(self) -> None:
        reg = AgentRegistry(default_role="missing")
        assert reg.get_default() is None

    def test_list_roles_excludes_disabled(self) -> None:
        reg = AgentRegistry()
        reg.register(_role("code", enabled=True))
        reg.register(_role("hidden", enabled=False))
        reg.register(_role("general", enabled=True))
        roles = reg.list_roles()
        names = [r.name for r in roles]
        assert "code" in names
        assert "general" in names
        assert "hidden" not in names

    def test_role_names_excludes_disabled(self) -> None:
        reg = AgentRegistry()
        reg.register(_role("code"))
        reg.register(_role("off", enabled=False))
        assert reg.role_names() == ["code"]

    def test_role_names_empty(self) -> None:
        reg = AgentRegistry()
        assert reg.role_names() == []


class TestMergeRegister:
    """Tests for field-level merge when overriding existing roles."""

    def test_new_role_registered_as_is(self) -> None:
        reg = AgentRegistry()
        role = AgentRoleConfig(name="data", description="Data tasks")
        reg.merge_register(role)
        assert reg.get("data") is role

    def test_merge_preserves_unset_fields(self) -> None:
        """Config that only sets 'model' should keep the default's other fields."""
        reg = AgentRegistry()
        default = AgentRoleConfig(
            name="code",
            description="Coding tasks",
            system_prompt="You are an engineer.",
            denied_tools=["web_fetch"],
        )
        reg.register(default)
        # Config override only specifies name + model
        override = AgentRoleConfig(name="code", model="gpt-4o")
        reg.merge_register(override)

        merged = reg.get("code")
        assert merged is not None
        assert merged.model == "gpt-4o"  # overridden
        assert merged.description == "Coding tasks"  # preserved
        assert merged.system_prompt == "You are an engineer."  # preserved
        assert merged.denied_tools == ["web_fetch"]  # preserved

    def test_merge_overrides_explicit_fields_only(self) -> None:
        reg = AgentRegistry()
        reg.register(
            AgentRoleConfig(
                name="research",
                description="Original",
                system_prompt="Original prompt",
                denied_tools=["exec"],
            )
        )
        override = AgentRoleConfig(
            name="research",
            description="Updated description",
            denied_tools=["write_file"],
        )
        reg.merge_register(override)

        merged = reg.get("research")
        assert merged is not None
        assert merged.description == "Updated description"
        assert merged.denied_tools == ["write_file"]
        assert merged.system_prompt == "Original prompt"  # not in override → preserved

    def test_merge_no_op_when_only_name_set(self) -> None:
        """Override with only 'name' should leave the role unchanged."""
        reg = AgentRegistry()
        original = AgentRoleConfig(name="pm", description="PM role", denied_tools=["exec"])
        reg.register(original)

        reg.merge_register(AgentRoleConfig(name="pm"))
        assert reg.get("pm") is original  # no fields to merge → same object
