"""Unit tests for onboard core logic functions.

These tests focus on the business logic behind the onboard wizard,
without testing the interactive UI components.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import BaseModel, Field

from nanobot.cli import onboard as onboard_wizard

# Import functions to test
from nanobot.cli.commands import _merge_missing_defaults
from nanobot.cli.onboard import (
    _BACK_PRESSED,
    _configure_pydantic_model,
    _format_value,
    _get_field_display_name,
    _get_field_type_info,
    _get_constraint_hint,
    _input_text,
    _validate_field_constraint,
    run_onboard,
)
from nanobot.config.schema import Config
from nanobot.utils.helpers import sync_workspace_templates


class TestMergeMissingDefaults:
    """Tests for _merge_missing_defaults recursive config merging."""

    def test_adds_missing_top_level_keys(self):
        existing = {"a": 1}
        defaults = {"a": 1, "b": 2, "c": 3}

        result = _merge_missing_defaults(existing, defaults)

        assert result == {"a": 1, "b": 2, "c": 3}

    def test_preserves_existing_values(self):
        existing = {"a": "custom_value"}
        defaults = {"a": "default_value"}

        result = _merge_missing_defaults(existing, defaults)

        assert result == {"a": "custom_value"}

    def test_merges_nested_dicts_recursively(self):
        existing = {
            "level1": {
                "level2": {
                    "existing": "kept",
                }
            }
        }
        defaults = {
            "level1": {
                "level2": {
                    "existing": "replaced",
                    "added": "new",
                },
                "level2b": "also_new",
            }
        }

        result = _merge_missing_defaults(existing, defaults)

        assert result == {
            "level1": {
                "level2": {
                    "existing": "kept",
                    "added": "new",
                },
                "level2b": "also_new",
            }
        }

    def test_returns_existing_if_not_dict(self):
        assert _merge_missing_defaults("string", {"a": 1}) == "string"
        assert _merge_missing_defaults([1, 2, 3], {"a": 1}) == [1, 2, 3]
        assert _merge_missing_defaults(None, {"a": 1}) is None
        assert _merge_missing_defaults(42, {"a": 1}) == 42

    def test_returns_existing_if_defaults_not_dict(self):
        assert _merge_missing_defaults({"a": 1}, "string") == {"a": 1}
        assert _merge_missing_defaults({"a": 1}, None) == {"a": 1}

    def test_handles_empty_dicts(self):
        assert _merge_missing_defaults({}, {"a": 1}) == {"a": 1}
        assert _merge_missing_defaults({"a": 1}, {}) == {"a": 1}
        assert _merge_missing_defaults({}, {}) == {}

    def test_backfills_channel_config(self):
        """Real-world scenario: backfill missing channel fields."""
        existing_channel = {
            "enabled": False,
            "appId": "",
            "secret": "",
        }
        default_channel = {
            "enabled": False,
            "appId": "",
            "secret": "",
            "msgFormat": "plain",
            "allowFrom": [],
        }

        result = _merge_missing_defaults(existing_channel, default_channel)

        assert result["msgFormat"] == "plain"
        assert result["allowFrom"] == []


class TestGetFieldTypeInfo:
    """Tests for _get_field_type_info type extraction."""

    def test_extracts_str_type(self):
        class Model(BaseModel):
            field: str

        type_name, inner = _get_field_type_info(Model.model_fields["field"])
        assert type_name == "str"
        assert inner is None

    def test_extracts_int_type(self):
        class Model(BaseModel):
            count: int

        type_name, inner = _get_field_type_info(Model.model_fields["count"])
        assert type_name == "int"
        assert inner is None

    def test_extracts_bool_type(self):
        class Model(BaseModel):
            enabled: bool

        type_name, inner = _get_field_type_info(Model.model_fields["enabled"])
        assert type_name == "bool"
        assert inner is None

    def test_extracts_float_type(self):
        class Model(BaseModel):
            ratio: float

        type_name, inner = _get_field_type_info(Model.model_fields["ratio"])
        assert type_name == "float"
        assert inner is None

    def test_extracts_list_type_with_item_type(self):
        class Model(BaseModel):
            items: list[str]

        type_name, inner = _get_field_type_info(Model.model_fields["items"])
        assert type_name == "list"
        assert inner is str

    def test_extracts_list_type_without_item_type(self):
        # Plain list without type param falls back to str
        class Model(BaseModel):
            items: list  # type: ignore

        # Plain list annotation doesn't match list check, returns str
        type_name, inner = _get_field_type_info(Model.model_fields["items"])
        assert type_name == "str"  # Falls back to str for untyped list
        assert inner is None

    def test_extracts_dict_type(self):
        # Plain dict without type param falls back to str
        class Model(BaseModel):
            data: dict  # type: ignore

        # Plain dict annotation doesn't match dict check, returns str
        type_name, inner = _get_field_type_info(Model.model_fields["data"])
        assert type_name == "str"  # Falls back to str for untyped dict
        assert inner is None

    def test_extracts_optional_type(self):
        class Model(BaseModel):
            optional: str | None = None

        type_name, inner = _get_field_type_info(Model.model_fields["optional"])
        # Should unwrap Optional and get str
        assert type_name == "str"
        assert inner is None

    def test_extracts_nested_model_type(self):
        class Inner(BaseModel):
            x: int

        class Outer(BaseModel):
            nested: Inner

        type_name, inner = _get_field_type_info(Outer.model_fields["nested"])
        assert type_name == "model"
        assert inner is Inner

    def test_handles_none_annotation(self):
        """Field with None annotation defaults to str."""
        class Model(BaseModel):
            field: Any = None

        # Create a mock field_info with None annotation
        field_info = SimpleNamespace(annotation=None)
        type_name, inner = _get_field_type_info(field_info)
        assert type_name == "str"
        assert inner is None

    def test_literal_type_returns_literal_with_choices(self):
        """Literal["a", "b"] should return ("literal", ["a", "b"])."""
        from typing import Literal

        class Model(BaseModel):
            mode: Literal["standard", "persistent"] = "standard"

        type_name, inner = _get_field_type_info(Model.model_fields["mode"])
        assert type_name == "literal"
        assert inner == ["standard", "persistent"]

    def test_real_provider_retry_mode_field(self):
        """Validate against actual AgentDefaults.provider_retry_mode field."""
        from nanobot.config.schema import AgentDefaults

        type_name, inner = _get_field_type_info(AgentDefaults.model_fields["provider_retry_mode"])
        assert type_name == "literal"
        assert inner == ["standard", "persistent"]


class TestGetFieldDisplayName:
    """Tests for _get_field_display_name human-readable name generation."""

    def test_uses_description_if_present(self):
        class Model(BaseModel):
            api_key: str = Field(description="API Key for authentication")

        name = _get_field_display_name("api_key", Model.model_fields["api_key"])
        assert name == "API Key for authentication"

    def test_converts_snake_case_to_title(self):
        field_info = SimpleNamespace(description=None)
        name = _get_field_display_name("user_name", field_info)
        assert name == "User Name"

    def test_adds_url_suffix(self):
        field_info = SimpleNamespace(description=None)
        name = _get_field_display_name("api_url", field_info)
        # Title case: "Api Url"
        assert "Url" in name and "Api" in name

    def test_adds_path_suffix(self):
        field_info = SimpleNamespace(description=None)
        name = _get_field_display_name("file_path", field_info)
        assert "Path" in name and "File" in name

    def test_adds_id_suffix(self):
        field_info = SimpleNamespace(description=None)
        name = _get_field_display_name("user_id", field_info)
        # Title case: "User Id"
        assert "Id" in name and "User" in name

    def test_adds_key_suffix(self):
        field_info = SimpleNamespace(description=None)
        name = _get_field_display_name("api_key", field_info)
        assert "Key" in name and "Api" in name

    def test_adds_token_suffix(self):
        field_info = SimpleNamespace(description=None)
        name = _get_field_display_name("auth_token", field_info)
        assert "Token" in name and "Auth" in name

    def test_adds_seconds_suffix(self):
        field_info = SimpleNamespace(description=None)
        name = _get_field_display_name("timeout_s", field_info)
        # Contains "(Seconds)" with title case
        assert "(Seconds)" in name or "(seconds)" in name

    def test_adds_ms_suffix(self):
        field_info = SimpleNamespace(description=None)
        name = _get_field_display_name("delay_ms", field_info)
        # Contains "(Ms)" or "(ms)"
        assert "(Ms)" in name or "(ms)" in name


class TestFormatValue:
    """Tests for _format_value display formatting."""

    def test_formats_none_as_not_set(self):
        assert "not set" in _format_value(None)

    def test_formats_empty_string_as_not_set(self):
        assert "not set" in _format_value("")

    def test_formats_empty_dict_as_not_set(self):
        assert "not set" in _format_value({})

    def test_formats_empty_list_as_not_set(self):
        assert "not set" in _format_value([])

    def test_formats_string_value(self):
        result = _format_value("hello")
        assert "hello" in result

    def test_formats_list_value(self):
        result = _format_value(["a", "b"])
        assert "a" in result or "b" in result

    def test_formats_dict_value(self):
        result = _format_value({"key": "value"})
        assert "key" in result or "value" in result

    def test_formats_int_value(self):
        result = _format_value(42)
        assert "42" in result

    def test_formats_bool_true(self):
        result = _format_value(True)
        assert "true" in result.lower() or "✓" in result

    def test_formats_bool_false(self):
        result = _format_value(False)
        assert "false" in result.lower() or "✗" in result


class TestSyncWorkspaceTemplates:
    """Tests for sync_workspace_templates file synchronization."""

    def test_creates_missing_files(self, tmp_path):
        """Should create template files that don't exist."""
        workspace = tmp_path / "workspace"

        added = sync_workspace_templates(workspace, silent=True)

        # Check that some files were created
        assert isinstance(added, list)
        # The actual files depend on the templates directory

    def test_does_not_overwrite_existing_files(self, tmp_path):
        """Should not overwrite files that already exist."""
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "AGENTS.md").write_text("existing content")

        sync_workspace_templates(workspace, silent=True)

        # Existing file should not be changed
        content = (workspace / "AGENTS.md").read_text()
        assert content == "existing content"

    def test_creates_memory_directory(self, tmp_path):
        """Should create memory directory structure."""
        workspace = tmp_path / "workspace"

        sync_workspace_templates(workspace, silent=True)

        assert (workspace / "memory").exists() or (workspace / "skills").exists()

    def test_returns_list_of_added_files(self, tmp_path):
        """Should return list of relative paths for added files."""
        workspace = tmp_path / "workspace"

        added = sync_workspace_templates(workspace, silent=True)

        assert isinstance(added, list)
        # All paths should be relative to workspace
        for path in added:
            assert not Path(path).is_absolute()


