"""Two-phase memory processor: Dream class."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.memory.file_store import MemoryStore
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.utils.helpers import truncate_text
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


_STALE_THRESHOLD_DAYS = 14


class Dream:
    """Two-phase memory processor: analyze history.jsonl, then edit files via AgentRunner.

    Phase 1 produces an analysis summary (plain LLM call).
    Phase 2 delegates to AgentRunner with read_file / edit_file tools so the
    LLM can make targeted, incremental edits instead of replacing entire files.
    """

    _MEMORY_FILE_MAX_CHARS = 32_000
    _SOUL_FILE_MAX_CHARS = 16_000
    _USER_FILE_MAX_CHARS = 16_000
    _HISTORY_ENTRY_PREVIEW_MAX_CHARS = 4_000

    def __init__(
        self,
        store: MemoryStore,
        provider: LLMProvider,
        model: str,
        max_batch_size: int = 20,
        max_iterations: int = 10,
        max_tool_result_chars: int = 16_000,
        annotate_line_ages: bool = True,
    ):
        self.store = store
        self.provider = provider
        self.model = model
        self.max_batch_size = max_batch_size
        self.max_iterations = max_iterations
        self.max_tool_result_chars = max_tool_result_chars
        self.annotate_line_ages = annotate_line_ages
        self._runner = AgentRunner(provider)
        self._tools = self._build_tools()

    def set_provider(self, provider: LLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model
        self._runner.provider = provider

    def _build_tools(self) -> ToolRegistry:
        from nanobot.agent.skills import BUILTIN_SKILLS_DIR
        from nanobot.agent.tools.file_state import FileStates
        from nanobot.agent.tools.filesystem import EditFileTool, ReadFileTool, WriteFileTool

        tools = ToolRegistry()
        workspace = self.store.workspace
        extra_read = [BUILTIN_SKILLS_DIR] if BUILTIN_SKILLS_DIR.exists() else None
        file_states = FileStates()
        tools.register(ReadFileTool(
            workspace=workspace,
            allowed_dir=workspace,
            extra_allowed_dirs=extra_read,
            file_states=file_states,
        ))
        tools.register(EditFileTool(workspace=workspace, allowed_dir=workspace, file_states=file_states))
        skills_dir = workspace / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        tools.register(WriteFileTool(workspace=workspace, allowed_dir=skills_dir, file_states=file_states))
        return tools

    def _list_existing_skills(self) -> list[str]:
        import re as _re
        from nanobot.agent.skills import BUILTIN_SKILLS_DIR

        desc_re = _re.compile(r"^description:\s*(.+)$", _re.MULTILINE | _re.IGNORECASE)
        entries: dict[str, str] = {}
        for base in (self.store.workspace / "skills", BUILTIN_SKILLS_DIR):
            if not base.exists():
                continue
            for d in base.iterdir():
                if not d.is_dir():
                    continue
                skill_md = d / "SKILL.md"
                if not skill_md.exists():
                    continue
                if d.name in entries and base == BUILTIN_SKILLS_DIR:
                    continue
                content = skill_md.read_text(encoding="utf-8")[:500]
                m = desc_re.search(content)
                desc = m.group(1).strip() if m else "(no description)"
                entries[d.name] = desc
        return [f"{name} — {desc}" for name, desc in sorted(entries.items())]

    def _annotate_with_ages(self, content: str) -> str:
        file_path = "memory/MEMORY.md"
        try:
            ages = self.store.git.line_ages(file_path)
        except Exception:
            logger.debug("line_ages failed for {}", file_path)
            return content
        if not ages:
            return content
        had_trailing = content.endswith("\n")
        lines = content.splitlines()
        if len(lines) != len(ages):
            logger.debug(
                "line_ages length mismatch for {} (lines={}, ages={}); skipping annotation",
                file_path, len(lines), len(ages),
            )
            return content
        annotated: list[str] = []
        for line, age in zip(lines, ages):
            if not line.strip():
                annotated.append(line)
                continue
            if age.age_days > _STALE_THRESHOLD_DAYS:
                annotated.append(f"{line}  ← {age.age_days}d")
            else:
                annotated.append(line)
        result = "\n".join(annotated)
        if had_trailing:
            result += "\n"
        return result

    async def run(self) -> bool:
        from nanobot.agent.skills import BUILTIN_SKILLS_DIR

        last_cursor = self.store.get_last_dream_cursor()
        entries = self.store.read_unprocessed_history(since_cursor=last_cursor)
        if not entries:
            return False

        batch = entries[: self.max_batch_size]
        logger.info(
            "Dream: processing {} entries (cursor {}→{}), batch={}",
            len(entries), last_cursor, batch[-1]["cursor"], len(batch),
        )

        history_text = "\n".join(
            f"[{e['timestamp']}] "
            f"{truncate_text(e['content'], self._HISTORY_ENTRY_PREVIEW_MAX_CHARS)}"
            for e in batch
        )

        current_date = datetime.now().strftime("%Y-%m-%d")
        raw_memory = self.store.read_memory() or "(empty)"
        annotated_memory = (
            self._annotate_with_ages(raw_memory) if self.annotate_line_ages else raw_memory
        )
        current_memory = truncate_text(annotated_memory, self._MEMORY_FILE_MAX_CHARS)
        current_soul = truncate_text(self.store.read_soul() or "(empty)", self._SOUL_FILE_MAX_CHARS)
        current_user = truncate_text(self.store.read_user() or "(empty)", self._USER_FILE_MAX_CHARS)

        file_context = (
            f"## Current Date\n{current_date}\n\n"
            f"## Current MEMORY.md ({len(current_memory)} chars)\n{current_memory}\n\n"
            f"## Current SOUL.md ({len(current_soul)} chars)\n{current_soul}\n\n"
            f"## Current USER.md ({len(current_user)} chars)\n{current_user}"
        )

        phase1_prompt = f"## Conversation History\n{history_text}\n\n{file_context}"

        try:
            phase1_response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": render_template(
                            "agent/dream_phase1.md",
                            strip=True,
                            stale_threshold_days=_STALE_THRESHOLD_DAYS,
                        ),
                    },
                    {"role": "user", "content": phase1_prompt},
                ],
                tools=None,
                tool_choice=None,
            )
            analysis = phase1_response.content or ""
            logger.debug("Dream Phase 1 analysis ({} chars): {}", len(analysis), analysis[:500])
        except Exception:
            logger.exception("Dream Phase 1 failed")
            return False

        existing_skills = self._list_existing_skills()
        skills_section = ""
        if existing_skills:
            skills_section = (
                "\n\n## Existing Skills\n"
                + "\n".join(f"- {s}" for s in existing_skills)
            )
        phase2_prompt = f"## Analysis Result\n{analysis}\n\n{file_context}{skills_section}"

        tools = self._tools
        skill_creator_path = BUILTIN_SKILLS_DIR / "skill-creator" / "SKILL.md"
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": render_template(
                    "agent/dream_phase2.md",
                    strip=True,
                    skill_creator_path=str(skill_creator_path),
                ),
            },
            {"role": "user", "content": phase2_prompt},
        ]

        try:
            result = await self._runner.run(AgentRunSpec(
                initial_messages=messages,
                tools=tools,
                model=self.model,
                max_iterations=self.max_iterations,
                max_tool_result_chars=self.max_tool_result_chars,
                fail_on_tool_error=False,
            ))
            logger.debug(
                "Dream Phase 2 complete: stop_reason={}, tool_events={}",
                result.stop_reason, len(result.tool_events),
            )
            for ev in (result.tool_events or []):
                logger.info(
                    "Dream tool_event: name={}, status={}, detail={}",
                    ev.get("name"), ev.get("status"), ev.get("detail", "")[:200],
                )
        except Exception:
            logger.exception("Dream Phase 2 failed")
            result = None

        changelog: list[str] = []
        if result and result.tool_events:
            for event in result.tool_events:
                if event["status"] == "ok":
                    changelog.append(f"{event['name']}: {event['detail']}")

        if result and result.stop_reason == "completed":
            new_cursor = batch[-1]["cursor"]
            self.store.set_last_dream_cursor(new_cursor)
            logger.info("Dream done: {} change(s), cursor advanced to {}", len(changelog), new_cursor)
        else:
            reason = result.stop_reason if result else "exception"
            logger.warning(
                "Dream incomplete ({}): cursor NOT advanced, will retry next cron cycle", reason
            )

        self.store.compact_history()

        if changelog and self.store.git.is_initialized():
            ts = batch[-1]["timestamp"]
            summary = f"dream: {ts}, {len(changelog)} change(s)"
            commit_msg = f"{summary}\n\n{analysis.strip()}"
            sha = self.store.git.auto_commit(commit_msg)
            if sha:
                logger.info("Dream commit: {}", sha)

        return True
