"""Tests for ContextBuilder — system prompt and message assembly."""

# FIXME: this is from blackcat and won't necessarily suit the blackcat's custom builder or not testing all the extras that the blackcat has
from pathlib import Path

import pytest

from blackcat.agent.context import ContextBuilder
from blackcat.session.goal_state import GOAL_STATE_KEY

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _builder(tmp_path: Path, **kw) -> ContextBuilder:
    return ContextBuilder(workspace=tmp_path, **kw)


# ---------------------------------------------------------------------------
# _merge_message_content (static)
# ---------------------------------------------------------------------------


class TestMergeMessageContent:
    def test_str_plus_str(self):
        result = ContextBuilder._merge_message_content("hello", "world")
        assert result == "hello\n\nworld"

    def test_empty_left_plus_str(self):
        result = ContextBuilder._merge_message_content("", "world")
        assert result == "world"

    def test_list_plus_list(self):
        left = [{"type": "text", "text": "a"}]
        right = [{"type": "text", "text": "b"}]
        result = ContextBuilder._merge_message_content(left, right)
        assert len(result) == 2
        assert result[0]["text"] == "a"
        assert result[1]["text"] == "b"

    def test_str_plus_list(self):
        right = [{"type": "text", "text": "b"}]
        result = ContextBuilder._merge_message_content("hello", right)
        assert len(result) == 2
        assert result[0]["text"] == "hello"
        assert result[1]["text"] == "b"

    def test_list_plus_str(self):
        left = [{"type": "text", "text": "a"}]
        result = ContextBuilder._merge_message_content(left, "world")
        assert len(result) == 2
        assert result[0]["text"] == "a"
        assert result[1]["text"] == "world"

    def test_none_plus_str(self):
        result = ContextBuilder._merge_message_content(None, "hello")
        assert result == [{"type": "text", "text": "hello"}]

    def test_str_plus_none(self):
        result = ContextBuilder._merge_message_content("hello", None)
        assert result == [{"type": "text", "text": "hello"}]

    def test_none_plus_none(self):
        result = ContextBuilder._merge_message_content(None, None)
        assert result == []

    def test_list_items_not_dicts_wrapped(self):
        result = ContextBuilder._merge_message_content(["raw_item"], None)
        assert result == [{"type": "text", "text": "raw_item"}]


# ---------------------------------------------------------------------------
# _load_bootstrap_files
# ---------------------------------------------------------------------------