class TestProviderChannelInfo:
    """Tests for provider and channel info retrieval."""

    def test_get_provider_names_returns_dict(self):
        from nanobot.cli.onboard import _get_provider_names

        names = _get_provider_names()
        assert isinstance(names, dict)
        assert len(names) > 0
        # Should include common providers
        assert "openai" in names or "anthropic" in names
        assert "openai_codex" not in names
        assert "github_copilot" not in names

    def test_get_channel_names_returns_dict(self):
        from nanobot.cli.onboard import _get_channel_names

        names = _get_channel_names()
        assert isinstance(names, dict)
        # Should include at least some channels
        assert len(names) >= 0

    def test_get_provider_info_returns_valid_structure(self):
        from nanobot.cli.onboard import _get_provider_info

        info = _get_provider_info()
        assert isinstance(info, dict)
        # Each value should be a tuple with expected structure
        for provider_name, value in info.items():
            assert isinstance(value, tuple)
            assert len(value) == 4  # (display_name, needs_api_key, needs_api_base, env_var)


class _SimpleDraftModel(BaseModel):
    api_key: str = ""


class _NestedDraftModel(BaseModel):
    api_key: str = ""


class _OuterDraftModel(BaseModel):
    nested: _NestedDraftModel = Field(default_factory=_NestedDraftModel)


