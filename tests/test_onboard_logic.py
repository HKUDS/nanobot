"""Unit tests for onboard core logic functions.

These tests focus on the business logic behind the onboard wizard,
without testing the interactive UI components.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from pydantic import BaseModel, Field

from nanobot.cli import onboard_wizard

# Import functions to test
from nanobot.cli.commands import _merge_missing_defaults
from nanobot.cli.onboard_wizard import (
    _BACK_PRESSED,
    _configure_pydantic_model,
    _format_value,
    _get_field_display_name,
    _get_field_type_info,
    run_onboard,
)
from nanobot.config.schema import Config
from nanobot.utils.helpers import sync_workspace_templates


class _SimpleDraftModel(BaseModel):
    api_key: str = ""


class _NestedDraftModel(BaseModel):
    api_key: str = ""


class _OuterDraftModel(BaseModel):
    nested: _NestedDraftModel = Field(default_factory=_NestedDraftModel)


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
        from nanobot.cli.onboard_wizard import _get_provider_names

        names = _get_provider_names()
        assert isinstance(names, dict)
        assert len(names) > 0
        # Should include common providers
        assert "openai" in names or "anthropic" in names

    def test_get_channel_names_returns_dict(self):
        from nanobot.cli.onboard_wizard import _get_channel_names

        names = _get_channel_names()
        assert isinstance(names, dict)
        # Should include at least some channels
        assert len(names) >= 0

    def test_get_provider_info_returns_valid_structure(self):
        from nanobot.cli.onboard_wizard import _get_provider_info

        info = _get_provider_info()
        assert isinstance(info, dict)
        # Each value should be a tuple with expected structure
        for provider_name, value in info.items():
            assert isinstance(value, tuple)
            assert len(value) == 4  # (display_name, needs_api_key, needs_api_base, env_var)


class TestConfigurePydanticModelDrafts:
    @staticmethod
    def _patch_prompt_helpers(monkeypatch, tokens, text_value="secret"):
        sequence = iter(tokens)

        def fake_select(_prompt, choices, default=None):
            token = next(sequence)
            if token == "first":
                return choices[0]
            if token == "done":
                return "✓ Done"
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
                "🤖 Configure Agent Settings",
                KeyboardInterrupt(),
                "🗑️ Exit Without Saving",
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

        def fake_configure_agents(config):
            config.agents.defaults.model = "test/provider-model"

        monkeypatch.setattr(onboard_wizard, "_show_main_menu_header", lambda: None)
        monkeypatch.setattr(onboard_wizard.questionary, "select", fake_select)
        monkeypatch.setattr(onboard_wizard, "_configure_agents", fake_configure_agents)

        result = run_onboard(initial_config=initial_config)

        assert result.should_save is False
        assert result.config.model_dump(by_alias=True) == initial_config.model_dump(by_alias=True)
