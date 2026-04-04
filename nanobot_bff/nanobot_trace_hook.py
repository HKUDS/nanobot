"""Trajectory Modeling Hook for Nanobot Agent - Zero-invasion design.

Records (s, a, o, r) tuples for each agent iteration using Nanobot's AgentHook interface.

Based on fork_merge technical spec:
- Each branch = independent TraceModelHook instance
- Workspace isolation via branch_id subdirectory
- LRU management handled by LRUAgentManager (not here)
"""

import json
from typing import Any

from nanobot.agent.hook import AgentHook, AgentHookContext


class TraceModelHook(AgentHook):
    """Hook that captures (s, a, o, r) trajectory tuples for each agent iteration.

    This hook is completely independent of Nanobot core code - zero invasion.
    It hooks into the agent lifecycle via before_iteration/before_execute_tools/after_iteration
    to capture the full trajectory of each agent step.
    """

    def __init__(self, branch_id: str, task: str = "", available_tools: list[dict] = None):
        self.branch_id = branch_id
        self.task = task
        self.available_tools = available_tools or []

        self.s_t: dict[str, Any] = {}
        self.a_t: dict[str, Any] = {}
        self.o_t: dict[str, Any] = {}
        self.r_t: float = 0.0

        self._iteration_traces: list[dict[str, Any]] = []

    async def before_iteration(self, context: AgentHookContext) -> None:
        """Capture s_t: State before each iteration.

        Contains:
        - task: Current task objective
        - history_summary: Concatenated conversation history
        - tools: Available tool list (from tool_registry)
        - env: Environment info (model, branch, iteration)
        """
        messages = context.messages or []
        history_text = self._build_history_summary(messages)

        self.s_t = {
            "task": self.task,
            "history_summary": history_text,
            "tools": self.available_tools,
            "env": {
                "model": self._infer_model_from_messages(messages),
                "branch_id": self.branch_id,
                "iteration": context.iteration,
                "message_count": len(messages),
            }
        }

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """Capture a_t: Action - the LLM's decision (tool call or text reply).

        This is called after the LLM responds but before tool execution.
        If the response has tool_calls, that's the action.
        Otherwise, the text content is the action.
        """
        if context.tool_calls:
            self.a_t = {
                "type": "tool_call",
                "content": "",
                "tool_calls": [
                    {
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "id": tc.id,
                    }
                    for tc in context.tool_calls
                ]
            }
        else:
            self.a_t = {
                "type": "chat_reply",
                "content": context.response.content if context.response else "",
                "tool_calls": []
            }

    async def after_iteration(self, context: AgentHookContext) -> None:
        """Capture o_t and r_t, then save complete trajectory tuple.

        o_t: Observation - results from tool execution or final LLM response
        r_t: Reward - binary (1.0 success / 0.0 failure)
        """
        if context.tool_results:
            self.o_t = {
                "type": "tool_results",
                "stdout": "",
                "stderr": "",
                "results": [
                    self._serialize_tool_result(r)
                    for r in context.tool_results
                ],
                "source": "tools"
            }
        else:
            self.o_t = {
                "type": "final_response",
                "content": context.final_content or "",
                "error": context.error or "",
                "results": [],
                "source": "llm"
            }

        self.r_t = self._compute_reward(context)

        trace = {
            "iteration": context.iteration,
            "branch_id": self.branch_id,
            "s_t": self.s_t,
            "a_t": self.a_t,
            "o_t": self.o_t,
            "r_t": self.r_t,
        }

        self._iteration_traces.append(trace)

    def get_traces(self) -> list[dict[str, Any]]:
        """Return all captured traces for this branch."""
        return self._iteration_traces

    def clear_traces(self) -> None:
        """Clear all captured traces."""
        self._iteration_traces = []

    def _build_history_summary(self, messages: list[dict[str, Any]]) -> str:
        """Build history summary by concatenating messages (MVP approach)."""
        lines = []
        for msg in messages[-20:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            content = str(content)[:500]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _serialize_tool_result(self, result: Any) -> dict[str, Any]:
        """Serialize a tool execution result."""
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            return {"content": result[:2000]}
        return {"content": str(result)[:2000]}

    def _compute_reward(self, context: AgentHookContext) -> float:
        """Compute binary reward: 1.0 for success, 0.0 for failure.

        MVP uses simple binary reward. Can be extended with PRM/HIL later.
        """
        if context.error:
            return 0.0
        if context.stop_reason == "max_iterations":
            return 0.0
        if context.final_content:
            return 1.0
        return 1.0

    def _infer_model_from_messages(self, messages: list[dict[str, Any]]) -> str:
        """Try to infer model from message metadata or return default."""
        for msg in reversed(messages):
            if isinstance(msg, dict):
                if "model" in msg:
                    return msg["model"]
        return "unknown"