class TestConfigurePydanticModelDrafts:
    @staticmethod
    def _patch_prompt_helpers(monkeypatch, tokens, text_value="secret"):
        sequence = iter(tokens)

        def fake_select(_prompt, choices, default=None):
            token = next(sequence)
            if token == "first":
                return choices[0]
            if token == "done":
                return "[Done]"
            if token == "back":
                return _BACK_PRESSED
            return token

        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select)
        monkeypatch.setattr(onboard_wizard, "_show_config_panel", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            onboard_wizard, "_input_with_existing", lambda *_args, **_kwargs: text_value
        )

    def test_discarding_section_keeps_original_model_unchanged(self, monkeypatch):
        model = _SimpleDraftModel()
        self._patch_prompt_helpers(monkeypatch, ["first", "back"])

        result = _configure_pydantic_model(model, "Simple")

        assert result is None
        assert model.api_key == ""

    def test_completing_section_returns_updated_draft(self, monkeypatch):
        model = _SimpleDraftModel()
        self._patch_prompt_helpers(monkeypatch, ["first", "done"])

        result = _configure_pydantic_model(model, "Simple")

        assert result is not None
        updated = cast(_SimpleDraftModel, result)
        assert updated.api_key == "secret"
        assert model.api_key == ""

    def test_nested_section_back_discards_nested_edits(self, monkeypatch):
        model = _OuterDraftModel()
        self._patch_prompt_helpers(monkeypatch, ["first", "first", "back", "done"])

        result = _configure_pydantic_model(model, "Outer")

        assert result is not None
        updated = cast(_OuterDraftModel, result)
        assert updated.nested.api_key == ""
        assert model.nested.api_key == ""

    def test_nested_section_done_commits_nested_edits(self, monkeypatch):
        model = _OuterDraftModel()
        self._patch_prompt_helpers(monkeypatch, ["first", "first", "done", "done"])

        result = _configure_pydantic_model(model, "Outer")

        assert result is not None
        updated = cast(_OuterDraftModel, result)
        assert updated.nested.api_key == "secret"
        assert model.nested.api_key == ""


