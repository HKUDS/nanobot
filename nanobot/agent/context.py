"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools import image_generation as image_generation_tools
from nanobot.agent.tools import mcp as mcp_tools
from nanobot.agent.tools import sessions as session_tools
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.apps.cli import utils as cli_app_utils
from nanobot.bus.events import (
    INBOUND_META_RUNTIME_CONTROL,
    RUNTIME_CONTROL_SESSION_DISCARD,
    InboundMessage,
)
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_END,
    RUNTIME_CONTEXT_MESSAGE_META,
    RUNTIME_CONTEXT_TAG,
    RuntimeContextBlock,
    append_runtime_context,
)
from nanobot.security.workspace_access import WorkspaceScopeResolver
from nanobot.session.keys import last_channel_from_metadata
from nanobot.session.manager import Session
from nanobot.session.summary import SessionSummary
from nanobot.utils.helpers import detect_image_mime, load_bundled_template
from nanobot.utils.prompt_templates import render_template


def session_extra(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return persisted kwargs for turn-attached capabilities."""
    return (
        cli_app_utils.session_extra(metadata)
        | mcp_tools.session_extra(metadata)
        | session_tools.session_extra(metadata)
    )


async def handle_runtime_control(state: Any, msg: InboundMessage, tools: ToolRegistry) -> bool:
    if msg.metadata.get(INBOUND_META_RUNTIME_CONTROL) == RUNTIME_CONTROL_SESSION_DISCARD:
        await state.discard_session(msg.session_key)
        return True
    return await image_generation_tools.handle_runtime_control(state, msg, tools)


@dataclass(frozen=True, slots=True)
class PersistedPromptContextResolver:
    """Restore prompt routing context when no inbound message is available."""

    workspace_scopes: WorkspaceScopeResolver
    unified_session: bool = False

    def __call__(self, session: Session) -> tuple[str | None, Path]:
        channel = session.key.split(":", 1)[0] if ":" in session.key else None
        if self.unified_session:
            route = last_channel_from_metadata(session.metadata)
            if route is not None:
                channel = route[0]
        scope = self.workspace_scopes.for_turn(
            channel=channel,
            message_metadata=None,
            session_metadata=session.metadata,
        )
        return channel, scope.project_path


@dataclass(frozen=True, slots=True)
class TranscriptInput:
    """Raw turn inputs from which ``ContextBuilder`` assembles a transcript."""

    history: list[dict[str, Any]]
    current_message: str | None
    media: Sequence[str] | None = None
    current_role: str = "user"
    session_summary: SessionSummary | None = None
    runtime_context_blocks: Sequence[RuntimeContextBlock] | None = None

    @property
    def message_count(self) -> int:
        """Number of boundary-preserving messages in the assembled transcript."""
        return 1 + len(self.history) + (self.current_message is not None)


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md"]
    _SKIPPABLE_DEFAULTS = {"AGENTS.md", "USER.md"}
    _RUNTIME_CONTEXT_TAG = RUNTIME_CONTEXT_TAG
    _RUNTIME_CONTEXT_END = RUNTIME_CONTEXT_END

    def __init__(self, workspace: Path, timezone: str | None = None, disabled_skills: list[str] | None = None):
        self.workspace = workspace
        self.timezone = timezone
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace, disabled_skills=set(disabled_skills) if disabled_skills else None)

    def build_system_prompt(
        self,
        *,
        channel: str | None = None,
        session_summary: SessionSummary | None = None,
        workspace: Path | None = None,
        include_memory: bool = True,
    ) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        root = workspace or self.workspace
        parts = [self._get_identity(channel=channel, workspace=root)]

        bootstrap = self._load_bootstrap_files(root)
        if bootstrap:
            parts.append(bootstrap)

        parts.append(render_template("agent/tool_contract.md"))

        project_path = root.expanduser().resolve()
        if project_path != self.workspace.expanduser().resolve():
            parts.append(
                "# Current Project\n\n"
                f"Working directory: {project_path}\n"
                "Use it as the default root for project files and relative tool paths."
            )

        if include_memory:
            memory = self.memory.read_memory()
            if memory and not self._is_template_content(memory, "memory/MEMORY.md"):
                parts.append(f"# Memory\n\n## Long-term Memory\n{memory}")

        active_skills = self.skills.get_always_skills()
        if active_skills:
            active_content = self.skills.load_skills_for_context(active_skills)
            if active_content:
                parts.append(f"# Active Skills\n\n{active_content}")

        skills_summary = self.skills.build_skills_summary(
            exclude=set(active_skills),
            workspace=root,
        )
        if skills_summary:
            parts.append(render_template("agent/skills_section.md", skills_summary=skills_summary))

        if session_summary:
            parts.append(
                "[Archived Context Summary]\n\n"
                f"Previous conversation summary (last active {session_summary['last_active']}):\n"
                f"{session_summary['text']}"
            )

        return "\n\n---\n\n".join(parts)

    def _get_identity(self, channel: str | None = None, workspace: Path | None = None) -> str:
        """Get the core identity section."""
        root = workspace or self.workspace
        workspace_path = str(root.expanduser().resolve())
        agent_workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return render_template(
            "agent/identity.md",
            workspace_path=workspace_path,
            agent_workspace_path=agent_workspace_path,
            runtime=runtime,
            platform_policy=render_template("agent/platform_policy.md", system=system),
            channel=channel or "",
        )

    @staticmethod
    def _merge_message_content(left: Any, right: Any) -> str | list[dict[str, Any]]:
        if isinstance(left, str) and isinstance(right, str):
            if not left:
                return right
            if not right:
                return left
            return f"{left}\n\n{right}"

        def _to_blocks(value: Any) -> list[dict[str, Any]]:
            if isinstance(value, list):
                return [
                    cast(dict[str, Any], item)
                    if isinstance(item, dict)
                    else {"type": "text", "text": str(item)}
                    for item in cast(list[Any], value)
                ]
            if value is None:
                return []
            return [{"type": "text", "text": str(value)}]

        return _to_blocks(left) + _to_blocks(right)

    def _load_bootstrap_files(self, workspace: Path | None = None) -> str:
        """Load project instructions plus the agent's global profile files."""
        parts: list[str] = []
        project_root = workspace or self.workspace
        sources = [
            ("AGENTS.md", project_root),
            ("SOUL.md", self.workspace),
            ("USER.md", self.workspace),
        ]

        for filename, root in sources:
            file_path = root / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                if filename == "SOUL.md" and self._is_template_content(
                    content,
                    "legacy/SOUL.md",
                ):
                    content = load_bundled_template("SOUL.md") or content
                if not content.strip():
                    continue
                if filename in self._SKIPPABLE_DEFAULTS and self._is_template_content(
                    content, filename
                ):
                    continue
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _is_template_content(content: str, template_path: str) -> bool:
        """Check if *content* is identical to the bundled template (user hasn't customized it)."""
        tpl = load_bundled_template(template_path)
        if tpl is not None:
            return content.strip() == tpl.strip()
        return False

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str | None,
        *,
        media: list[str] | None = None,
        channel: str | None = None,
        current_role: str = "user",
        session_summary: SessionSummary | None = None,
        runtime_context_blocks: Sequence[RuntimeContextBlock] | None = None,
        workspace: Path | None = None,
        include_memory: bool = True,
    ) -> list[dict[str, Any]]:
        """Compatibility wrapper for callers that need merged adjacent roles."""
        messages = self.build_transcript(
            TranscriptInput(
                history=history,
                current_message=current_message,
                media=media,
                current_role=current_role,
                session_summary=session_summary,
                runtime_context_blocks=runtime_context_blocks,
            ),
            channel=channel,
            workspace=workspace,
            include_memory=include_memory,
        )
        if current_message is None:
            return messages
        current = messages[-1]
        if len(messages) < 2 or messages[-2].get("role") != current.get("role"):
            return messages

        merged = dict(messages[-2])
        merged["content"] = self._merge_message_content(
            merged.get("content"),
            current.get("content"),
        )
        current_meta = current.get("_meta")
        if current.get("role") == "user" and isinstance(current_meta, dict):
            internal_meta = dict(merged.get("_meta") or {})
            internal_meta.update(cast(dict[str, Any], current_meta))
            merged["_meta"] = internal_meta
        return [*messages[:-2], merged]

    def build_transcript(
        self,
        transcript: TranscriptInput,
        *,
        channel: str | None = None,
        workspace: Path | None = None,
        include_memory: bool = True,
    ) -> list[dict[str, Any]]:
        """Build a model transcript while preserving the fresh-turn boundary."""
        root = workspace or self.workspace
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self.build_system_prompt(
                    channel=channel,
                    session_summary=transcript.session_summary,
                    workspace=root,
                    include_memory=include_memory,
                ),
            },
            *transcript.history,
        ]
        if transcript.current_message is None:
            return messages

        current = self.build_current_message(
            transcript.current_message,
            media=list(transcript.media) if transcript.media else None,
            current_role=transcript.current_role,
            runtime_context_blocks=transcript.runtime_context_blocks,
        )
        messages.append(current)
        return messages

    def build_current_message(
        self,
        current_message: str,
        *,
        media: list[str] | None = None,
        current_role: str = "user",
        runtime_context_blocks: Sequence[RuntimeContextBlock] | None = None,
    ) -> dict[str, Any]:
        """Build only the fresh turn message without merging it into history."""
        content = self.build_user_content(current_message, image_paths=media)
        blocks: list[RuntimeContextBlock] = []
        if current_role == "user":
            blocks.extend(runtime_context_blocks or ())
            skill_context = self.skills.build_explicit_skill_runtime_context(current_message)
            if skill_context is not None and skill_context not in blocks:
                blocks.append(skill_context)
        merged, runtime_context_meta = append_runtime_context(content, blocks)
        current: dict[str, Any] = {"role": current_role, "content": merged}
        if current_role == "user" and runtime_context_meta is not None:
            current["_meta"] = {
                RUNTIME_CONTEXT_MESSAGE_META: runtime_context_meta,
            }
        return current

    def build_user_content(
        self,
        text: str,
        image_paths: list[str] | None,
    ) -> str | list[dict[str, Any]]:
        """Build user message content from prefiltered image paths."""
        if not image_paths:
            return text

        image_blocks: list[dict[str, Any]] = []
        for path in image_paths:
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            # Re-detect from the bytes used for the request: the file may have
            # changed since attachment routing, and the data URL needs its MIME.
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(raw).decode()
            image_blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
                "_meta": {"path": str(p)},
            })

        if not image_blocks:
            return text
        return image_blocks + [{"type": "text", "text": text}]
