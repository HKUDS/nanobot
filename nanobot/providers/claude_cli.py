"""Claude CLI provider - uses Claude Code subscription via CLI."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


# Model aliases for Claude CLI
CLAUDE_MODEL_ALIASES: dict[str, str] = {
    "opus": "opus",
    "opus-4.5": "opus",
    "opus-4": "opus",
    "claude-opus-4-5": "opus",
    "claude-opus-4": "opus",
    "sonnet": "sonnet",
    "sonnet-4.5": "sonnet",
    "sonnet-4.1": "sonnet",
    "sonnet-4.0": "sonnet",
    "claude-sonnet-4-5": "sonnet",
    "claude-sonnet-4-1": "sonnet",
    "claude-sonnet-4-0": "sonnet",
    "haiku": "haiku",
    "haiku-3.5": "haiku",
    "claude-haiku-3-5": "haiku",
}


class ClaudeCliProvider(LLMProvider):
    """
    LLM provider that uses the Claude CLI (Claude Code subscription).
    
    This provider spawns the `claude` CLI process to interact with Claude,
    allowing use of Claude Max subscription instead of API credits.
    """
    
    def __init__(
        self,
        default_model: str = "opus",
        command: str = "claude",
        timeout_seconds: int = 300,
        working_dir: str | None = None,
    ):
        """
        Initialize the Claude CLI provider.
        
        Args:
            default_model: Default model to use (opus, sonnet, haiku).
            command: Path to claude CLI executable.
            timeout_seconds: Max time to wait for CLI response.
            working_dir: Working directory for CLI execution.
        """
        super().__init__(api_key=None, api_base=None)
        self.default_model = self._normalize_model(default_model)
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.working_dir = working_dir
        self._session_ids: dict[str, str] = {}  # session_key -> claude_session_id
    
    def _normalize_model(self, model: str) -> str:
        """Normalize model name to Claude CLI format."""
        model_lower = model.lower().strip()
        return CLAUDE_MODEL_ALIASES.get(model_lower, model_lower)
    
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        session_key: str | None = None,
    ) -> LLMResponse:
        """
        Send a chat completion request via Claude CLI.
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions (NOT SUPPORTED in CLI mode).
            model: Model identifier (opus, sonnet, haiku).
            max_tokens: Maximum tokens in response (ignored by CLI).
            temperature: Sampling temperature (ignored by CLI).
            session_key: Optional session key for conversation continuity.
        
        Returns:
            LLMResponse with content.
        
        Note:
            Tool calls are NOT supported when using Claude CLI.
            The CLI runs in non-interactive mode without tool execution.
        """
        model = self._normalize_model(model or self.default_model)
        
        # Build prompt from messages
        prompt = self._build_prompt_from_messages(messages)
        
        # Get or create session ID
        session_id = None
        if session_key:
            session_id = self._session_ids.get(session_key)
        
        try:
            result = await self._run_claude_cli(
                prompt=prompt,
                model=model,
                session_id=session_id,
                system_prompt=self._extract_system_prompt(messages),
            )
            
            # Store session ID for future calls
            if session_key and result.get("session_id"):
                self._session_ids[session_key] = result["session_id"]
            
            return LLMResponse(
                content=result.get("text", ""),
                tool_calls=[],  # CLI doesn't support tools
                finish_reason="stop",
                usage=result.get("usage", {}),
            )
            
        except asyncio.TimeoutError:
            return LLMResponse(
                content="Error: Claude CLI timed out.",
                finish_reason="error",
            )
        except Exception as e:
            logger.error(f"Claude CLI error: {e}")
            return LLMResponse(
                content=f"Error calling Claude CLI: {str(e)}",
                finish_reason="error",
            )
    
    def _build_prompt_from_messages(self, messages: list[dict[str, Any]]) -> str:
        """Convert message list to a single prompt string."""
        parts = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                # System messages are handled separately
                continue
            elif role == "user":
                parts.append(f"Human: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
            elif role == "tool":
                # Include tool results as context
                tool_name = msg.get("name", "tool")
                parts.append(f"[Tool Result from {tool_name}]: {content}")
        
        # Add final prompt marker
        if parts and not parts[-1].startswith("Human:"):
            parts.append("Human: Please continue.")
        
        return "\n\n".join(parts)
    
    def _extract_system_prompt(self, messages: list[dict[str, Any]]) -> str | None:
        """Extract system prompt from messages."""
        for msg in messages:
            if msg.get("role") == "system":
                return msg.get("content", "")
        return None
    
    async def _run_claude_cli(
        self,
        prompt: str,
        model: str,
        session_id: str | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute Claude CLI and parse response.
        
        Args:
            prompt: The user prompt.
            model: Model to use.
            session_id: Optional session ID for resumption.
            system_prompt: Optional system prompt to append.
        
        Returns:
            Dict with 'text', 'session_id', and optionally 'usage'.
        """
        # Build command arguments
        args = [
            self.command,
            "-p",  # Print mode (non-interactive)
            "--output-format", "json",
            "--dangerously-skip-permissions",
            "--model", model,
        ]
        
        # Add session handling
        if session_id:
            args.extend(["--resume", session_id])
        
        # Add system prompt if provided and this is a new session
        if system_prompt and not session_id:
            args.extend(["--append-system-prompt", system_prompt])
        
        # Add the prompt as the final argument
        args.append(prompt)
        
        # Clear Anthropic API key from environment to force CLI auth
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_API_KEY_OLD", None)
        
        logger.debug(f"Running Claude CLI: {self.command} with model={model}")
        
        # Run the CLI
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.working_dir,
            env=env,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise
        
        stdout_text = stdout.decode("utf-8").strip()
        stderr_text = stderr.decode("utf-8").strip()
        
        if process.returncode != 0:
            error_msg = stderr_text or stdout_text or "CLI failed with no output"
            raise RuntimeError(f"Claude CLI failed (code {process.returncode}): {error_msg}")
        
        # Parse JSON output
        return self._parse_cli_output(stdout_text)
    
    def _parse_cli_output(self, output: str) -> dict[str, Any]:
        """Parse Claude CLI JSON output."""
        if not output:
            return {"text": "", "session_id": None}
        
        try:
            # Try parsing as single JSON object
            data = json.loads(output)
            return self._extract_from_json(data)
        except json.JSONDecodeError:
            pass
        
        # Try parsing as JSONL (multiple JSON objects)
        result_text = []
        session_id = None
        usage = {}
        
        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                extracted = self._extract_from_json(data)
                if extracted.get("text"):
                    result_text.append(extracted["text"])
                if extracted.get("session_id"):
                    session_id = extracted["session_id"]
                if extracted.get("usage"):
                    usage = extracted["usage"]
            except json.JSONDecodeError:
                # Non-JSON line, might be raw text
                result_text.append(line)
        
        return {
            "text": "\n".join(result_text),
            "session_id": session_id,
            "usage": usage,
        }
    
    def _extract_from_json(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract relevant fields from parsed JSON."""
        text = (
            data.get("result") or
            data.get("response") or
            data.get("content") or
            data.get("text") or
            data.get("message") or
            ""
        )
        
        session_id = (
            data.get("session_id") or
            data.get("sessionId") or
            data.get("conversation_id") or
            data.get("conversationId") or
            None
        )
        
        usage = data.get("usage", {})
        
        return {
            "text": text,
            "session_id": session_id,
            "usage": usage,
        }
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
    
    def clear_session(self, session_key: str) -> None:
        """Clear stored session ID for a given key."""
        self._session_ids.pop(session_key, None)
    
    def get_session_id(self, session_key: str) -> str | None:
        """Get stored session ID for a given key."""
        return self._session_ids.get(session_key)