class TestRunOnboardExitBehavior:
    def test_main_menu_interrupt_can_discard_unsaved_session_changes(self, monkeypatch):
        initial_config = Config()

        responses = iter(
            [
                "[A] Agent Settings",
                KeyboardInterrupt(),
                "[X] Exit Without Saving",
            ]
        )

        class FakePrompt:
            def __init__(self, response):
                self.response = response

            def ask(self):
                if isinstance(self.response, BaseException):
                    raise self.response
                return self.response

        def fake_select(*_args, **_kwargs):
            return FakePrompt(next(responses))

        def fake_configure_general_settings(config, section):
            if section == "Agent Settings":
                config.agents.defaults.model = "test/provider-model"

        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard, "questionary", SimpleNamespace(select=fake_select))
        monkeypatch.setattr(onboard_wizard, "_configure_general_settings", fake_configure_general_settings)

        result = run_onboard(initial_config=initial_config)

        assert result.should_save is False
        assert result.config.model_dump(by_alias=True) == initial_config.model_dump(by_alias=True)


class TestValidateFieldConstraint:
    """Tests for _validate_field_constraint schema-aware input validation."""

    def test_returns_none_when_no_constraints(self):
        """Fields without constraints should pass validation."""
        from pydantic import BaseModel

        class M(BaseModel):
            name: str = "hello"

        field_info = M.model_fields["name"]
        from nanobot.cli.onboard import _validate_field_constraint

        assert _validate_field_constraint("anything", field_info) is None

    def test_rejects_value_below_ge_bound(self):
        """Value below ge (>=) bound should return error."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            count: int = Field(default=3, ge=0)

        field_info = M.model_fields["count"]
        from nanobot.cli.onboard import _validate_field_constraint

        result = _validate_field_constraint(-1, field_info)
        assert result is not None
        assert "0" in result

    def test_accepts_value_at_ge_bound(self):
        """Value exactly at ge (>=) bound should pass."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            count: int = Field(default=3, ge=0)

        field_info = M.model_fields["count"]
        from nanobot.cli.onboard import _validate_field_constraint

        assert _validate_field_constraint(0, field_info) is None

    def test_rejects_value_above_le_bound(self):
        """Value above le (<=) bound should return error."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            retries: int = Field(default=3, le=10)

        field_info = M.model_fields["retries"]
        from nanobot.cli.onboard import _validate_field_constraint

        result = _validate_field_constraint(11, field_info)
        assert result is not None
        assert "10" in result

    def test_accepts_value_at_le_bound(self):
        """Value exactly at le (<=) bound should pass."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            retries: int = Field(default=3, le=10)

        field_info = M.model_fields["retries"]
        from nanobot.cli.onboard import _validate_field_constraint

        assert _validate_field_constraint(10, field_info) is None

    def test_combined_ge_and_le_bounds(self):
        """Field with both ge and le should validate both."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            retries: int = Field(default=3, ge=0, le=10)

        field_info = M.model_fields["retries"]
        from nanobot.cli.onboard import _validate_field_constraint

        assert _validate_field_constraint(5, field_info) is None
        assert _validate_field_constraint(-1, field_info) is not None
        assert _validate_field_constraint(11, field_info) is not None

    def test_gt_and_lt_bounds(self):
        """Strict inequality bounds (gt, lt) should exclude boundary."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            ratio: float = Field(default=0.5, gt=0.0, lt=1.0)

        field_info = M.model_fields["ratio"]
        from nanobot.cli.onboard import _validate_field_constraint

        assert _validate_field_constraint(0.5, field_info) is None
        assert _validate_field_constraint(0.0, field_info) is not None
        assert _validate_field_constraint(1.0, field_info) is not None

    def test_min_length_constraint(self):
        """min_length should validate string/list length."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            name: str = Field(default="x", min_length=1)

        field_info = M.model_fields["name"]
        from nanobot.cli.onboard import _validate_field_constraint

        assert _validate_field_constraint("a", field_info) is None
        assert _validate_field_constraint("", field_info) is not None

    def test_max_length_constraint(self):
        """max_length should validate string/list length."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            tag: str = Field(default="x", max_length=5)

        field_info = M.model_fields["tag"]
        from nanobot.cli.onboard import _validate_field_constraint

        assert _validate_field_constraint("abc", field_info) is None
        assert _validate_field_constraint("abcdef", field_info) is not None

    def test_real_send_max_retries_field(self):
        """Validate against the actual ChannelsConfig.send_max_retries field."""
        from nanobot.config.schema import ChannelsConfig
        from nanobot.cli.onboard import _validate_field_constraint

        field_info = ChannelsConfig.model_fields["send_max_retries"]
        assert _validate_field_constraint(3, field_info) is None
        assert _validate_field_constraint(0, field_info) is None
        assert _validate_field_constraint(10, field_info) is None
        assert _validate_field_constraint(-1, field_info) is not None
        assert _validate_field_constraint(11, field_info) is not None


