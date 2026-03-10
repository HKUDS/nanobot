"""Context builder for assembling agent prompts.

This module is responsible for constructing the complete message array
sent to the LLM on each iteration.  Key responsibilities:

- **System prompt assembly** — combines base personality, skill
  instructions, memory context (``MEMORY.md`` excerpt + retrieved events),
  tool schemas, and session metadata into a single system message.
- **Token budgeting** — estimates token usage and ensures the assembled
  context fits within the model's context window.
- **3-phase compression** — when the budget is exceeded:
  1. Truncate long tool-result messages.
  2. Drop tool-result messages entirely.
  3. Summarize older conversation segments via LLM call (preserving
     facts and decisions) and replace them with a compact summary.

The ``_ChatProvider`` protocol avoids circular imports with the providers
package while allowing the summarization phase to call the LLM.
"""

import base64
import hashlib
import json
import mimetypes
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from loguru import logger

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.feedback import feedback_summary

# ---------------------------------------------------------------------------
# Async provider protocol (avoids circular import with providers module)
# ---------------------------------------------------------------------------


class _ChatProvider(Protocol):
    """Minimal interface used by summarize_and_compress."""

    async def chat(
        self, *, messages: list[dict], tools: Any, model: str, temperature: float, max_tokens: int
    ) -> Any: ...


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Fast heuristic token count (~4 chars per token for English).

    Accurate enough for budget decisions without pulling in tiktoken.
    """
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens across a message list."""
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
        # Count tool call arguments
        for tc in m.get("tool_calls", []):
            fn = tc.get("function", {})
            total += estimate_tokens(fn.get("arguments", ""))
            total += estimate_tokens(fn.get("name", ""))
    return total


def compress_context(
    messages: list[dict[str, Any]],
    max_tokens: int,
    *,
    preserve_recent: int = 6,
    tool_token_threshold: int = 200,
) -> list[dict[str, Any]]:
    """Drop or truncate old tool results to fit within *max_tokens*.

    Strategy (in order):
    1. Keep system message and the most recent *preserve_recent* messages intact.
    2. For older tool-result messages, truncate large outputs to a summary line.
    3. If still over budget, drop oldest tool-result messages entirely.

    Returns a new list (does not mutate the input).
    """
    if not messages:
        return messages

    current = estimate_messages_tokens(messages)
    if current <= max_tokens:
        return messages

    # Separate: system (index 0), middle, tail
    system = messages[:1]
    tail_start = max(1, len(messages) - preserve_recent)
    middle = list(messages[1:tail_start])
    tail = messages[tail_start:]

    # Phase 1: truncate large tool results in middle
    truncation_note = "(output truncated to save context – re-run tool if needed)"
    for i, m in enumerate(middle):
        if m.get("role") == "tool":
            content = m.get("content", "")
            if isinstance(content, str) and estimate_tokens(content) > 200:
                middle[i] = {**m, "content": content[:200] + f"\n{truncation_note}"}

    trial = system + middle + tail
    if estimate_messages_tokens(trial) <= max_tokens:
        return trial

    # Phase 2: drop tool results from middle entirely (keep assistant + user)
    middle = [m for m in middle if m.get("role") != "tool"]

    trial = system + middle + tail
    if estimate_messages_tokens(trial) <= max_tokens:
        return trial

    # Phase 3: drop all middle messages (extreme case)
    logger.warning("Context compression dropped all middle messages to fit budget")
    return system + tail


# ---------------------------------------------------------------------------
# Summarisation-based compression (async, uses LLM)
# ---------------------------------------------------------------------------

_SUMMARIZE_SYSTEM = (
    "You are a context-compression assistant. "
    "Summarise the following conversation excerpt into a concise digest (≤300 tokens). "
    "Preserve: tool names used, key results, decisions made, any errors encountered. "
    "Omit pleasantries and raw data dumps. "
    "Respond with ONLY the summary text, no preamble."
)

# In-process cache: hash of serialised middle → summary text
_summary_cache: dict[str, str] = {}


