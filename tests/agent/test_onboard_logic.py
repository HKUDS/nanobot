"""Unit tests for onboard core logic functions.

These tests focus on the business logic behind the onboard wizard,
without testing the interactive UI components.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from pydantic import BaseModel, Field

from nanobot.cli import onboard as onboard_wizard
from nanobot.cli.commands import _merge_missing_defaults
from nanobot.cli.onboard import (
    _BACK_PRESSED,
    _configure_pydantic_model,
    _format_value,
    _get_constraint_hint,
    _get_field_display_name,
    _get_field_type_info,
    _input_text,
    run_onboard,
)
from nanobot.config.schema import Config, ModelPresetConfig
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
        assert "Seconds" in name or "seconds" in name
        assert "(" not in name
        assert ")" not in name

    def test_adds_ms_suffix(self):
        field_info = SimpleNamespace(description=None)
        name = _get_field_display_name("delay_ms", field_info)
        assert "Ms" in name or "ms" in name
        assert "(" not in name
        assert ")" not in name


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

    def test_does_not_create_tools_md(self, tmp_path):
        """Tool contract is injected internally, not copied into user workspaces."""
        workspace = tmp_path / "workspace"

        added = sync_workspace_templates(workspace, silent=True)

        assert "TOOLS.md" not in added
        assert not (workspace / "TOOLS.md").exists()

    def test_preserves_existing_tools_md_without_overwriting(self, tmp_path):
        """Legacy user workspaces may have TOOLS.md; sync should leave it untouched."""
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True)
        tools_path = workspace / "TOOLS.md"
        tools_path.write_text("custom tool notes", encoding="utf-8")

        sync_workspace_templates(workspace, silent=True)

        assert tools_path.read_text(encoding="utf-8") == "custom tool notes"

    def test_creates_memory_directory(self, tmp_path):
        """Should create memory directory structure."""
        workspace = tmp_path / "workspace"

        sync_workspace_templates(workspace, silent=True)

        assert (workspace / "memory").exists() or (workspace / "skills").exists()

    def test_creates_prompt_readme_without_dream_override(self, tmp_path):
        workspace = tmp_path / "workspace"

        added = sync_workspace_templates(workspace, silent=True)

        assert "prompts/README.md" in {path.replace("\\", "/") for path in added}
        assert (workspace / "prompts" / "README.md").exists()
        assert not (workspace / "prompts" / "dream.md").exists()

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

    def test_back_commits_section_draft(self, monkeypatch):
        model = _SimpleDraftModel()
        self._patch_prompt_helpers(monkeypatch, ["first", "back"])

        result = _configure_pydantic_model(model, "Simple")

        assert result is not None
        updated = cast(_SimpleDraftModel, result)
        assert updated.api_key == "secret"
        assert model.api_key == ""

    def test_cancel_keeps_original_model_unchanged(self, monkeypatch):
        model = _SimpleDraftModel()
        self._patch_prompt_helpers(monkeypatch, ["first", None])

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

    def test_nested_section_back_commits_nested_edits(self, monkeypatch):
        model = _OuterDraftModel()
        self._patch_prompt_helpers(monkeypatch, ["first", "first", "back", "done"])

        result = _configure_pydantic_model(model, "Outer")

        assert result is not None
        updated = cast(_OuterDraftModel, result)
        assert updated.nested.api_key == "secret"
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
                "[A] Advanced Settings",
                "[A] Agent Settings",
                KeyboardInterrupt(),
                "[X] Exit Without Saving",
            ]
        )

        def fake_select_with_back(*_args, **_kwargs):
            response = next(responses)
            if isinstance(response, BaseException):
                raise response
            return response

        def fake_configure_general_settings(config, section):
            if section == "Agent Settings":
                config.agents.defaults.model = "test/provider-model"

        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select_with_back)
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
        from nanobot.cli.onboard import _validate_field_constraint
        from nanobot.config.schema import ChannelsConfig

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
        """Field with ge+le should show a min-max suffix."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            retries: int = Field(default=3, ge=0, le=10)

        field_info = M.model_fields["retries"]
        hint = _get_constraint_hint(field_info)
        assert "0" in hint
        assert "10" in hint
        assert "(" not in hint
        assert ")" not in hint

    def test_ge_only(self):
        """Field with only ge should show a >= suffix."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            count: int = Field(default=1, ge=0)

        field_info = M.model_fields["count"]
        hint = _get_constraint_hint(field_info)
        assert "0" in hint
        assert ">=" in hint
        assert "(" not in hint
        assert ")" not in hint

    def test_le_only(self):
        """Field with only le should show a <= suffix."""
        from pydantic import BaseModel, Field

        class M(BaseModel):
            ratio: float = Field(default=1.0, le=100.0)

        field_info = M.model_fields["ratio"]
        hint = _get_constraint_hint(field_info)
        assert "100" in hint
        assert "<=" in hint
        assert "(" not in hint
        assert ")" not in hint

    def test_real_send_max_retries_hint(self):
        """Actual ChannelsConfig.send_max_retries should show a 0-10 suffix."""
        from nanobot.config.schema import ChannelsConfig

        field_info = ChannelsConfig.model_fields["send_max_retries"]
        hint = _get_constraint_hint(field_info)
        assert "0" in hint
        assert "10" in hint
        assert "(" not in hint
        assert ")" not in hint


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

        new_api = ApiConfig(host="0.0.0.0", port=9999, api_key="secret")
        _SETTINGS_SETTER["API Server"](config, new_api)
        assert config.api.host == "0.0.0.0"
        assert config.api.port == 9999
        assert config.api.api_key == "secret"


class TestMainMenuUpdate:
    """Tests for main menu including new Channel Common and API Server items."""

    def test_choice_viewport_keeps_long_menus_within_terminal_height(self):
        """Long provider menus should render as a bounded scrolling slice."""
        assert onboard_wizard._choice_viewport(selected_index=0, total=20, visible_count=5) == (0, 5)
        assert onboard_wizard._choice_viewport(selected_index=10, total=20, visible_count=5) == (
            8,
            13,
        )
        assert onboard_wizard._choice_viewport(selected_index=19, total=20, visible_count=5) == (
            15,
            20,
        )

    def test_choice_viewport_handles_tiny_terminals(self):
        """A one-row menu is still usable instead of failing as window-too-small."""
        assert onboard_wizard._choice_viewport(selected_index=3, total=5, visible_count=0) == (3, 4)

    def test_main_menu_hides_save_actions_until_needed(self):
        """The first screen should not show save or summary actions before edits."""
        from nanobot.cli.onboard import _get_main_menu_choices

        clean_choices = _get_main_menu_choices(False)
        dirty_choices = _get_main_menu_choices(True)

        assert clean_choices == [
            "[Q] Quick Start",
            "[A] Advanced Settings",
            "[X] Exit",
        ]
        assert "[S] Save and Exit" not in clean_choices
        assert "[V] View Configuration Summary" not in clean_choices
        assert "[S] Save and Exit" in dirty_choices
        assert "[X] Exit Without Saving" in dirty_choices

    def test_run_onboard_quick_start_edit(self, monkeypatch):
        """run_onboard should route [Q] to Quick Start."""
        initial_config = Config()

        responses = iter([
            "[Q] Quick Start",
        ])

        def fake_select_with_back(*_args, **_kwargs):
            return next(responses)

        def fake_quick_start(config):
            config.agents.defaults.bot_name = "quickbot"
            return True

        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select_with_back)
        monkeypatch.setattr(onboard_wizard, "_configure_quick_start", fake_quick_start)

        result = run_onboard(initial_config=initial_config)

        assert result.should_save is True
        assert result.config.agents.defaults.bot_name == "quickbot"

    def test_main_menu_default_resets_after_returning_from_advanced(self, monkeypatch):
        """Returning from Advanced should not leave its item visually selected."""
        initial_config = Config()
        responses = iter([
            "[A] Advanced Settings",
            "<- Back",
            "[X] Exit",
        ])
        main_defaults: list[str | None] = []

        def fake_select_with_back(prompt, _choices, default=None):
            if prompt == "What would you like to do?":
                main_defaults.append(default)
            return next(responses)

        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard, "_show_section_header", lambda *a, **kw: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select_with_back)

        result = run_onboard(initial_config=initial_config)

        assert result.should_save is False
        assert main_defaults == [None, None]

    def test_ask_prompt_shortens_escape_timeout(self):
        """Questionary text prompts should not wait the default timeout on Escape."""

        class FakePrompt:
            def __init__(self):
                self.application = SimpleNamespace(ttimeoutlen=0.5, timeoutlen=1.0)

            def ask(self):
                return "ok"

        prompt = FakePrompt()

        assert onboard_wizard._ask_prompt(prompt) == "ok"
        assert prompt.application.ttimeoutlen == onboard_wizard._PROMPT_ESCAPE_TIMEOUT_SECONDS
        assert prompt.application.timeoutlen == onboard_wizard._PROMPT_ESCAPE_TIMEOUT_SECONDS

    def test_quick_start_provider_choices_include_all_chat_providers(self):
        """Quick Start should be driven by the provider registry, not a short allowlist."""
        from nanobot.providers.registry import PROVIDERS

        choices = onboard_wizard._get_quick_start_provider_choices()
        selected_provider_names = set(choices.values())
        expected_provider_names = set()
        seen_display_names: set[str] = set()
        for spec in PROVIDERS:
            if spec.name == "custom" or spec.is_oauth or spec.is_transcription_only:
                continue
            if spec.display_name in seen_display_names:
                continue
            seen_display_names.add(spec.display_name)
            expected_provider_names.add(spec.name)
        expected_provider_names.add("custom")

        assert selected_provider_names == expected_provider_names
        assert "assemblyai" not in selected_provider_names
        assert choices["OpenCode Zen"] == "opencode"
        assert choices[onboard_wizard._QUICK_START_CUSTOM_PROVIDER_CHOICE] == "custom"

    def test_quick_start_provider_choice_skips_advanced_prompts(self, monkeypatch):
        """The beginner path should ask for provider credentials and model."""
        config = Config()

        def fail_websocket_config(*_args, **_kwargs):
            raise AssertionError("Quick Start should not open WebSocket settings")

        pause_messages: list[str] = []

        class FakePrompt:
            def __init__(self, response):
                self.response = response

            def ask(self):
                return self.response

        monkeypatch.setattr(onboard_wizard.console, "clear", lambda: None)
        monkeypatch.setattr(onboard_wizard, "_show_section_header", lambda *a, **kw: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: "DeepSeek")
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: "sk-ds-test")
        monkeypatch.setattr(
            onboard_wizard,
            "_input_model_with_autocomplete",
            lambda *a, **kw: "deepseek-v4-flash",
        )
        monkeypatch.setattr(
            onboard_wizard,
            "questionary",
            SimpleNamespace(
                confirm=lambda *a, **kw: FakePrompt(True),
                password=lambda *a, **kw: FakePrompt("webui-secret"),
            ),
        )
        monkeypatch.setattr(onboard_wizard, "_configure_pydantic_model", fail_websocket_config)
        monkeypatch.setattr(onboard_wizard, "_print_summary_panel", lambda *a, **kw: None)
        monkeypatch.setattr(onboard_wizard, "_pause", lambda message="": pause_messages.append(message))

        assert onboard_wizard._configure_quick_start(config) is True

        assert pause_messages == ["Press Enter to save and exit..."]
        assert config.providers.deepseek.api_key == "sk-ds-test"
        assert config.providers.deepseek.api_base == "https://api.deepseek.com"
        assert config.agents.defaults.model_preset == "primary"
        assert config.model_presets["primary"].provider == "deepseek"
        assert config.model_presets["primary"].model == "deepseek-v4-flash"
        websocket = getattr(config.channels, "websocket")
        assert websocket["enabled"] is True
        assert websocket["websocketRequiresToken"] is True
        assert websocket["tokenIssueSecret"] == "webui-secret"

    def test_quick_start_provider_menu_escape_returns_back(self, monkeypatch):
        """Esc from the first Quick Start menu should return to the main menu."""
        config = Config()

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(
            onboard_wizard,
            "_select_with_back",
            lambda *a, **kw: onboard_wizard._BACK_PRESSED,
        )

        assert onboard_wizard._configure_quick_start_provider(config) is onboard_wizard._BACK_PRESSED
        assert "primary" not in config.model_presets

    def test_quick_start_provider_back_skips_pause(self, monkeypatch):
        """Returning from Quick Start should not require an extra Enter key press."""
        config = Config()
        pause_messages: list[str] = []

        def fail_websocket_defaults(*_args, **_kwargs):
            raise AssertionError("Back navigation should not continue Quick Start")

        monkeypatch.setattr(onboard_wizard.console, "clear", lambda: None)
        monkeypatch.setattr(onboard_wizard, "_show_section_header", lambda *a, **kw: None)
        monkeypatch.setattr(
            onboard_wizard,
            "_configure_quick_start_provider",
            lambda *_args: onboard_wizard._BACK_PRESSED,
        )
        monkeypatch.setattr(
            onboard_wizard,
            "_enable_quick_start_websocket_defaults",
            fail_websocket_defaults,
        )
        monkeypatch.setattr(onboard_wizard, "_pause", lambda message="": pause_messages.append(message))

        assert onboard_wizard._configure_quick_start(config) is False
        assert pause_messages == []

    def test_quick_start_websocket_decline_rolls_back_provider_defaults(self, monkeypatch):
        """A failed WebSocket step should not leave saveable Quick Start defaults behind."""
        config = Config()
        original = config.model_dump(by_alias=True)

        class FakePrompt:
            def __init__(self, response):
                self.response = response

            def ask(self):
                return self.response

        monkeypatch.setattr(onboard_wizard.console, "clear", lambda: None)
        monkeypatch.setattr(onboard_wizard.console, "print", lambda *a, **kw: None)
        monkeypatch.setattr(onboard_wizard, "_show_section_header", lambda *a, **kw: None)
        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *a, **kw: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: "DeepSeek")
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: "sk-ds-test")
        monkeypatch.setattr(
            onboard_wizard,
            "_input_model_with_autocomplete",
            lambda *a, **kw: "deepseek-v4-flash",
        )
        monkeypatch.setattr(
            onboard_wizard,
            "questionary",
            SimpleNamespace(confirm=lambda *a, **kw: FakePrompt(False)),
        )
        monkeypatch.setattr(onboard_wizard, "_pause", lambda message="": None)

        assert onboard_wizard._configure_quick_start(config) is False

        assert config.model_dump(by_alias=True) == original
        assert getattr(config.channels, "websocket", None) is None

    def test_quick_start_provider_choice_asks_for_model_id(self, monkeypatch):
        """Known providers should ask users for the model instead of fetching one."""
        config = Config()
        model_prompts: list[tuple[str, str, str]] = []

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: "OpenRouter")
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: "sk-or-test")

        def fake_model_input(prompt, current, provider):
            model_prompts.append((prompt, current, provider))
            return "openai/gpt-4o-mini"

        monkeypatch.setattr(onboard_wizard, "_input_model_with_autocomplete", fake_model_input)

        assert onboard_wizard._configure_quick_start_provider(config) is True

        assert model_prompts == [("Model ID", "", "openrouter")]
        assert config.providers.openrouter.api_key == "sk-or-test"
        assert config.providers.openrouter.api_base == "https://openrouter.ai/api/v1"
        assert config.model_presets["primary"].provider == "openrouter"
        assert config.model_presets["primary"].model == "openai/gpt-4o-mini"

    def test_quick_start_local_provider_skips_api_key(self, monkeypatch):
        """Local providers should only need a model when they have a default base URL."""
        config = Config()

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: "Ollama")

        def fail_text_input(*_args, **_kwargs):
            raise AssertionError("Ollama Quick Start should not require an API key")

        monkeypatch.setattr(onboard_wizard, "_input_text", fail_text_input)
        monkeypatch.setattr(
            onboard_wizard,
            "_input_model_with_autocomplete",
            lambda *a, **kw: "llama3.2",
        )

        assert onboard_wizard._configure_quick_start_provider(config) is True

        assert config.providers.ollama.api_key is None
        assert config.providers.ollama.api_base == "http://localhost:11434/v1"
        assert config.model_presets["primary"].provider == "ollama"
        assert config.model_presets["primary"].model == "llama3.2"

    def test_quick_start_openai_stores_key_and_model_without_base(self, monkeypatch):
        """OpenAI should support key-only setup without storing a default base URL."""
        config = Config()

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: "OpenAI")
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: "sk-openai-test")
        monkeypatch.setattr(
            onboard_wizard,
            "_input_model_with_autocomplete",
            lambda *a, **kw: "gpt-4o-mini",
        )

        assert onboard_wizard._configure_quick_start_provider(config) is True

        assert config.providers.openai.api_key == "sk-openai-test"
        assert config.providers.openai.api_base is None
        assert config.model_presets["primary"].provider == "openai"
        assert config.model_presets["primary"].model == "gpt-4o-mini"

    def test_quick_start_api_key_escape_returns_to_provider_choice(self, monkeypatch):
        """Esc from an API-key prompt should go back to provider selection."""
        config = Config()
        provider_answers = iter(["DeepSeek", "OpenAI"])
        api_key_answers = iter([onboard_wizard._BACK_PRESSED, "sk-openai-test"])
        selected_providers: list[str] = []

        def fake_select(*_args, **_kwargs):
            selected = next(provider_answers)
            selected_providers.append(selected)
            return selected

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select)
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: next(api_key_answers))
        monkeypatch.setattr(
            onboard_wizard,
            "_input_model_with_autocomplete",
            lambda *a, **kw: "gpt-4o-mini",
        )

        assert onboard_wizard._configure_quick_start_provider(config) is True

        assert selected_providers == ["DeepSeek", "OpenAI"]
        assert config.providers.deepseek.api_key is None
        assert config.providers.openai.api_key == "sk-openai-test"
        assert config.model_presets["primary"].provider == "openai"

    def test_quick_start_zhipu_coding_plan_uses_coding_base_url(self, monkeypatch):
        """Zhipu Coding Plan should not use the standard Zhipu base URL."""
        config = Config()
        choices = iter(["Zhipu AI", "Coding Plan"])

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: next(choices))
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: "zhipu-key")
        monkeypatch.setattr(
            onboard_wizard,
            "_input_model_with_autocomplete",
            lambda *a, **kw: "glm-4.6",
        )

        assert onboard_wizard._configure_quick_start_provider(config) is True

        assert config.providers.zhipu.api_key == "zhipu-key"
        assert config.providers.zhipu.api_base == "https://open.bigmodel.cn/api/coding/paas/v4"
        assert config.model_presets["primary"].provider == "zhipu"
        assert config.model_presets["primary"].model == "glm-4.6"

    def test_quick_start_minimax_mainland_token_plan_uses_mainland_base_url(self, monkeypatch):
        """MiniMax mainland token plan should not use the global MiniMax base URL."""
        config = Config()
        choices = iter(["MiniMax", "Mainland China Token Plan"])

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: next(choices))
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: "minimax-key")
        monkeypatch.setattr(
            onboard_wizard,
            "_input_model_with_autocomplete",
            lambda *a, **kw: "MiniMax-M2",
        )

        assert onboard_wizard._configure_quick_start_provider(config) is True

        assert config.providers.minimax.api_key == "minimax-key"
        assert config.providers.minimax.api_base == "https://api.minimaxi.com/v1"
        assert config.model_presets["primary"].provider == "minimax"
        assert config.model_presets["primary"].model == "MiniMax-M2"

    def test_quick_start_stepfun_step_plan_uses_plan_base_url(self, monkeypatch):
        """StepFun Step Plan should not use the standard StepFun base URL."""
        config = Config()
        choices = iter(["Step Fun", "Step Plan"])

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: next(choices))
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: "stepfun-key")
        monkeypatch.setattr(
            onboard_wizard,
            "_input_model_with_autocomplete",
            lambda *a, **kw: "step-3.5-flash",
        )

        assert onboard_wizard._configure_quick_start_provider(config) is True

        assert config.providers.stepfun.api_key == "stepfun-key"
        assert config.providers.stepfun.api_base == "https://api.stepfun.ai/step_plan/v1"
        assert config.model_presets["primary"].provider == "stepfun"
        assert config.model_presets["primary"].model == "step-3.5-flash"

    def test_quick_start_xiaomi_mimo_token_plan_uses_token_plan_base_url(self, monkeypatch):
        """Xiaomi MiMo Token Plan should not use the standard MiMo base URL."""
        config = Config()
        choices = iter(["Xiaomi MIMO", "Token Plan"])

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: next(choices))
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: "mimo-key")
        monkeypatch.setattr(
            onboard_wizard,
            "_input_model_with_autocomplete",
            lambda *a, **kw: "mimo-v2.5-pro",
        )

        assert onboard_wizard._configure_quick_start_provider(config) is True

        assert config.providers.xiaomi_mimo.api_key == "mimo-key"
        assert config.providers.xiaomi_mimo.api_base == "https://token-plan-sgp.xiaomimimo.com/v1"
        assert config.model_presets["primary"].provider == "xiaomi_mimo"
        assert config.model_presets["primary"].model == "mimo-v2.5-pro"

    def test_quick_start_custom_base_url_asks_for_model_id(self, monkeypatch):
        """Custom providers should ask for base URL and model ID."""
        config = Config()
        text_answers = iter(["sk-custom-test", "https://api.example.test/v1"])

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(
            onboard_wizard,
            "_select_with_back",
            lambda *a, **kw: onboard_wizard._QUICK_START_CUSTOM_PROVIDER_CHOICE,
        )
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: next(text_answers))
        monkeypatch.setattr(
            onboard_wizard,
            "_input_model_with_autocomplete",
            lambda *a, **kw: "custom-model",
        )

        assert onboard_wizard._configure_quick_start_provider(config) is True

        assert config.providers.custom.api_key == "sk-custom-test"
        assert config.providers.custom.api_base == "https://api.example.test/v1"
        assert config.model_presets["primary"].provider == "custom"
        assert config.model_presets["primary"].model == "custom-model"

    def test_quick_start_provider_without_default_base_url_prompts_for_base(self, monkeypatch):
        """Providers that require an endpoint should ask for a base URL in Quick Start."""
        config = Config()
        text_answers = iter(["azure-key", "https://azure.example.test/openai"])

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: "Azure OpenAI")
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: next(text_answers))
        monkeypatch.setattr(
            onboard_wizard,
            "_input_model_with_autocomplete",
            lambda *a, **kw: "deployment-name",
        )

        assert onboard_wizard._configure_quick_start_provider(config) is True

        assert config.providers.azure_openai.api_key == "azure-key"
        assert config.providers.azure_openai.api_base == "https://azure.example.test/openai"
        assert config.model_presets["primary"].provider == "azure_openai"
        assert config.model_presets["primary"].model == "deployment-name"

    def test_quick_start_websocket_step_explains_channel_enablement(self, monkeypatch):
        """Quick Start should confirm and protect WebSocket for WebUI."""
        config = Config()
        messages: list[str] = []

        class FakePrompt:
            def __init__(self, response):
                self.response = response

            def ask(self):
                return self.response

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard.console, "print", lambda message="", *a, **kw: messages.append(str(message)))
        monkeypatch.setattr(
            onboard_wizard,
            "questionary",
            SimpleNamespace(
                confirm=lambda *a, **kw: FakePrompt(True),
                password=lambda *a, **kw: FakePrompt("webui-secret"),
            ),
        )

        assert onboard_wizard._enable_quick_start_websocket_defaults(config) is True

        assert any("WebSocket channel" in message for message in messages)
        assert any("http://127.0.0.1:8765" in message for message in messages)
        websocket = getattr(config.channels, "websocket")
        assert websocket["enabled"] is True
        assert websocket["websocketRequiresToken"] is True
        assert websocket["tokenIssueSecret"] == "webui-secret"

    def test_quick_start_websocket_step_can_be_declined(self, monkeypatch):
        """Declining WebSocket should stop Quick Start before changing channel config."""
        config = Config()

        class FakePrompt:
            def __init__(self, response):
                self.response = response

            def ask(self):
                return self.response

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard.console, "print", lambda *a, **kw: None)
        monkeypatch.setattr(
            onboard_wizard,
            "questionary",
            SimpleNamespace(confirm=lambda *a, **kw: FakePrompt(False)),
        )

        assert onboard_wizard._enable_quick_start_websocket_defaults(config) is False
        assert getattr(config.channels, "websocket", None) is None

    def test_quick_start_websocket_requires_password(self, monkeypatch):
        """Accepting WebSocket with an empty password should not enable the channel."""
        config = Config()

        class FakePrompt:
            def __init__(self, response):
                self.response = response

            def ask(self):
                return self.response

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard.console, "print", lambda *a, **kw: None)
        monkeypatch.setattr(
            onboard_wizard,
            "questionary",
            SimpleNamespace(
                confirm=lambda *a, **kw: FakePrompt(True),
                password=lambda *a, **kw: FakePrompt(""),
            ),
        )

        assert onboard_wizard._enable_quick_start_websocket_defaults(config) is False
        assert getattr(config.channels, "websocket", None) is None

    def test_quick_start_requires_api_key_before_setting_defaults(self, monkeypatch):
        """Quick Start should not create a ready-looking config without an API key."""
        config = Config()

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: "DeepSeek")
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: "")

        assert onboard_wizard._configure_quick_start_provider(config) is False

        assert config.providers.deepseek.api_key is None
        assert config.providers.deepseek.api_base is None
        assert config.providers.custom.api_key is None
        assert config.providers.custom.api_base is None
        assert "primary" not in config.model_presets

    def test_quick_start_requires_model_id_before_setting_defaults(self, monkeypatch):
        """Quick Start should not create a preset without an explicit model ID."""
        config = Config()

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: "DeepSeek")
        monkeypatch.setattr(onboard_wizard, "_input_text", lambda *a, **kw: "sk-ds-test")
        monkeypatch.setattr(onboard_wizard, "_input_model_with_autocomplete", lambda *a, **kw: "")

        assert onboard_wizard._configure_quick_start_provider(config) is False

        assert config.providers.deepseek.api_key is None
        assert config.providers.deepseek.api_base is None
        assert "primary" not in config.model_presets

    def test_quick_start_summary_calls_out_missing_api_key(self, monkeypatch):
        """Quick Start summary should not tell users to run gateway before adding a key."""
        config = Config()
        config.model_presets["primary"] = ModelPresetConfig(
            model="deepseek-v4-flash",
            provider="deepseek",
        )

        captured: dict[str, list[tuple[str, str]]] = {}

        monkeypatch.setattr(onboard_wizard, "_show_quick_start_progress", lambda *_args: None)
        monkeypatch.setattr(
            onboard_wizard,
            "_print_summary_panel",
            lambda rows, _title: captured.setdefault("rows", rows),
        )

        onboard_wizard._show_quick_start_summary(config)

        labels = [label for label, _value in captured["rows"]]
        rows = dict(captured["rows"])
        assert rows["Status"] == "DeepSeek API key missing"
        assert "API key" in rows["Next"]
        assert "nanobot gateway" in rows["Next"]
        assert "agent -m" not in rows["Next"]
        assert labels.index("Next") < labels.index("Open")
        assert "Model" not in rows
        assert "Entry point" not in rows
        assert "API key" not in rows
        assert "Defaults" not in rows

    def test_configure_login_channel_defaults_to_login(self, monkeypatch):
        """The channel wizard should start login before exposing advanced fields."""
        from nanobot.channels.base import BaseChannel

        config = Config()
        calls: dict[str, Any] = {}

        class LoginConfig(BaseModel):
            enabled: bool = False

        class LoginChannel(BaseChannel):
            name = "loginchat"
            display_name = "Login Chat"

            async def login(self, force: bool = False) -> bool:
                calls["force"] = force
                return True

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def send(self, msg) -> None:
                pass

        def fail_configure(*_args, **_kwargs):
            raise AssertionError("Default action should run login, not open advanced fields")

        monkeypatch.setattr(onboard_wizard, "_get_channel_names", lambda: {"loginchat": "Login Chat"})
        monkeypatch.setattr(
            onboard_wizard,
            "_get_channel_config_class",
            lambda channel: LoginConfig if channel == "loginchat" else None,
        )
        monkeypatch.setattr(
            onboard_wizard,
            "_get_channel_class",
            lambda channel: LoginChannel if channel == "loginchat" else None,
        )
        monkeypatch.setattr(
            onboard_wizard,
            "_select_with_back",
            lambda *_args, **_kwargs: onboard_wizard._CHANNEL_LOGIN_CHOICE,
        )
        monkeypatch.setattr(onboard_wizard, "_configure_pydantic_model", fail_configure)

        onboard_wizard._configure_channel(config, "loginchat")

        loginchat = getattr(config.channels, "loginchat")
        assert loginchat["enabled"] is True
        assert calls == {"force": False}

    def test_main_menu_dispatch_includes_channel_common(self):
        """Advanced menu dispatch should route [H] to Channel Common."""

        # We verify by checking the dispatch table is set up correctly
        # The menu items are defined inline in run_onboard, so we test
        # that _configure_general_settings handles the new sections.
        from nanobot.cli.onboard import _SETTINGS_GETTER, _SETTINGS_SECTIONS, _SETTINGS_SETTER

        assert "Channel Common" in _SETTINGS_SECTIONS
        assert "Channel Common" in _SETTINGS_GETTER
        assert "Channel Common" in _SETTINGS_SETTER

    def test_main_menu_dispatch_includes_api_server(self):
        """Advanced menu dispatch should route [I] to API Server."""
        from nanobot.cli.onboard import _SETTINGS_GETTER, _SETTINGS_SECTIONS, _SETTINGS_SETTER

        assert "API Server" in _SETTINGS_SECTIONS
        assert "API Server" in _SETTINGS_GETTER
        assert "API Server" in _SETTINGS_SETTER

    def test_run_onboard_channel_common_edit(self, monkeypatch):
        """run_onboard should handle [H] Channel Common through Advanced Settings."""
        initial_config = Config()

        responses = iter([
            "[A] Advanced Settings",
            "[H] Channel Common",
            KeyboardInterrupt(),
            "[S] Save and Exit",
        ])

        def fake_select_with_back(*_args, **_kwargs):
            response = next(responses)
            if isinstance(response, BaseException):
                raise response
            return response

        def fake_configure_general_settings(config, section):
            if section == "Channel Common":
                config.channels.send_tool_hints = True

        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select_with_back)
        monkeypatch.setattr(onboard_wizard, "_configure_general_settings", fake_configure_general_settings)

        result = run_onboard(initial_config=initial_config)

        assert result.should_save is True
        assert result.config.channels.send_tool_hints is True

    def test_run_onboard_api_server_edit(self, monkeypatch):
        """run_onboard should handle [I] API Server through Advanced Settings."""
        initial_config = Config()

        responses = iter([
            "[A] Advanced Settings",
            "[I] API Server",
            KeyboardInterrupt(),
            "[S] Save and Exit",
        ])

        def fake_select_with_back(*_args, **_kwargs):
            response = next(responses)
            if isinstance(response, BaseException):
                raise response
            return response

        def fake_configure_general_settings(config, section):
            if section == "API Server":
                config.api.port = 9999

        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select_with_back)
        monkeypatch.setattr(onboard_wizard, "_configure_general_settings", fake_configure_general_settings)

        result = run_onboard(initial_config=initial_config)

        assert result.should_save is True
        assert result.config.api.port == 9999

    def test_view_summary_calls_pause(self, monkeypatch):
        """Advanced [V] View Summary should pause before returning to the menu."""
        initial_config = Config()
        pause_called = {"n": 0}

        responses = iter([
            "[A] Advanced Settings",
            "[V] View Configuration Summary",
            KeyboardInterrupt(),
            "[X] Exit",
        ])

        def fake_select_with_back(*_args, **_kwargs):
            response = next(responses)
            if isinstance(response, BaseException):
                raise response
            return response

        def fake_pause():
            pause_called["n"] += 1

        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select_with_back)
        # _pause is called inside _show_summary, so we patch it there
        monkeypatch.setattr(onboard_wizard, "_pause", fake_pause)
        # Suppress summary output but still call _pause
        monkeypatch.setattr(onboard_wizard, "_print_summary_panel", lambda *a, **kw: None)
        monkeypatch.setattr(onboard_wizard, "_get_provider_names", lambda: {})
        monkeypatch.setattr(onboard_wizard, "_get_channel_names", lambda: {})

        result = run_onboard(initial_config=initial_config)

        assert result.should_save is False
        assert pause_called["n"] == 1


class TestInputTextEmptyString:
    """Tests for _input_text empty-string handling bug fix."""

    def test_empty_string_returned_not_none(self, monkeypatch):
        """_input_text should return empty string, not None, when user enters ''."""
        monkeypatch.setattr(
            onboard_wizard,
            "_get_questionary",
            lambda: SimpleNamespace(text=lambda *a, **kw: SimpleNamespace(ask=lambda: "")),
        )

        result = _input_text("Name", "old", "str")
        assert result == ""

    def test_none_still_returns_none(self, monkeypatch):
        """_input_text should return None when questionary returns None."""
        monkeypatch.setattr(
            onboard_wizard,
            "_get_questionary",
            lambda: SimpleNamespace(text=lambda *a, **kw: SimpleNamespace(ask=lambda: None)),
        )

        result = _input_text("Name", "old", "str")
        assert result is None

    def test_escape_returns_back_pressed(self, monkeypatch):
        """_input_text should preserve the local back sentinel."""
        monkeypatch.setattr(
            onboard_wizard,
            "_get_questionary",
            lambda: SimpleNamespace(
                text=lambda *a, **kw: SimpleNamespace(ask=lambda: onboard_wizard._BACK_PRESSED)
            ),
        )

        result = _input_text("Name", "old", "str")
        assert result is onboard_wizard._BACK_PRESSED


class TestIsStrOrNone:
    """Tests for _is_str_or_none helper."""

    def test_str_or_none_true(self):
        from nanobot.cli.onboard import _is_str_or_none

        assert _is_str_or_none(str | None) is True

    def test_optional_str_true(self):
        from typing import Optional

        from nanobot.cli.onboard import _is_str_or_none

        assert _is_str_or_none(Optional[str]) is True

    def test_str_only_false(self):
        from nanobot.cli.onboard import _is_str_or_none

        assert _is_str_or_none(str) is False

    def test_int_or_none_false(self):
        from nanobot.cli.onboard import _is_str_or_none

        assert _is_str_or_none(int | None) is False


class TestConfigurePydanticModelEmptyString:
    """Tests that optional string fields are cleared when empty string is entered."""

    def test_optional_str_empty_string_becomes_none(self, monkeypatch):
        """Entering '' for an optional str field should set it to None."""
        from pydantic import BaseModel


        class M(BaseModel):
            api_key: str | None = None

        model = M(api_key="secret")

        call_count = {"select": 0}

        def fake_select(_prompt, choices, default=None):
            call_count["select"] += 1
            # First call: select the api_key field, then Done
            if call_count["select"] == 1:
                for c in choices:
                    if "Api Key" in c:
                        return c
                return choices[0]
            return "[Done]"

        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select)
        monkeypatch.setattr(onboard_wizard, "_show_config_panel", lambda *a, **kw: None)
        # Simulate user entering empty string
        monkeypatch.setattr(
            onboard_wizard, "_input_with_existing", lambda *a, **kw: ""
        )

        result = _configure_pydantic_model(model, "Test")
        assert result is not None
        assert result.api_key is None

    def test_required_str_empty_string_kept(self, monkeypatch):
        """Entering '' for a required str field should keep the empty string."""
        from pydantic import BaseModel

        class M(BaseModel):
            api_key: str = ""

        model = M(api_key="secret")

        call_count = {"select": 0}

        def fake_select(_prompt, choices, default=None):
            call_count["select"] += 1
            if call_count["select"] == 1:
                for c in choices:
                    if "Api Key" in c:
                        return c
                return choices[0]
            return "[Done]"

        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select)
        monkeypatch.setattr(onboard_wizard, "_show_config_panel", lambda *a, **kw: None)
        monkeypatch.setattr(
            onboard_wizard, "_input_with_existing", lambda *a, **kw: ""
        )

        result = _configure_pydantic_model(model, "Test")
        assert result is not None
        assert result.api_key == ""


class TestModelPresetWizard:
    """Tests for model preset CRUD in the onboard wizard."""

    def test_sync_preset_cache(self):
        """_sync_preset_cache should populate the module-level cache."""
        from nanobot.cli.onboard import _MODEL_PRESET_CACHE, _sync_preset_cache
        from nanobot.config.schema import ModelPresetConfig

        config = Config()
        config.model_presets["fast"] = ModelPresetConfig(model="gpt-4.1-mini")
        config.model_presets["power"] = ModelPresetConfig(model="gpt-4.1")
        _sync_preset_cache(config)
        assert _MODEL_PRESET_CACHE == {"fast", "power"}
        _MODEL_PRESET_CACHE.clear()

    def test_model_preset_add(self, monkeypatch):
        """_configure_model_presets should add a new preset."""
        from nanobot.cli.onboard import _MODEL_PRESET_CACHE, _configure_model_presets
        from nanobot.config.schema import ModelPresetConfig

        config = Config()
        _MODEL_PRESET_CACHE.clear()

        responses = iter([
            "[+] Add new preset",
            "my-preset",
            "<- Back",
        ])

        class FakePrompt:
            def __init__(self, response):
                self.response = response

            def ask(self):
                return self.response

        def fake_text(*_args, **_kwargs):
            return FakePrompt(next(responses))

        def fake_configure(*_model, **_kwargs):
            return ModelPresetConfig(model="gpt-test", temperature=0.5)

        def fake_select_with_back(*_args, **_kwargs):
            return next(responses)

        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select_with_back)
        monkeypatch.setattr(onboard_wizard, "questionary", SimpleNamespace(text=fake_text))
        monkeypatch.setattr(onboard_wizard, "_configure_pydantic_model", fake_configure)
        monkeypatch.setattr(onboard_wizard, "_show_section_header", lambda *a, **kw: None)
        monkeypatch.setattr(onboard_wizard, "console", SimpleNamespace(clear=lambda: None))

        _configure_model_presets(config)

        assert "my-preset" in config.model_presets
        assert config.model_presets["my-preset"].model == "gpt-test"
        assert config.model_presets["my-preset"].temperature == 0.5
        _MODEL_PRESET_CACHE.clear()

    def test_model_preset_delete(self, monkeypatch):
        """_configure_model_presets should delete an existing preset."""
        from nanobot.cli.onboard import _MODEL_PRESET_CACHE, _configure_model_presets
        from nanobot.config.schema import ModelPresetConfig

        config = Config()
        config.model_presets["old - preset"] = ModelPresetConfig(model="x")
        _MODEL_PRESET_CACHE.clear()
        _MODEL_PRESET_CACHE.update({"old - preset", "default"})

        responses = iter([
            "old - preset - x",
            "Delete",
            True,
            "<- Back",
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

        def fake_confirm(*_args, **_kwargs):
            return FakePrompt(next(responses))

        def fake_select_with_back(*_args, **_kwargs):
            return next(responses)

        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select_with_back)
        monkeypatch.setattr(
            onboard_wizard, "questionary", SimpleNamespace(select=fake_select, confirm=fake_confirm)
        )
        monkeypatch.setattr(onboard_wizard, "_show_section_header", lambda *a, **kw: None)
        monkeypatch.setattr(onboard_wizard, "console", SimpleNamespace(clear=lambda: None))

        _configure_model_presets(config)

        assert "old - preset" not in config.model_presets
        assert "old - preset" not in _MODEL_PRESET_CACHE
        _MODEL_PRESET_CACHE.clear()

    def test_model_preset_field_handler(self, monkeypatch):
        """_handle_model_preset_field should set a preset name from choices."""
        from nanobot.cli.onboard import _MODEL_PRESET_CACHE, _handle_model_preset_field
        from nanobot.config.schema import AgentDefaults

        _MODEL_PRESET_CACHE.clear()
        _MODEL_PRESET_CACHE.update({"fast", "power", "default"})

        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: "fast")

        defaults = AgentDefaults()
        _handle_model_preset_field(defaults, "model_preset", "Model Preset", None)
        assert defaults.model_preset == "fast"
        _MODEL_PRESET_CACHE.clear()

    def test_model_preset_field_handler_clear(self, monkeypatch):
        """_handle_model_preset_field should clear preset when Clear value is chosen."""
        from nanobot.cli.onboard import (
            _CLEAR_CHOICE,
            _MODEL_PRESET_CACHE,
            _handle_model_preset_field,
        )
        from nanobot.config.schema import AgentDefaults

        _MODEL_PRESET_CACHE.clear()
        _MODEL_PRESET_CACHE.add("fast")

        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: _CLEAR_CHOICE)

        defaults = AgentDefaults(model_preset="fast")
        _handle_model_preset_field(defaults, "model_preset", "Model Preset", "fast")
        assert defaults.model_preset is None
        _MODEL_PRESET_CACHE.clear()

    def test_main_menu_dispatch_includes_model_presets(self):
        """_configure_model_presets should be importable and callable."""
        from nanobot.cli.onboard import _configure_model_presets

        assert callable(_configure_model_presets)

    def test_run_onboard_model_presets_edit(self, monkeypatch):
        """run_onboard should handle [M] Model Presets through Advanced Settings."""
        from nanobot.config.schema import ModelPresetConfig

        initial_config = Config()

        responses = iter([
            "[A] Advanced Settings",
            "[M] Model Presets",
            KeyboardInterrupt(),
            "[S] Save and Exit",
        ])

        def fake_select_with_back(*_args, **_kwargs):
            response = next(responses)
            if isinstance(response, BaseException):
                raise response
            return response

        preset_mutated = {"n": 0}

        def fake_configure_model_presets(config):
            preset_mutated["n"] += 1
            config.model_presets["test"] = ModelPresetConfig(model="gpt-test")

        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select_with_back)
        monkeypatch.setattr(onboard_wizard, "_configure_model_presets", fake_configure_model_presets)
        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard, "_show_section_header", lambda *a, **kw: None)
        monkeypatch.setattr(onboard_wizard, "console", SimpleNamespace(clear=lambda: None))

        result = run_onboard(initial_config)
        assert result.should_save is True
        assert preset_mutated["n"] == 1
        assert "test" in result.config.model_presets

    def test_fallback_models_field_add(self, monkeypatch):
        """_handle_fallback_models_field should add a preset name."""
        from nanobot.cli.onboard import _MODEL_PRESET_CACHE, _handle_fallback_models_field
        from nanobot.config.schema import AgentDefaults

        _MODEL_PRESET_CACHE.clear()
        _MODEL_PRESET_CACHE.update({"fast", "default"})

        select_responses = iter(["fast"])
        questionary_responses = iter(["[+] Add preset", "[Done]"])

        class FakePrompt:
            def __init__(self, response):
                self.response = response

            def ask(self):
                if isinstance(self.response, BaseException):
                    raise self.response
                return self.response

        def fake_questionary_select(*_args, **_kwargs):
            return FakePrompt(next(questionary_responses))

        def fake_select_with_back(*_args, **_kwargs):
            return next(select_responses)

        monkeypatch.setattr(
            onboard_wizard, "questionary",
            SimpleNamespace(select=fake_questionary_select, press_any_key_to_continue=lambda: FakePrompt(None)),
        )
        monkeypatch.setattr(onboard_wizard, "_select_with_back", fake_select_with_back)
        monkeypatch.setattr(onboard_wizard, "console", SimpleNamespace(clear=lambda: None, print=lambda *a, **kw: None))

        defaults = AgentDefaults()
        _handle_fallback_models_field(defaults, "fallback_models", "Fallback Models", [])
        assert defaults.fallback_models == ["fast"]
        _MODEL_PRESET_CACHE.clear()

    def test_provider_field_handler(self, monkeypatch):
        """_handle_provider_field should set provider from choices."""
        from nanobot.cli.onboard import _handle_provider_field
        from nanobot.config.schema import AgentDefaults

        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: "anthropic")

        defaults = AgentDefaults()
        _handle_provider_field(defaults, "provider", "Provider", "auto")
        assert defaults.provider == "anthropic"

    def test_search_provider_field_handler(self, monkeypatch):
        """_handle_search_provider_field should set the search engine from choices."""
        from nanobot.agent.tools.web import WebSearchConfig
        from nanobot.cli.onboard import _handle_search_provider_field

        monkeypatch.setattr(onboard_wizard, "_select_with_back", lambda *a, **kw: "keenable")

        cfg = WebSearchConfig()
        _handle_search_provider_field(cfg, "provider", "Provider", "duckduckgo")
        assert cfg.provider == "keenable"

    def test_provider_field_dispatch_is_model_type_aware(self):
        """WebSearchConfig.provider must not be hijacked by the LLM provider handler."""
        from nanobot.agent.tools.web import WebSearchConfig
        from nanobot.cli.onboard import (
            _handle_provider_field,
            _handle_search_provider_field,
            _resolve_field_handler,
        )
        from nanobot.config.schema import AgentDefaults

        assert _resolve_field_handler(WebSearchConfig(), "provider") is _handle_search_provider_field
        assert _resolve_field_handler(AgentDefaults(), "provider") is _handle_provider_field
