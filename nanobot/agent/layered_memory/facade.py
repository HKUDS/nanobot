"""分层记忆门面——loop/runner 集成的唯一入口点。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.layered_memory.l0_store import L0Store
from nanobot.agent.layered_memory.offload.canvas import TaskCanvas, format_canvas_runtime_lines
from nanobot.agent.layered_memory.sanitize import sanitize_turn_messages
from nanobot.agent.layered_memory.offload.node_registry import (
    NodeRegistry,
    summarize_tool_result,
    tool_result_char_len,
)
from nanobot.config.schema import LayeredMemoryConfig
from nanobot.providers.base import ToolCallRequest
from nanobot.utils.helpers import persist_path_from_tool_content


@dataclass(frozen=True)
class RecallResult:
    """在运行时/系统提示词中合并 turn 前回忆的载体。"""
    prepend_lines: list[str] = field(default_factory=list)  # 需要添加在消息前的历史片段
    append_system: str | None = None  # 附加到系统提示的内容（可选）


class LayeredMemoryFacade:
    """负责异步卸载（canvas）、消息捕获（L0）、回忆和流水线钩子的协调。

    LM0-C：如果配置未开启则直接空操作。LM1及以上由子模块具体实现。
    """

    __slots__ = ("_config", "_l0_store", "_offload_tool_counts", "_workspace")

    def __init__(self, workspace: Path, config: LayeredMemoryConfig | None = None) -> None:
        self._workspace = workspace
        self._config = config or LayeredMemoryConfig()
        self._offload_tool_counts: dict[str, int] = {}
        self._l0_store = L0Store(workspace)

    @property
    def workspace(self) -> Path:
        # 返回当前工作区路径
        return self._workspace

    @property
    def config(self) -> LayeredMemoryConfig:
        # 返回分层记忆配置对象
        return self._config

    @property
    def enabled(self) -> bool:
        """主开关（对应 layeredMemory.enable 配置）。"""
        return self._config.enable

    async def recall(
        self,
        query: str,
        session_key: str,
        *,
        is_subagent: bool = False,
    ) -> RecallResult:
        """build_messages 前进行 L1/L2/L3 回忆（LM2）。
        query: 查询关键词
        session_key: 会话标识
        is_subagent: 是否为子代理
        """
        if not self._config.recall_enabled(is_subagent=is_subagent):
            # 如果未开启回忆功能则直接返回空 RecallResult
            return RecallResult()
        _ = query, session_key  # 占位，避免未使用变量告警
        return RecallResult()

    def canvas_lines(self, session_key: str, *, is_subagent: bool = False) -> list[str]:
        """Runtime lines: ``[Task canvas]`` + Mermaid + node index (≤ ``max_canvas_chars``)."""
        if not self._config.offload_enabled(is_subagent=is_subagent):
            return []
        canvas = self._task_canvas(session_key)
        every_n = self._config.offload.update_canvas_every_n_tools
        refresh = every_n == 0 or not canvas.mmd_path.exists()
        mmd = canvas.read(refresh=refresh)
        nodes = canvas.registry.list_nodes()
        return format_canvas_runtime_lines(
            mmd,
            nodes,
            max_chars=self._config.offload.max_canvas_chars,
        )

    def refresh_canvas(self, session_key: str, *, is_subagent: bool = False) -> None:
        """Regenerate ``canvas.mmd`` (turn end or periodic tool refresh)."""
        if not self._config.offload_enabled(is_subagent=is_subagent):
            return
        self._task_canvas(session_key).refresh()

    async def capture_turn(
        self,
        session_key: str,
        new_messages: list[dict[str, Any]],
        *,
        turn_id: str | None = None,
        is_subagent: bool = False,
    ) -> None:
        """消息持久化 L0 片段，并在 _save_turn 后通知 pipeline（LM2-B）。"""
        if not self._config.capture_enabled(is_subagent=is_subagent):
            return
        if not session_key or not new_messages:
            return
        try:
            rows = sanitize_turn_messages(new_messages)
            if not rows:
                return
            inserted = await asyncio.to_thread(
                self._l0_store.append_messages,
                session_key,
                turn_id,
                rows,
            )
            retention = self._config.capture.l0_retention_days
            if retention > 0:
                await asyncio.to_thread(self._l0_store.prune_older_than_days, retention)
            logger.debug(
                "layered_memory l0_capture_done session={} inserted={}",
                session_key,
                inserted,
            )
        except Exception:
            logger.exception("layered_memory capture_turn failed for {}", session_key)

    def register_tool_result(
        self,
        *,
        session_key: str,
        node_id: str,
        tool_name: str,
        persist_path: str | None,
        summary: str,
        chars: int,
        is_subagent: bool = False,
    ) -> None:
        """工具运行结果注册节点，归一化/持久化后调用（LM1）。
        session_key: 会话标识
        node_id: 工具对应节点ID
        tool_name: 工具名称
        persist_path: 结果持久化路径（可选）
        summary: 工具运行结果摘要
        chars: 结果文本长度
        is_subagent: 是否为子代理
        """
        if not self._config.offload_enabled(is_subagent=is_subagent):
            return
        registry = NodeRegistry(
            self._workspace,
            session_key,
            max_summary_chars=self._config.offload.max_node_summary_chars,
        )
        registry.upsert(
            node_id=node_id,
            tool=tool_name,
            path=persist_path,
            summary=summary,
            chars=chars,
        )
        self._maybe_refresh_canvas_after_tool(session_key, is_subagent=is_subagent)

    def sync_tool_nodes(
        self,
        *,
        session_key: str,
        tool_calls: list[ToolCallRequest],
        tool_results: list[Any],
        is_subagent: bool = False,
    ) -> None:
        """Batch upsert nodes from hook (no periodic refresh counter)."""
        if not self._config.offload_enabled(is_subagent=is_subagent):
            return
        registry = NodeRegistry(
            self._workspace,
            session_key,
            max_summary_chars=self._config.offload.max_node_summary_chars,
        )
        max_summary = self._config.offload.max_node_summary_chars
        for tool_call, result in zip(tool_calls, tool_results, strict=False):
            if not tool_call.id:
                continue
            summary_source = result if isinstance(result, str) else str(result)
            summary = summarize_tool_result(summary_source, max_chars=max_summary) or tool_call.name
            registry.upsert(
                node_id=tool_call.id,
                tool=tool_call.name,
                path=persist_path_from_tool_content(result, workspace=self._workspace),
                summary=summary,
                chars=tool_result_char_len(result),
            )

    def _task_canvas(self, session_key: str) -> TaskCanvas:
        return TaskCanvas(
            self._workspace,
            session_key,
            max_summary_chars=self._config.offload.max_node_summary_chars,
        )

    def _maybe_refresh_canvas_after_tool(
        self,
        session_key: str,
        *,
        is_subagent: bool,
    ) -> None:
        every_n = self._config.offload.update_canvas_every_n_tools
        if every_n <= 0 or not self._config.offload_enabled(is_subagent=is_subagent):
            return
        count = self._offload_tool_counts.get(session_key, 0) + 1
        self._offload_tool_counts[session_key] = count
        if count % every_n == 0:
            self._task_canvas(session_key).refresh()
