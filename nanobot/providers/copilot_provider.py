"""GitHub Copilot provider using the Copilot SDK.

Requires: pip install github-copilot-sdk
Requires: GitHub Copilot CLI installed and authenticated (copilot --version)
"""

import json
import uuid
from typing import Any

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CopilotProvider(LLMProvider):
    """
    LLM provider using the GitHub Copilot SDK.

    Unlike LiteLLMProvider, this communicates with Copilot CLI via JSON-RPC
    rather than using OpenAI-compatible HTTP APIs through LiteLLM.

    The client is started lazily on first chat() call and reused across calls.
    Each chat() call creates a new session (stateless from the agent loop's
    perspective), matching the LLMProvider.chat() contract.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "gpt-4.1",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._client = None
        self._started = False

    async def _ensure_client(self):
        """Lazily start the Copilot client on first use."""
        if not self._started:
            try:
                from copilot import CopilotClient
            except ImportError:
                raise ImportError(
                    "github-copilot-sdk is required for the Copilot provider. "
                    "Install it with: pip install github-copilot-sdk"
                )

            self._client = CopilotClient()
            await self._client.start()
            self._started = True
        return self._client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a chat completion request via Copilot SDK.

        Creates a new session per call.  Tools are registered with intercepting
        handlers so that tool-call invocations are captured and returned in
        LLMResponse for the agent loop to execute.
        """
        try:
            client = await self._ensure_client()
        except ImportError as e:
            return LLMResponse(content=str(e), finish_reason="error")

        model = self._resolve_model(model or self.default_model)

        # Collect tool call invocations via handler callbacks
        tool_call_collector: list[dict[str, Any]] = []

        # Build session config
        session_config: dict[str, Any] = {"model": model}
        if tools:
            session_config["tools"] = self._convert_tools(tools, tool_call_collector)

        try:
            session = await client.create_session(session_config)
        except Exception as e:
            return LLMResponse(
                content=f"Error creating Copilot session: {e}",
                finish_reason="error",
            )

        # Collect response data from events
        response_content: str | None = None
        reasoning_content: str | None = None
        usage: dict[str, int] = {}

        def on_event(event):
            nonlocal response_content, reasoning_content, usage
            from copilot.generated.session_events import SessionEventType

            if event.type == SessionEventType.ASSISTANT_MESSAGE:
                response_content = event.data.content
            elif event.type == SessionEventType.ASSISTANT_REASONING:
                reasoning_content = getattr(event.data, "reasoning_text", None)
            elif event.type == SessionEventType.ASSISTANT_USAGE:
                usage = {
                    "prompt_tokens": int(getattr(event.data, "input_tokens", 0) or 0),
                    "completion_tokens": int(getattr(event.data, "output_tokens", 0) or 0),
                    "total_tokens": int((getattr(event.data, "input_tokens", 0) or 0)
                                       + (getattr(event.data, "output_tokens", 0) or 0)),
                }
            elif event.type == SessionEventType.SESSION_ERROR:
                msg = getattr(event.data, "message", None) or str(event.data)
                response_content = f"Copilot error: {msg}"

        session.on(on_event)

        prompt = self._messages_to_prompt(messages)

        try:
            await session.send_and_wait({"prompt": prompt})
        except Exception as e:
            return LLMResponse(
                content=f"Error calling Copilot: {e}",
                finish_reason="error",
            )

        # Build ToolCallRequest list from intercepted invocations
        parsed_tool_calls: list[ToolCallRequest] = []
        for tc in tool_call_collector:
            args = tc.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}
            parsed_tool_calls.append(
                ToolCallRequest(
                    id=tc.get("tool_call_id", f"copilot-{uuid.uuid4().hex[:12]}"),
                    name=tc["name"],
                    arguments=args,
                )
            )

        return LLMResponse(
            content=response_content,
            tool_calls=parsed_tool_calls,
            finish_reason="tool_calls" if parsed_tool_calls else "stop",
            usage=usage,
            reasoning_content=reasoning_content,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_model(self, model: str) -> str:
        """Strip 'copilot/' prefix if present."""
        if model.startswith("copilot/"):
            return model[len("copilot/"):]
        return model

    def _messages_to_prompt(self, messages: list[dict[str, Any]]) -> str:
        """Convert OpenAI-format message list to a single prompt string.

        The Copilot SDK accepts a prompt string, not a message array.  We
        serialise the full conversation into labelled blocks so the LLM can
        follow the multi-turn context.
        """
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                parts.append(f"[System]\n{content}")
            elif role == "user":
                parts.append(f"[User]\n{content}")
            elif role == "assistant":
                if content:
                    parts.append(f"[Assistant]\n{content}")
                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    parts.append(
                        f"[Tool Call: {func.get('name', '?')}]\n"
                        f"Arguments: {func.get('arguments', '{}')}"
                    )
            elif role == "tool":
                name = msg.get("name", "unknown")
                parts.append(f"[Tool Result: {name}]\n{content}")

        return "\n\n".join(parts)

    def _convert_tools(
        self,
        tools: list[dict[str, Any]],
        collector: list[dict[str, Any]],
    ) -> list:
        """Convert OpenAI-format tool schemas to Copilot SDK Tool objects.

        Each tool gets a handler that records the invocation in *collector*
        and returns a placeholder result.  Actual execution is done by the
        agent loop after chat() returns the tool calls.
        """
        from copilot import Tool

        copilot_tools = []
        for tool_def in tools:
            func = tool_def.get("function", {})
            name = func.get("name", "")
            description = func.get("description", "")
            parameters = func.get("parameters", {})

            # Handler receives ToolInvocation (TypedDict with arguments,
            # tool_name, tool_call_id, session_id).  We capture the
            # invocation and return a placeholder result so the SDK can
            # proceed to session.idle.
            def _handler(invocation, *, _name=name, _collector=collector):
                _collector.append({
                    "name": _name,
                    "arguments": invocation.get("arguments", {}),
                    "tool_call_id": invocation.get("tool_call_id", ""),
                })
                return {
                    "textResultForLlm": "[Tool execution deferred to agent]",
                    "resultType": "success",
                }

            copilot_tools.append(Tool(
                name=name,
                description=description,
                handler=_handler,
                parameters=parameters or None,
            ))

        return copilot_tools

    def get_default_model(self) -> str:
        return self.default_model

    async def cleanup(self) -> None:
        """Stop the Copilot client."""
        if self._client and self._started:
            await self._client.stop()
            self._started = False