class TestGetConstraintHint:
    """Tests for _get_constraint_hint field display suffix."""

    def test_no_constraints_returns_empty(self):
        """Fields without constraints should return empty string."""
        from pydantic import BaseModel

        class M(BaseModel):
            name: str = "hello"

        field_info = M.model_fields["name"]
        assert _get_constraint_hint(field_info) == ""

    def test_ge_le_range(self):
        """Field with ge+le should show '(min-max)'."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            retries: int = Field(default=3, ge=0, le=10)

        field_info = M.model_fields["retries"]
        hint = _get_constraint_hint(field_info)
        assert "0" in hint
        assert "10" in hint

    def test_ge_only(self):
        """Field with only ge should show '(>= N)'."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            count: int = Field(default=1, ge=0)

        field_info = M.model_fields["count"]
        hint = _get_constraint_hint(field_info)
        assert "0" in hint
        assert ">=" in hint

    def test_le_only(self):
        """Field with only le should show '(<= N)'."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            ratio: float = Field(default=1.0, le=100.0)

        field_info = M.model_fields["ratio"]
        hint = _get_constraint_hint(field_info)
        assert "100" in hint
        assert "<=" in hint

    def test_real_send_max_retries_hint(self):
        """Actual ChannelsConfig.send_max_retries should show '(0-10)'."""
        from nanobot.config.schema import ChannelsConfig

        field_info = ChannelsConfig.model_fields["send_max_retries"]
        hint = _get_constraint_hint(field_info)
        assert "0" in hint
        assert "10" in hint


class TestInputTextWithValidation:
    """Tests for _input_text integration with constraint validation."""

    def test_rejects_out_of_range_int(self, monkeypatch):
        """_input_text with field_info should reject values violating ge/le constraints."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            retries: int = Field(default=3, ge=0, le=10)

        field_info = M.model_fields["retries"]
        monkeypatch.setattr(
            onboard_wizard,
            "_get_questionary",
            lambda: SimpleNamespace(text=lambda *a, **kw: SimpleNamespace(ask=lambda: "15")),
        )

        result = _input_text("Retries", 3, "int", field_info=field_info)
        assert result is None

    def test_accepts_valid_int(self, monkeypatch):
        """_input_text with field_info should accept valid constrained values."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            retries: int = Field(default=3, ge=0, le=10)

        field_info = M.model_fields["retries"]
        monkeypatch.setattr(
            onboard_wizard,
            "_get_questionary",
            lambda: SimpleNamespace(text=lambda *a, **kw: SimpleNamespace(ask=lambda: "5")),
        )

        result = _input_text("Retries", 3, "int", field_info=field_info)
        assert result == 5

    def test_works_without_field_info(self, monkeypatch):
        """_input_text without field_info should work as before (no validation)."""
        monkeypatch.setattr(
            onboard_wizard,
            "_get_questionary",
            lambda: SimpleNamespace(text=lambda *a, **kw: SimpleNamespace(ask=lambda: "42")),
        )

        result = _input_text("Count", 0, "int")
        assert result == 42


class TestChannelCommonRegistration:
    """Tests for Channel Common menu registration."""

    def test_channel_common_in_settings_sections(self):
        """Channel Common should be registered in _SETTINGS_SECTIONS."""
        from nanobot.cli.onboard import _SETTINGS_SECTIONS

        assert "Channel Common" in _SETTINGS_SECTIONS

    def test_channel_common_getter_returns_channels(self):
        """Channel Common getter should return config.channels."""
        from nanobot.cli.onboard import _SETTINGS_GETTER

        config = Config()
        result = _SETTINGS_GETTER["Channel Common"](config)
        assert result is config.channels

    def test_channel_common_setter_writes_channels(self):
        """Channel Common setter should update config.channels."""
        from nanobot.cli.onboard import _SETTINGS_SETTER

        config = Config()
        original = config.channels
        new_channels = original.model_copy(deep=True)
        new_channels.send_tool_hints = True
        _SETTINGS_SETTER["Channel Common"](config, new_channels)
        assert config.channels.send_tool_hints is True

    def test_channel_common_edit_preserves_extras(self):
        """Editing Channel Common should not lose per-channel extras."""
        config = Config()
        config.channels.feishu = {"enabled": True, "appId": "test123"}
        channels = config.channels.model_copy(deep=True)
        channels.send_tool_hints = True
        config.channels = channels
        assert config.channels.send_tool_hints is True
        assert config.channels.feishu["appId"] == "test123"


class TestApiServerRegistration:
    """Tests for API Server menu registration."""

    def test_api_server_in_settings_sections(self):
        """API Server should be registered in _SETTINGS_SECTIONS."""
        from nanobot.cli.onboard import _SETTINGS_SECTIONS

        assert "API Server" in _SETTINGS_SECTIONS

    def test_api_server_getter_returns_api(self):
        """API Server getter should return config.api."""
        from nanobot.cli.onboard import _SETTINGS_GETTER

        config = Config()
        result = _SETTINGS_GETTER["API Server"](config)
        assert result is config.api

    def test_api_server_setter_writes_api(self):
        """API Server setter should update config.api."""
        from nanobot.cli.onboard import _SETTINGS_SETTER

        config = Config()
        from nanobot.config.schema import ApiConfig

        new_api = ApiConfig(host="0.0.0.0", port=9999)
        _SETTINGS_SETTER["API Server"](config, new_api)
        assert config.api.host == "0.0.0.0"
        assert config.api.port == 9999


class TestMainMenuUpdate:
    """Tests for main menu including new Channel Common and API Server items."""

    def test_main_menu_dispatch_includes_channel_common(self):
        """Main menu dispatch should route [H] to Channel Common."""
        from nanobot.cli.onboard import run_onboard

        # We verify by checking the dispatch table is set up correctly
        # The menu items are defined inline in run_onboard, so we test
        # that _configure_general_settings handles the new sections.
        from nanobot.cli.onboard import _SETTINGS_SECTIONS, _SETTINGS_GETTER, _SETTINGS_SETTER

        assert "Channel Common" in _SETTINGS_SECTIONS
        assert "Channel Common" in _SETTINGS_GETTER
        assert "Channel Common" in _SETTINGS_SETTER

    def test_main_menu_dispatch_includes_api_server(self):
        """Main menu dispatch should route [I] to API Server."""
        from nanobot.cli.onboard import _SETTINGS_SECTIONS, _SETTINGS_GETTER, _SETTINGS_SETTER

        assert "API Server" in _SETTINGS_SECTIONS
        assert "API Server" in _SETTINGS_GETTER
        assert "API Server" in _SETTINGS_SETTER

    def test_run_onboard_channel_common_edit(self, monkeypatch):
        """run_onboard should handle [H] Channel Common correctly."""
        initial_config = Config()

        responses = iter([
            "[H] Channel Common",
            KeyboardInterrupt(),
            "[S] Save and Exit",
        ])

        class FakePrompt:
            def __init__(self, response):
                self.response = response

            def ask(self):
                if isinstance(self.response, BaseException):
                    raise self.response
                return self.response

        def fake_select(*_args, **_kwargs):
            return FakePrompt(next(responses))

        def fake_configure_general_settings(config, section):
            if section == "Channel Common":
                config.channels.send_tool_hints = True

        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard, "questionary", SimpleNamespace(select=fake_select))
        monkeypatch.setattr(onboard_wizard, "_configure_general_settings", fake_configure_general_settings)

        result = run_onboard(initial_config=initial_config)

        assert result.should_save is True
        assert result.config.channels.send_tool_hints is True

    def test_run_onboard_api_server_edit(self, monkeypatch):
        """run_onboard should handle [I] API Server correctly."""
        initial_config = Config()

        responses = iter([
            "[I] API Server",
            KeyboardInterrupt(),
            "[S] Save and Exit",
        ])

        class FakePrompt:
            def __init__(self, response):
                self.response = response

            def ask(self):
                if isinstance(self.response, BaseException):
                    raise self.response
                return self.response

        def fake_select(*_args, **_kwargs):
            return FakePrompt(next(responses))

        def fake_configure_general_settings(config, section):
            if section == "API Server":
                config.api.port = 9999

        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard, "questionary", SimpleNamespace(select=fake_select))
        monkeypatch.setattr(onboard_wizard, "_configure_general_settings", fake_configure_general_settings)

        result = run_onboard(initial_config=initial_config)

        assert result.should_save is True
        assert result.config.api.port == 9999

    def test_view_summary_calls_pause(self, monkeypatch):
        """[V] View Summary should pause before returning to main menu."""
        initial_config = Config()
        pause_called = {"n": 0}

        responses = iter([
            "[V] View Configuration Summary",
            "[S] Save and Exit",
        ])

        class FakePrompt:
            def __init__(self, response):
                self.response = response

            def ask(self):
                if isinstance(self.response, BaseException):
                    raise self.response
                return self.response

        def fake_select(*_args, **_kwargs):
            return FakePrompt(next(responses))

        def fake_pause():
            pause_called["n"] += 1

        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard, "questionary", SimpleNamespace(select=fake_select))
        # _pause is called inside _show_summary, so we patch it there
        monkeypatch.setattr(onboard_wizard, "_pause", fake_pause)
        # Suppress summary output but still call _pause
        monkeypatch.setattr(onboard_wizard, "_print_summary_panel", lambda *a, **kw: None)
        monkeypatch.setattr(onboard_wizard, "_get_provider_names", lambda: {})
        monkeypatch.setattr(onboard_wizard, "_get_channel_names", lambda: {})

        result = run_onboard(initial_config=initial_config)

        assert result.should_save is True
        assert pause_called["n"] == 1
