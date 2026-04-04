"""Nanobot Agent Service - Integration layer between BFF and Nanobot core.

Based on fork_merge technical spec:
- Uses LRUAgentManager for global multi-agent management
- Each branch = independent Agent + TraceModelHook
- Maximum 10 active agents with LRU eviction
"""

import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Any

from nanobot.agent.runner import AgentRunSpec, AgentRunner
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.message import MessageTool
from nanobot.providers.openai_compat_provider import OpenAICompatProvider, set_current_session_config

from config import (
    DATA_DIR,
    DASHSCOPE_API_KEY,
    DEEPSEEK_API_KEY,
    MAX_ITERATIONS,
)
from database import Database
from nanobot_trace_hook import TraceModelHook
from nanobot_agent_manager import agent_manager


class AgentService:
    """Service layer for managing Nanobot agent interactions with trajectory modeling."""

    def __init__(self, db: Database):
        self.db = db
        self.active_providers: dict[int, OpenAICompatProvider] = {}
        self.conversation_messages: dict[int, list[dict[str, Any]]] = {}
        self.hook_cache: dict[str, TraceModelHook] = {}

    def _get_api_key_for_model(self, model: str) -> str:
        """Get the appropriate API key based on model name."""
        model_lower = model.lower()
        if "deepseek" in model_lower:
            return DEEPSEEK_API_KEY or "sk-b192d1bf26f740adace7d5f628656921"
        elif "qwen" in model_lower or "dashscope" in model_lower:
            return DASHSCOPE_API_KEY or "sk-91fe1c9c529b46bb88dc200a2e97b2b6"
        elif "kimi" in model_lower or "moonshot" in model_lower:
            return os.environ.get("KIMI_API_KEY", "")
        elif "minimax" in model_lower:
            return os.environ.get("MINIMAX_API_KEY", "")
        return DEEPSEEK_API_KEY or ""

    def _get_api_type_for_model(self, model: str) -> str:
        """Get the API type based on model name."""
        model_lower = model.lower()
        if "deepseek" in model_lower:
            return "deepseek"
        elif "qwen" in model_lower or "dashscope" in model_lower:
            return "qwen"
        elif "kimi" in model_lower or "moonshot" in model_lower:
            return "kimi"
        elif "minimax" in model_lower:
            return "minimax"
        return "deepseek"

    def _get_provider_for_model(self, model: str, conversation_id: int) -> OpenAICompatProvider:
        """Get or create an LLM provider for the specified model."""
        if conversation_id not in self.active_providers:
            api_key = self._get_api_key_for_model(model)
            provider = OpenAICompatProvider(api_key=api_key)
            self.active_providers[conversation_id] = provider
        return self.active_providers[conversation_id]

    def _create_tool_registry(self) -> ToolRegistry:
        """Create a tool registry with available tools."""
        registry = ToolRegistry()
        registry.register(WebSearchTool())
        registry.register(WebFetchTool())
        registry.register(MessageTool())
        return registry

    def _get_or_create_hook(self, branch_id: str, task: str = "", tools: list = None) -> TraceModelHook:
        """Get or create a TraceModelHook for the branch."""
        if branch_id in self.hook_cache:
            hook = self.hook_cache[branch_id]
            hook.task = task
            hook.available_tools = tools or []
            return hook

        hook = TraceModelHook(
            branch_id=branch_id,
            task=task,
            available_tools=tools or []
        )
        self.hook_cache[branch_id] = hook
        return hook

    async def _save_traces(self, conversation_id: int, branch_id: str, traces: list) -> None:
        """Save iteration traces to database."""
        for trace in traces:
            try:
                await self.db.save_trace(
                    conversation_id=conversation_id,
                    branch_id=branch_id,
                    iteration=trace["iteration"],
                    s_t=trace["s_t"],
                    a_t=trace["a_t"],
                    o_t=trace["o_t"],
                    r_t=trace["r_t"],
                )
            except Exception as e:
                print(f"Failed to save trace: {e}")

    async def create_conversation(self, title: str, model: str) -> int:
        """Create a new conversation with main branch."""
        conversation_id = await self.db.create_conversation(title, model)
        self.conversation_messages[conversation_id] = []

        main_branch_id = f"main_{conversation_id}"
        await self.db.create_branch(
            conversation_id=conversation_id,
            branch_id=main_branch_id,
            branch_name="main"
        )

        self._get_or_create_hook(main_branch_id, task=title)

        return conversation_id

    async def send_message(
        self,
        conversation_id: int,
        content: str,
        model: str | None = None
    ) -> dict[str, Any]:
        """Send a message to the agent and get a response with full trajectory data."""
        conversation = await self.db.get_conversation(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")

        model = model or conversation["model"]
        provider = self._get_provider_for_model(model, conversation_id)

        api_type = self._get_api_type_for_model(model)
        session_config = {
            "api_type": api_type,
            "api_key": self._get_api_key_for_model(model),
            "session_key": f"conv_{conversation_id}",
        }
        set_current_session_config(session_config)

        messages = self.conversation_messages.get(conversation_id, [])
        messages.append({"role": "user", "content": content})

        main_branch_id = f"main_{conversation_id}"

        turn_id = await self.db.get_conversation_turn_count(conversation_id) + 1

        tool_registry = self._create_tool_registry()
        tool_definitions = tool_registry.get_definitions()

        hook = self._get_or_create_hook(
            branch_id=main_branch_id,
            task=conversation.get("title", ""),
            tools=tool_definitions
        )

        spec = AgentRunSpec(
            initial_messages=list(messages),
            tools=tool_registry,
            model=model,
            max_iterations=MAX_ITERATIONS,
            hook=hook,
        )

        runner = AgentRunner(provider=provider)

        observation = ""
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        traces = []

        try:
            result = await runner.run(spec)

            observation = result.final_content or ""
            usage = result.usage

            messages.append({"role": "assistant", "content": observation})

            traces = hook.get_traces()
            hook.clear_traces()

            await self._save_traces(conversation_id, main_branch_id, traces)

        except Exception as e:
            observation = f"Error: {str(e)}"
            messages.append({"role": "assistant", "content": observation})
        finally:
            set_current_session_config(None)

        self.conversation_messages[conversation_id] = messages

        reward = 1.0

        await self.db.add_turn(
            conversation_id=conversation_id,
            turn_id=turn_id,
            state={
                "conversation_id": conversation_id,
                "model": model,
                "turn_count": len(messages) // 2,
                "last_updated": datetime.now().isoformat(),
            },
            action=content,
            observation=observation,
            reward=reward,
            usage=usage,
        )

        trajectory = {
            "turn_id": turn_id,
            "user_input": content,
            "agent_response": observation,
            "reward": reward,
            "timestamp": datetime.now().isoformat(),
            "iteration_traces": traces,
        }

        return {
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "content": observation,
            "trajectory": trajectory,
            "usage": usage,
            "iteration_count": len(traces),
        }

    async def get_conversation_history(self, conversation_id: int) -> list[dict]:
        """Get the full conversation history with trajectory data."""
        return await self.db.get_turns(conversation_id)

    async def get_traces(self, conversation_id: int, branch_id: str | None = None) -> list[dict]:
        """Get trajectory traces for a conversation."""
        return await self.db.get_traces(conversation_id, branch_id)

    async def get_branches(self, conversation_id: int) -> list[dict]:
        """Get all branches for a conversation."""
        return await self.db.get_branches(conversation_id)

    async def fork_branch(
        self,
        conversation_id: int,
        parent_branch_id: str,
        new_branch_name: str
    ) -> dict:
        """Fork a new branch from an existing branch."""
        new_branch_id = f"{new_branch_name}_{uuid.uuid4().hex[:8]}"

        await self.db.create_branch(
            conversation_id=conversation_id,
            branch_id=new_branch_id,
            branch_name=new_branch_name,
            parent_branch_id=parent_branch_id
        )

        await agent_manager.fork_agent(parent_branch_id, new_branch_id)

        self._get_or_create_hook(new_branch_id)

        return {
            "new_branch_id": new_branch_id,
            "parent_branch_id": parent_branch_id,
        }

    def get_active_agents(self) -> list:
        """Get list of active agent branch IDs."""
        return agent_manager.get_active_agents()

    async def list_conversations(self) -> list:
        """List all conversations."""
        return await self.db.list_conversations()