def _hash_messages(msgs: list[dict[str, Any]]) -> str:
    """Fast content-based hash for caching summaries."""
    raw = json.dumps(msgs, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


async def summarize_and_compress(
    messages: list[dict[str, Any]],
    max_tokens: int,
    provider: "_ChatProvider",
    model: str,
    *,
    preserve_recent: int = 6,
    summary_max_tokens: int = 400,
    tool_token_threshold: int = 200,
) -> list[dict[str, Any]]:
    """Like :func:`compress_context` but uses an LLM call for Phase 3.

    When truncation alone isn't enough, the middle messages are summarised
    by the *provider* into a ``[Compressed Summary]`` system message, keeping
    key facts in the context window.

    Falls back to the synchronous drop-all behaviour if the LLM call fails.
    """
    if not messages:
        return messages

    current = estimate_messages_tokens(messages)
    if current <= max_tokens:
        return messages

    # Separate: system (index 0), middle, tail
    system = messages[:1]
    tail_start = max(1, len(messages) - preserve_recent)
    middle = list(messages[1:tail_start])
    tail = messages[tail_start:]

    # Phase 1: truncate large tool results in middle
    truncation_note = "(output truncated to save context – re-run tool if needed)"
    for i, m in enumerate(middle):
        if m.get("role") == "tool":
            content = m.get("content", "")
            if isinstance(content, str) and estimate_tokens(content) > tool_token_threshold:
                middle[i] = {**m, "content": content[:tool_token_threshold] + f"\n{truncation_note}"}

    trial = system + middle + tail
    if estimate_messages_tokens(trial) <= max_tokens:
        return trial

    # Phase 2: drop tool results from middle entirely (keep assistant + user)
    middle_no_tools = [m for m in middle if m.get("role") != "tool"]

    trial = system + middle_no_tools + tail
    if estimate_messages_tokens(trial) <= max_tokens:
        return trial

    # Phase 3 (enhanced): summarise middle messages via LLM
    if not middle:
        logger.warning("Context compression dropped all middle messages to fit budget")
        return system + tail

    cache_key = _hash_messages(middle)
    summary_text = _summary_cache.get(cache_key)

    if summary_text is None:
        # Build a digest of the middle messages for the summariser
        digest_parts: list[str] = []
        for m in middle:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            # Include tool call names if present
            tc_names = [tc.get("function", {}).get("name", "") for tc in m.get("tool_calls", [])]
            line = f"[{role}] {content[:600]}"
            if tc_names:
                line += f" (calls: {', '.join(tc_names)})"
            digest_parts.append(line)

        digest = "\n".join(digest_parts)

        try:
            resp = await provider.chat(
                messages=[
                    {"role": "system", "content": _SUMMARIZE_SYSTEM},
                    {"role": "user", "content": digest},
                ],
                tools=None,
                model=model,
                temperature=0.0,
                max_tokens=summary_max_tokens,
            )
            summary_text = (resp.content or "").strip()
            if summary_text:
                _summary_cache[cache_key] = summary_text
                logger.debug(
                    "Summarised {} middle messages into {} tokens",
                    len(middle),
                    estimate_tokens(summary_text),
                )
        except Exception:
            logger.warning("LLM summarisation failed; falling back to drop-all")
            summary_text = None

    if summary_text:
        summary_msg: dict[str, Any] = {
            "role": "system",
            "content": (
                "[Compressed Summary — earlier conversation was elided to save context]\n\n"
                + summary_text
            ),
        }
        trial = system + [summary_msg] + tail
        if estimate_messages_tokens(trial) <= max_tokens:
            return trial

    # Absolute fallback: drop everything
    logger.warning("Context compression dropped all middle messages to fit budget")
    return system + tail


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.

    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]

    def __init__(
        self,
        workspace: Path,
        *,
        memory_retrieval_k: int = 6,
        memory_token_budget: int = 900,
        memory_md_token_cap: int = 1500,
        memory_rollout_overrides: dict[str, Any] | None = None,
        role_system_prompt: str = "",
    ):
        self.workspace = workspace
        self.memory = MemoryStore(workspace, rollout_overrides=memory_rollout_overrides)
        self.skills = SkillsLoader(workspace)
        self.memory_retrieval_k = memory_retrieval_k
        self.memory_token_budget = memory_token_budget
        self.memory_md_token_cap = memory_md_token_cap
        self.role_system_prompt = role_system_prompt

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        current_message: str | None = None,
    ) -> str:
        """
        Build the system prompt from bootstrap files, memory, and skills.

        Args:
            skill_names: Optional list of skills to include.

        Returns:
            Complete system prompt.
        """
        parts = []

        # Core identity
        parts.append(self._get_identity())

        # Role-specific system prompt (multi-agent routing)
        if self.role_system_prompt:
            parts.append(f"# Agent Role\n\n{self.role_system_prompt}")

        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Memory context — graceful degradation if retrieval crashes
        try:
            memory = self.memory.get_memory_context(
                query=current_message,
                retrieval_k=self.memory_retrieval_k,
                token_budget=self.memory_token_budget,
                memory_md_token_cap=self.memory_md_token_cap,
            )
        except Exception:
            logger.warning("Memory context retrieval failed; continuing without memory")
            memory = ""
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        # Feedback summary — surface correction stats so the agent adapts
        events_file = self.memory.persistence.events_file
        fb_summary = feedback_summary(events_file)
        if fb_summary:
            parts.append(f"# Feedback\n\n{fb_summary}")

        # Skills - progressive loading
        # 1. Active skills: always-loaded + requested/matched for this turn
        always_skills = self.skills.get_always_skills()
        requested_skills = skill_names or []
        active_skills = list(dict.fromkeys([*always_skills, *requested_skills]))
        if active_skills:
            active_content = self.skills.load_skills_for_context(active_skills)
            if active_content:
                parts.append(f"# Active Skills\n\n{active_content}")

        # 2. Available skills: only show summary (agent uses read_file to load)
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        sys_name = platform.system()
        runtime = f"{'macOS' if sys_name == 'Darwin' else sys_name} {platform.machine()}, Python {platform.python_version()}"

        return f"""# nanobot 🐈

You are nanobot, a helpful AI assistant.

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable)
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

Reply directly with text for conversations. Only use the 'message' tool to send to a specific chat channel.

## Tool Call Guidelines
- Before calling tools, you may briefly state your intent (e.g. "Let me check that"), but NEVER predict or describe the expected result before receiving it.
- Before modifying a file, read it first to confirm its current content.
- Do not assume a file or directory exists — use list_dir or read_file to verify.
- After writing or editing a file, re-read it if accuracy matters.
- If a tool call fails, analyze the error before retrying with a different approach.

## Verification & Uncertainty
- Do not guess when evidence is weak, missing, or conflicting.
- Verify important claims using available files/tools before finalizing an answer.
- If verification is inconclusive, clearly state that the result is unclear and summarize what was checked.

## Memory
- Remember important facts: write to {workspace_path}/memory/MEMORY.md
- Recall past events: grep {workspace_path}/memory/HISTORY.md

## Using Your Memory Context
The `# Memory` section of this prompt contains retrieved personal facts, user profile data,
entity relationships, and past events. Follow these rules when answering:
- **Prefer memory over general knowledge.** If the Memory section contains an answer, use it
  rather than relying on your training data. Memory is more recent and user-specific.
- **Cite specific values verbatim.** When memory contains exact names, numbers, regions, or
  technical terms, use those exact terms in your answer — do not paraphrase or generalize.
- **Use the Entity Graph.** The `## Entity Graph` section lists verified relationships
  (subject → predicate → object). Treat these as authoritative facts about who/what is
  connected to whom/what.
- **Trust Profile Memory.** The `## Profile Memory` section reflects the user's verified
  preferences, constraints, and relationships. Higher confidence scores (closer to 1.0)
  indicate stronger evidence.
- **Answer from memory first.** If the memory context answers the user's question, respond
  directly. Only use tools for information that is NOT in your memory context.
  Do NOT fall back to tool calls or file searches for questions your memory already answers.
- **Be complete.** Include all relevant items from memory in your answer — do not
  summarize away details or omit entries from a set.
- **Memory overrides training data.** If memory mentions specific people, projects, or terms,
  treat those as workspace-specific facts, not general-knowledge concepts.

## Feedback & Corrections
- If the user corrects you or expresses dissatisfaction, use the `feedback` tool to record it (rating='negative' + their correction as comment).
- If the user praises an answer or reacts positively, use the `feedback` tool with rating='positive'.
- Learn from past corrections listed in the Feedback section of this prompt."""

    @staticmethod
    def _inject_runtime_context(
        user_content: str | list[dict[str, Any]],
        channel: str | None,
        chat_id: str | None,
    ) -> str | list[dict[str, Any]]:
        """Append dynamic runtime context to the tail of the user message."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        block = "[Runtime Context]\n" + "\n".join(lines)
        if isinstance(user_content, str):
            return f"{user_content}\n\n{block}"
        return [*user_content, {"type": "text", "text": block}]

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
        verify_before_answer: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Build the complete message list for an LLM call.

        Args:
            history: Previous conversation messages.
            current_message: The new user message.
            skill_names: Optional skills to include.
            media: Optional list of local file paths for images/media.
            channel: Current channel (telegram, feishu, etc.).
            chat_id: Current chat/user ID.

        Returns:
            List of messages including system prompt.
        """
        messages = []

        # System prompt
        system_prompt = self.build_system_prompt(skill_names, current_message=current_message)
        if verify_before_answer:
            system_prompt += (
                "\n\n## Verification Required\n"
                "Before answering this turn, verify the key claim(s) with available files/tools. "
                "If results remain inconclusive, say the outcome is unclear and list what was verified."
            )
        messages.append({"role": "system", "content": system_prompt})

        # History
        messages.extend(history)

        # Current message (with optional image attachments)
        user_content = self._build_user_content(current_message, media)
        user_content = self._inject_runtime_context(user_content, channel, chat_id)
        messages.append({"role": "user", "content": user_content})  # type: ignore[dict-item]

        return messages

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self, messages: list[dict[str, Any]], tool_call_id: str, tool_name: str, result: str
    ) -> list[dict[str, Any]]:
        """
        Add a tool result to the message list.

        Args:
            messages: Current message list.
            tool_call_id: ID of the tool call.
            tool_name: Name of the tool.
            result: Tool execution result.

        Returns:
            Updated message list.
        """
        messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result}
        )
        return messages

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Add an assistant message to the message list.

        Args:
            messages: Current message list.
            content: Message content.
            tool_calls: Optional tool calls.
            reasoning_content: Thinking output (Kimi, DeepSeek-R1, etc.).

        Returns:
            Updated message list.
        """
        msg: dict[str, Any] = {"role": "assistant"}

        # Always include content — some providers (e.g. StepFun) reject
        # assistant messages that omit the key entirely.
        msg["content"] = content

        if tool_calls:
            msg["tool_calls"] = tool_calls

        # Include reasoning content when provided (required by some thinking models)
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content

        messages.append(msg)
        return messages
