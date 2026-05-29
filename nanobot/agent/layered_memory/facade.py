"""分层记忆门面——loop/runner 集成的唯一入口点。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.layered_memory.l0_store import L0Store
from nanobot.agent.layered_memory.l1_extractor import L1Extractor
from nanobot.agent.layered_memory.l1_store import L1Store
from nanobot.agent.layered_memory.obs import log_recall_result, log_recall_timeout
from nanobot.agent.layered_memory.offload.canvas import TaskCanvas, format_canvas_runtime_lines
from nanobot.agent.layered_memory.pipeline import L1JobHandler, L2JobHandler, L3JobHandler, MemoryPipelineManager
from nanobot.agent.layered_memory.recall import RecallResult, perform_recall
from nanobot.agent.layered_memory.persona.generator import PersonaGenerator
from nanobot.agent.layered_memory.scene.extractor import SceneExtractor
from nanobot.agent.layered_memory.sanitize import sanitize_turn_messages
from nanobot.agent.layered_memory.offload.node_registry import (
    NodeRegistry,
    summarize_tool_result,
    tool_result_char_len,
)
from nanobot.config.schema import LayeredMemoryConfig
from nanobot.providers.base import LLMProvider, ToolCallRequest
from nanobot.utils.helpers import persist_path_from_tool_content


class LayeredMemoryFacade:
    """负责异步卸载（canvas）、消息捕获（L0）、回忆和流水线钩子的协调。

    LM0-C：如果配置未开启则直接空操作。LM1及以上由子模块具体实现。
    """

    __slots__ = ("_config", "_l0_store", "_l1_store", "_offload_tool_counts", "_pipeline", "_workspace")

    def __init__(
        self,
        workspace: Path,
        config: LayeredMemoryConfig | None = None,
        *,
        provider: LLMProvider | None = None,
        l1_handler: L1JobHandler | None = None,
        l2_handler: L2JobHandler | None = None,
        l3_handler: L3JobHandler | None = None,
    ) -> None:
        self._workspace = workspace
        self._config = config or LayeredMemoryConfig()
        self._offload_tool_counts: dict[str, int] = {}
        self._l0_store = L0Store(workspace)
        self._l1_store = L1Store(workspace)
        handler = l1_handler
        scene_handler = l2_handler
        persona_handler = l3_handler
        if handler is None and provider is not None and self._config.enable:
            handler = L1Extractor(
                workspace,
                self._config,
                provider,
                l0_store=self._l0_store,
                l1_store=self._l1_store,
            ).run
        if scene_handler is None and provider is not None and self._config.enable:
            scene_handler = SceneExtractor(
                workspace,
                self._config,
                provider,
                l1_store=self._l1_store,
            ).run
        if persona_handler is None and provider is not None and self._config.enable:
            persona_handler = PersonaGenerator(
                workspace,
                self._config,
                provider,
                l1_store=self._l1_store,
            ).run
        self._pipeline = MemoryPipelineManager(
            self._config,
            l1_handler=handler,
            l2_handler=scene_handler,
            l3_handler=persona_handler,
        )

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

    async def runtime_lines(
        self,
        query: str,
        session_key: str,
        *,
        is_subagent: bool = False,
    ) -> list[str]:
        """Canvas + recall prepend lines for ``current_runtime_lines`` (LM2-F)."""
        lines = list(self.canvas_lines(session_key, is_subagent=is_subagent))
        recall = await self.recall(query, session_key, is_subagent=is_subagent)
        lines.extend(recall.prepend_lines)
        return lines

    async def recall(
        self,
        query: str,
        session_key: str,
        *,
        is_subagent: bool = False,
    ) -> RecallResult:
        """build_messages 前进行 L1/L3 回忆（LM2-D）。"""
        if not self._config.recall_enabled(is_subagent=is_subagent):
            return RecallResult()
        recall_cfg = self._config.recall
        timeout_s = recall_cfg.timeout_ms / 1000.0
        include_guide = self._config.capture_enabled(is_subagent=is_subagent)
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    perform_recall,
                    workspace=self._workspace,
                    config=recall_cfg,
                    query=query,
                    session_key=session_key,
                    l1_store=self._l1_store,
                    include_tools_guide=include_guide,
                ),
                timeout=timeout_s,
            )
        except TimeoutError:
            log_recall_timeout(
                session_key=session_key,
                strategy=recall_cfg.strategy,
                timeout_ms=recall_cfg.timeout_ms,
            )
            return RecallResult()
        except Exception:
            logger.exception("layered_memory recall failed session={}", session_key)
            return RecallResult()
        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
        if result.prepend_lines:
            hits = sum(1 for line in result.prepend_lines if line.startswith("- ("))
            chars = sum(len(line) for line in result.prepend_lines)
            log_recall_result(
                session_key=session_key,
                strategy=recall_cfg.strategy,
                hits=hits,
                elapsed_ms=elapsed_ms,
                chars=chars,
            )
        return result

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
            await self._pipeline.notify_turn(
                session_key,
                turn_id=turn_id,
                is_subagent=is_subagent,
            )
        except Exception:
            logger.exception("layered_memory capture_turn failed for {}", session_key)

    async def shutdown_pipeline(self) -> None:
        """Flush pending pipeline buffers (gateway shutdown)."""
        await self._pipeline.close()

    async def close(self) -> None:
        """Shutdown pipeline and release SQLite connections."""
        await self.shutdown_pipeline()
        self._l0_store.close()
        self._l1_store.close()

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