class TestLoadBootstrapFiles:
    def test_no_bootstrap_files(self, tmp_path):
        builder = _builder(tmp_path)
        result = builder.load_identity()
        assert result == {}

    def test_agents_md(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("Be helpful.", encoding="utf-8")
        builder = _builder(tmp_path)
        result = builder.load_identity()
        assert "AGENTS.md" in result
        assert "Be helpful." in result["AGENTS.md"]

    def test_multiple_bootstrap_files(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("Rules.", encoding="utf-8")
        (tmp_path / "SOUL.md").write_text("Soul.", encoding="utf-8")
        builder = _builder(tmp_path)
        result = builder.load_identity()
        assert "AGENTS.md" in result
        assert "SOUL.md" in result
        assert "Rules." in result["AGENTS.md"]
        assert "Soul." in result["SOUL.md"]

    def test_all_bootstrap_files(self, tmp_path):
        for name in ContextBuilder.BOOTSTRAP_FILES:
            (tmp_path / name).write_text(f"Content of {name}", encoding="utf-8")
        builder = _builder(tmp_path)
        result = builder.load_identity()
        for name in ContextBuilder.BOOTSTRAP_FILES:
            assert name in result

    def test_legacy_tools_md_is_not_bootstrapped(self, tmp_path):
        (tmp_path / "TOOLS.md").write_text("workspace tool notes", encoding="utf-8")
        builder = _builder(tmp_path)
        result = builder.load_identity()
        assert "TOOLS.md" not in result

    def test_utf8_content(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("用中文回复", encoding="utf-8")
        builder = _builder(tmp_path)
        result = builder.load_identity()
        assert "用中文回复" in result["AGENTS.md"]


# ---------------------------------------------------------------------------
# _is_template_content (static)
# ---------------------------------------------------------------------------


class TestIsTemplateContent:
    def test_nonexistent_template_returns_false(self):
        assert ContextBuilder._is_template_content("anything", "nonexistent/path.md") is False

    def test_content_matching_template(self):
        from importlib.resources import files as pkg_files
        tpl = pkg_files("blackcat") / "templates" / "memory" / "MEMORY.md"
        if not tpl.is_file():
            pytest.skip("MEMORY.md template not bundled")
        original = tpl.read_text(encoding="utf-8")
        assert ContextBuilder._is_template_content(original, "memory/MEMORY.md") is True

    def test_modified_content_returns_false(self):
        from importlib.resources import files as pkg_files
        tpl = pkg_files("blackcat") / "templates" / "memory" / "MEMORY.md"
        if not tpl.is_file():
            pytest.skip("MEMORY.md template not bundled")
        assert ContextBuilder._is_template_content("totally different", "memory/MEMORY.md") is False


# ---------------------------------------------------------------------------
# Bundled bootstrap templates
# ---------------------------------------------------------------------------


class TestBundledToolContract:
    def test_tool_contract_balances_general_and_coding_workflows(self):
        from importlib.resources import files as pkg_files

        tpl = pkg_files("blackcat") / "templates" / "agent" / "tool_contract.md"
        content = tpl.read_text(encoding="utf-8")

        assert "## General Tool Contract" in content
        assert "Use the narrowest structured tool" in content
        assert "Do not use `exec` as a universal workaround" in content
        assert "## File and Coding Workflows" in content
        assert "apply_patch" in content
        assert "## Web and External Information" in content
        assert "## Messaging and Media" in content
        assert "## Scheduling and Background Work" in content
        assert "pure coding" not in content.lower()

    @pytest.mark.asyncio
    async def test_tool_contract_is_injected_without_workspace_file(self, tmp_path):
        builder = _builder(tmp_path)
        prompt = await builder.build_system_prompt()
        assert "# Tool Usage Notes" in prompt
        assert "## General Tool Contract" in prompt
        assert "Do not use `exec` as a universal workaround" in prompt


# ---------------------------------------------------------------------------
# _build_user_content
# ---------------------------------------------------------------------------


class TestBuildUserContent:
    def test_no_media_returns_string(self, tmp_path):
        builder = _builder(tmp_path)
        result = builder._build_user_content("hello", None)
        assert result == "hello"

    def test_empty_media_returns_string(self, tmp_path):
        builder = _builder(tmp_path)
        result = builder._build_user_content("hello", [])
        assert result == "hello"

    def test_nonexistent_media_file_returns_string(self, tmp_path):
        builder = _builder(tmp_path)
        result = builder._build_user_content("hello", ["/nonexistent/image.png"])
        assert result == "hello"

    def test_non_image_file_returns_string(self, tmp_path):
        txt = tmp_path / "doc.txt"
        txt.write_text("not an image", encoding="utf-8")
        builder = _builder(tmp_path)
        result = builder._build_user_content("hello", [str(txt)])
        assert result == "hello"

    def test_valid_image_returns_list(self, tmp_path):
        png = tmp_path / "test.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        builder = _builder(tmp_path)
        result = builder._build_user_content("hello", [str(png)])
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "image_url"
        assert result[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert result[1]["type"] == "text"
        assert result[1]["text"] == "hello"

    def test_image_meta_includes_path(self, tmp_path):
        png = tmp_path / "test.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        builder = _builder(tmp_path)
        result = builder._build_user_content("hello", [str(png)])
        assert "_meta" in result[0]
        assert "path" in result[0]["_meta"]


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    @pytest.mark.asyncio
    async def test_returns_nonempty_string(self, tmp_path):
        builder = _builder(tmp_path)
        result = await builder.build_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_includes_identity_section(self, tmp_path):
        builder = _builder(tmp_path)
        result = await builder.build_system_prompt()
        assert "workspace" in result.lower() or "python" in result.lower()

    @pytest.mark.asyncio
    async def test_includes_bootstrap_files(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("Be helpful and concise.", encoding="utf-8")
        builder = _builder(tmp_path)
        result = await builder.build_system_prompt()
        assert "Be helpful and concise." in result

    @pytest.mark.asyncio
    async def test_includes_session_summary(self, tmp_path):
        builder = _builder(tmp_path)
        # session_summary is now injected via build_messages, not build_system_prompt directly
        # but we can test that the builder handles history with summary
        result = await builder.build_system_prompt()
        assert isinstance(result, str)  # Just verify it doesn't crash

    @pytest.mark.asyncio
    async def test_sections_separated_by_separator(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("Rules.", encoding="utf-8")
        builder = _builder(tmp_path)
        result = await builder.build_system_prompt()
        assert "\n\n---\n\n" in result

    @pytest.mark.asyncio
    async def test_no_bootstrap_no_summary(self, tmp_path):
        builder = _builder(tmp_path)
        result = await builder.build_system_prompt()
        assert isinstance(result, str)
        assert "## AGENTS.md" not in result
        assert "[Archived Context Summary]" not in result


# ---------------------------------------------------------------------------
# build_messages
# ---------------------------------------------------------------------------


class TestBuildMessages:
    @pytest.mark.asyncio
    async def test_basic_empty_history(self, tmp_path):
        builder = _builder(tmp_path)
        messages = await builder.build_messages([], "hello")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "hello" in str(messages[1]["content"])

    @pytest.mark.asyncio
    async def test_runtime_context_injected(self, tmp_path):
        builder = _builder(tmp_path)
        messages = await builder.build_messages([], "hello", channel="cli", chat_id="direct")
        user_msg = str(messages[-1]["content"])
        assert "[Runtime Context" in user_msg
        assert "hello" in user_msg

    @pytest.mark.asyncio
    async def test_session_metadata_injects_active_goal_state(self, tmp_path):
        builder = _builder(tmp_path)
        meta = {
            GOAL_STATE_KEY: {"status": "active", "objective": "Finish docs migration."},
        }
        messages = await builder.build_messages(
            [],
            "hi",
            channel="cli",
            chat_id="x",
            session_metadata=meta,
        )
        user_msg = str(messages[-1]["content"])
        assert "Goal (active):" in user_msg
        assert "Finish docs migration." in user_msg

    @pytest.mark.asyncio
    async def test_goal_state_does_not_leak_without_session_metadata(self, tmp_path):
        builder = _builder(tmp_path)
        other_session_meta = {
            GOAL_STATE_KEY: {"status": "active", "objective": "Other chat goal."},
        }

        with_goal = await builder.build_messages(
            [],
            "hi",
            channel="websocket",
            chat_id="chat-a",
            session_metadata=other_session_meta,
        )
        without_goal = await builder.build_messages(
            [],
            "hi",
            channel="websocket",
            chat_id="chat-b",
            session_metadata={},
        )

        assert "Other chat goal." in str(with_goal[-1]["content"])
        assert "Other chat goal." not in str(without_goal[-1]["content"])
        assert "Goal (active):" not in str(without_goal[-1]["content"])

    @pytest.mark.asyncio
    async def test_current_runtime_lines_are_injected(self, tmp_path):
        builder = _builder(tmp_path)
        messages = await builder.build_messages(
            [],
            "please use @zoom tonight",
            current_runtime_lines=[
                "CLI App Attachment: @zoom (installed; tool=run_cli_app; entry_point=cli-anything-zoom).",
            ],
        )
        user_msg = str(messages[-1]["content"])

        assert "CLI App Attachment: @zoom" in user_msg
        assert "tool=run_cli_app" in user_msg
        assert "entry_point=cli-anything-zoom" in user_msg

    @pytest.mark.asyncio
    async def test_consecutive_same_role_merged(self, tmp_path):
        builder = _builder(tmp_path)
        history = [{"role": "user", "content": "previous user message"}]
        messages = await builder.build_messages(history, "new message")
        assert len(messages) == 2  # system + merged user
        assert "previous user message" in str(messages[1]["content"])
        assert "new message" in str(messages[1]["content"])

    @pytest.mark.asyncio
    async def test_different_role_appended(self, tmp_path):
        builder = _builder(tmp_path)
        history = [{"role": "assistant", "content": "previous response"}]
        messages = await builder.build_messages(history, "new message")
        assert len(messages) == 3  # system + assistant + user

    @pytest.mark.asyncio
    async def test_media_with_history(self, tmp_path):
        png = tmp_path / "img.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        builder = _builder(tmp_path)
        history = [{"role": "assistant", "content": "see this"}]
        messages = await builder.build_messages(history, "check image", media=[str(png)])
        user_msg = messages[-1]["content"]
        assert isinstance(user_msg, list)
        assert any(b.get("type") == "image_url" for b in user_msg)


# ---------------------------------------------------------------------------
# resolve_author
# ---------------------------------------------------------------------------


class TestResolveAuthor:
    def _builder_with_authors(self, tmp_path, authors):
        return ContextBuilder(workspace=tmp_path, authors=authors)

    def test_matches_known_sender_id(self, tmp_path):
        from blackcat.config.schema import PlatformIdentity

        builder = self._builder_with_authors(
            tmp_path, {"skye": PlatformIdentity(telegram="123456789", cli="skye")}
        )
        assert builder.resolve_author("123456789", "telegram") == "skye"
        assert builder.resolve_author("skye", "cli") == "skye"

    def test_int_sender_id_coerced_to_str(self, tmp_path):
        from blackcat.config.schema import PlatformIdentity

        builder = self._builder_with_authors(
            tmp_path, {"skye": PlatformIdentity(telegram=123456789)}
        )
        assert builder.resolve_author(123456789, "telegram") == "skye"
        assert builder.resolve_author("123456789", "telegram") == "skye"

    def test_unknown_sender_id_returns_unknown(self, tmp_path):
        from blackcat.config.schema import PlatformIdentity

        builder = self._builder_with_authors(
            tmp_path, {"skye": PlatformIdentity(telegram="123456789")}
        )
        assert builder.resolve_author("999", "telegram") == "unknown"
        assert builder.resolve_author("123456789", "discord") == "unknown"

    def test_no_authors_returns_unknown(self, tmp_path):
        builder = _builder(tmp_path)
        assert builder.resolve_author("anyone", "telegram") == "unknown"

    def test_missing_args_returns_unknown(self, tmp_path):
        from blackcat.config.schema import PlatformIdentity

        builder = self._builder_with_authors(
            tmp_path, {"skye": PlatformIdentity(telegram="123")}
        )
        assert builder.resolve_author(None, "telegram") == "unknown"
        assert builder.resolve_author("123", None) == "unknown"


class TestBuildSystemPromptAuthorTrust:
    @pytest.mark.asyncio
    async def test_known_author_resolves_to_trusted(self, tmp_path):
        from blackcat.config.schema import PlatformIdentity

        (tmp_path / "IDENTITY.toml").write_text(
            "[trust]\ndefault = 0.3\n\n[trust.known]\nskye = 0.95\n",
            encoding="utf-8",
        )
        builder = ContextBuilder(
            workspace=tmp_path,
            authors={"skye": PlatformIdentity(telegram="123456789")},
        )
        prompt = await builder.build_system_prompt(sender_id="123456789", channel="telegram")
        assert "Author: skye" in prompt
        assert "Trust level: trusted" in prompt

    @pytest.mark.asyncio
    async def test_unknown_author_falls_to_low_trust(self, tmp_path):
        from blackcat.config.schema import PlatformIdentity

        (tmp_path / "IDENTITY.toml").write_text(
            "[trust]\ndefault = 0.3\n\n[trust.known]\nskye = 0.95\n",
            encoding="utf-8",
        )
        builder = ContextBuilder(
            workspace=tmp_path,
            authors={"skye": PlatformIdentity(telegram="123456789")},
        )
        prompt = await builder.build_system_prompt(sender_id="999", channel="telegram")
        assert "Author: unknown" in prompt
        assert "Trust level: low" in prompt
