"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import os
import platform
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.config.schema import InputLimitsConfig
from nanobot.utils.helpers import (
    audio_format_for_api,
    audio_mime_compat,
    build_assistant_message,
    current_time_str,
    detect_audio_mime,
    detect_image_mime,
    video_mime_compat,
)
from nanobot.utils.prompt_templates import render_template


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(self, workspace: Path, timezone: str | None = None, input_limits: InputLimitsConfig | None = None):
        self.workspace = workspace
        self.timezone = timezone
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
        self.input_limits = input_limits or InputLimitsConfig()

    @staticmethod
    def _file_size_ok(p: Path, max_bytes: int) -> bool | None:
        """Check file size via stat without reading into memory.

        Returns True if size is within limit, False if oversized,
        None if file cannot be stat'd (caller should try read_bytes instead).
        """
        try:
            return os.stat(p).st_size <= max_bytes
        except OSError:
            return None

    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(render_template("agent/skills_section.md", skills_summary=skills_summary))

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return render_template(
            "agent/identity.md",
            workspace_path=workspace_path,
            runtime=runtime,
            platform_policy=render_template("agent/platform_policy.md", system=system),
        )

    @staticmethod
    def _build_runtime_context(
        channel: str | None, chat_id: str | None, timezone: str | None = None,
    ) -> str:
        """Build untrusted runtime metadata block for injection before the user message."""
        lines = [f"Current Time: {current_time_str(timezone)}"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)

    @staticmethod
    def _merge_message_content(left: Any, right: Any) -> str | list[dict[str, Any]]:
        if isinstance(left, str) and isinstance(right, str):
            return f"{left}\n\n{right}" if left else right

        def _to_blocks(value: Any) -> list[dict[str, Any]]:
            if isinstance(value, list):
                return [item if isinstance(item, dict) else {"type": "text", "text": str(item)} for item in value]
            if value is None:
                return []
            return [{"type": "text", "text": str(value)}]

        return _to_blocks(left) + _to_blocks(right)

    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        current_role: str = "user",
        supports_vision: bool | None = None,
        supports_audio: bool | None = None,
        supports_video: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        runtime_ctx = self._build_runtime_context(channel, chat_id, self.timezone)
        user_content = self._build_user_content(
            current_message, media,
            supports_vision=supports_vision,
            supports_audio=supports_audio,
            supports_video=supports_video,
        )

        # Merge runtime context and user content into a single user message
        # to avoid consecutive same-role messages that some providers reject.
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content
        messages = [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *history,
        ]
        if messages[-1].get("role") == current_role:
            last = dict(messages[-1])
            last["content"] = self._merge_message_content(last.get("content"), merged)
            messages[-1] = last
            return messages
        messages.append({"role": current_role, "content": merged})
        return messages

    @staticmethod
    def _encode_image_block(raw: bytes, mime: str, path: Path) -> dict[str, Any]:
        """Base64-encode file bytes into an image_url content block."""
        b64 = base64.b64encode(raw).decode()
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
            "_meta": {"path": str(path)},
        }

    def _build_user_content(
        self,
        text: str,
        media: list[str] | None,
        *,
        supports_vision: bool | None = None,
        supports_audio: bool | None = None,
        supports_video: bool | None = None,
    ) -> str | list[dict[str, Any]]:
        """Build user message content with optional media blocks.

        Args:
            text: The user text message.
            media: List of file paths to media files.
            supports_vision: True=model supports images, False=use placeholder,
                             None=unconfigured (send images as before, let
                             provider/retry handle degradation).
            supports_audio: True=model supports native audio, False/None=skip
                            (channel layer already transcribed).
            supports_video: True=model supports native video, False/None=use
                            [file: path] placeholder.
        """
        if not media:
            return text

        blocks: list[dict[str, Any]] = []
        notes: list[str] = []
        limits = self.input_limits

        # Enforce image count limit
        max_images = limits.max_input_images
        image_count = 0
        image_media = []
        non_image_media = []
        for path in media:
            p = Path(path)
            guessed_mime = mimetypes.guess_type(path)[0] or ""
            if guessed_mime.startswith("image/"):
                image_count += 1
                if image_count <= max_images:
                    image_media.append(path)
            else:
                non_image_media.append(path)

        if image_count > max_images:
            extra = image_count - max_images
            noun = "image" if extra == 1 else "images"
            notes.append(
                f"[Skipped {extra} {noun}: "
                f"only the first {max_images} images are included]"
            )

        # Process images
        for path in image_media:
            p = Path(path)

            # When explicitly marked as non-vision, downgrade to text placeholder
            if supports_vision is False:
                blocks.append({"type": "text", "text": f"[image: {p}]"})
                continue

            size_ok = self._file_size_ok(p, limits.max_input_image_bytes)
            if size_ok is False:
                size_mb = limits.max_input_image_bytes // (1024 * 1024)
                notes.append(f"[Skipped image: file too large ({p.name}, limit {size_mb} MB)]")
                continue
            try:
                raw = p.read_bytes()
            except OSError:
                notes.append(f"[Skipped image: unable to read ({p.name or path})]")
                continue
            img_mime = detect_image_mime(raw[:32]) or mimetypes.guess_type(path)[0]
            if not img_mime or not img_mime.startswith("image/"):
                notes.append(f"[Skipped image: unsupported or invalid image format ({p.name})]")
                continue
            blocks.append(self._encode_image_block(raw, img_mime, p))

        # Process non-image media (audio, video, unknown)
        audio_count = 0
        video_count = 0
        for path in non_image_media:
            p = Path(path)
            guessed_mime = mimetypes.guess_type(path)[0] or ""
            is_audio = guessed_mime.startswith("audio/")
            is_video = guessed_mime.startswith("video/")

            # Pre-check file size via stat to avoid reading oversized files into memory.
            # Determine the relevant byte limit based on detected media type.
            _size_limit = 0
            if is_audio or is_video:
                _size_limit = limits.max_input_audio_bytes if is_audio else limits.max_input_video_bytes
            _stat_size_ok = self._file_size_ok(p, _size_limit) if _size_limit else None
            if _stat_size_ok is False:
                size_mb = _size_limit // (1024 * 1024)
                label = "audio" if is_audio else "video"
                notes.append(f"[Skipped {label}: file too large ({p.name}, limit {size_mb} MB)]")
                continue

            try:
                raw = p.read_bytes()
            except OSError:
                notes.append(f"[Skipped file: unable to read ({p.name or path})]")
                continue

            # Audio detection: by magic bytes or by filename
            # Always pass filename so fallback can match when magic bytes fail
            audio_mime = detect_audio_mime(raw[:32], filename=path)
            if audio_mime or is_audio:
                if supports_audio is True and audio_mime_compat(audio_mime):
                    audio_count += 1
                    if audio_count > limits.max_input_audios:
                        if audio_count == limits.max_input_audios + 1:
                            notes.append(
                                f"[Skipped audio: only {limits.max_input_audios} audio file(s) allowed]"
                            )
                        continue
                    if len(raw) > limits.max_input_audio_bytes:
                        size_mb = limits.max_input_audio_bytes // (1024 * 1024)
                        notes.append(f"[Skipped audio: file too large ({p.name}, limit {size_mb} MB)]")
                        continue
                    b64 = base64.b64encode(raw).decode()
                    blocks.append({
                        "type": "input_audio",
                        "input_audio": {"data": b64, "format": audio_format_for_api(audio_mime)},
                        "_meta": {"path": str(p)},
                    })
                else:
                    blocks.append({"type": "text", "text": f"[audio: {p}]"})
                continue

            # Video detection (already classified above)
            if is_video:
                if supports_video is True and video_mime_compat(guessed_mime):
                    video_count += 1
                    if video_count > limits.max_input_videos:
                        if video_count == limits.max_input_videos + 1:
                            notes.append(
                                f"[Skipped video: only {limits.max_input_videos} video file(s) allowed]"
                            )
                        continue
                    if len(raw) > limits.max_input_video_bytes:
                        size_mb = limits.max_input_video_bytes // (1024 * 1024)
                        notes.append(f"[Skipped video: file too large ({p.name}, limit {size_mb} MB)]")
                        continue
                    b64 = base64.b64encode(raw).decode()
                    blocks.append({
                        "type": "video_url",
                        "video_url": {"url": f"data:{guessed_mime};base64,{b64}"},
                        "_meta": {"path": str(p)},
                    })
                else:
                    blocks.append({"type": "text", "text": f"[video: {p}]"})
                continue

            # Unknown -> text placeholder
            blocks.append({"type": "text", "text": f"[file: {p}]"})

        note_text = "\n".join(notes).strip()
        text_block = text if not note_text else (f"{note_text}\n\n{text}" if text else note_text)

        if not blocks:
            return text_block
        return blocks + [{"type": "text", "text": text_block}]

    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: Any,
    ) -> list[dict[str, Any]]:
        """Add a tool result to the message list."""
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages

    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        messages.append(build_assistant_message(
            content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        ))
        return messages
