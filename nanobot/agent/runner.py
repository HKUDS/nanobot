"""Shared execution loop for tool-using agents."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import inspect
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.utils.prompt_templates import render_template
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMProvider, ToolCallRequest
from nanobot.utils.helpers import (
    build_assistant_message,
    estimate_message_tokens,
    estimate_prompt_tokens_chain,
    find_legal_message_start,
    maybe_persist_tool_result,
    truncate_text,
)
from nanobot.utils.runtime import (
    EMPTY_FINAL_RESPONSE_MESSAGE,
    build_finalization_retry_message,
    build_length_recovery_message,
    ensure_nonempty_tool_result,
    is_blank_text,
    repeated_external_lookup_error,
)

# 默认错误消息 - 当LLM调用失败时返回给用户
_DEFAULT_ERROR_MESSAGE = "Sorry, I encountered an error calling the AI model."
# 模型错误占位符 - 当模型返回错误时用于持久化存储
_PERSISTED_MODEL_ERROR_PLACEHOLDER = "[Assistant reply unavailable due to model error.]"
# 最大空响应重试次数
_MAX_EMPTY_RETRIES = 2
# 最大长度恢复尝试次数
_MAX_LENGTH_RECOVERIES = 3
# 每轮最大注入消息数
_MAX_INJECTIONS_PER_TURN = 3
# 最大注入循环次数
_MAX_INJECTION_CYCLES = 5
# 截断历史的安全缓冲区（token数）
_SNIP_SAFETY_BUFFER = 1024
# 微压缩保留的最近消息数
_MICROCOMPACT_KEEP_RECENT = 10
# 微压缩的最小字符数阈值
_MICROCOMPACT_MIN_CHARS = 500
# 可压缩的工具列表（这些工具的结果可以被简化）
_COMPACTABLE_TOOLS = frozenset({
    "read_file", "exec", "grep", "glob",
    "web_search", "web_fetch", "list_dir",
})
# 缺失工具结果的后备内容
_BACKFILL_CONTENT = "[Tool result unavailable — call was interrupted or lost]"



# ============================================================================
# AgentRunSpec — 代理运行配置
# ============================================================================

@dataclass(slots=True)
class AgentRunSpec:
    """单次代理运行的配置参数
    
    这个数据类包含了运行一个代理所需的所有配置项：
    - 消息和工具定义
    - 模型参数
    - 迭代限制
    - 回调函数
    - 错误处理策略
    """

    initial_messages: list[dict[str, Any]]  # 初始消息列表（系统提示+历史）
    tools: ToolRegistry  # 工具注册表
    model: str  # 模型名称
    max_iterations: int  # 最大迭代次数
    max_tool_result_chars: int  # 工具结果最大字符数
    temperature: float | None = None  # 温度参数
    max_tokens: int | None = None  # 最大生成token数
    reasoning_effort: str | None = None  # 推理 effort (用于推理模型)
    hook: AgentHook | None = None  # 生命周期钩子
    error_message: str | None = _DEFAULT_ERROR_MESSAGE  # 自定义错误消息
    max_iterations_message: str | None = None  # 达到最大迭代时的消息
    concurrent_tools: bool = False  # 是否允许并发执行工具
    fail_on_tool_error: bool = False  # 工具错误是否终止运行
    workspace: Path | None = None  # 工作目录
    session_key: str | None = None  # 会话key
    context_window_tokens: int | None = None  # 上下文窗口大小
    context_block_limit: int | None = None  # 上下文块限制
    provider_retry_mode: str = "standard"  # 重试模式
    progress_callback: Any | None = None  # 进度回调
    retry_wait_callback: Any | None = None  # 重试等待回调
    checkpoint_callback: Any | None = None  # 检查点回调
    injection_callback: Any | None = None  # 消息注入回调


# ============================================================================
# AgentRunResult — 代理运行结果
# ============================================================================

@dataclass(slots=True)
class AgentRunResult:
    """共享代理运行的结果
    
    包含代理执行完成后的所有输出信息：
    - 最终响应内容
    - 完整的消息历史
    - 使用的工具列表
    - token使用统计
    - 停止原因
    - 错误信息
    - 工具事件日志
    """

    final_content: str | None  # 最终响应文本
    messages: list[dict[str, Any]]  # 完整消息列表
    tools_used: list[str] = field(default_factory=list)  # 使用过的工具列表
    usage: dict[str, int] = field(default_factory=dict)  # token使用统计
    stop_reason: str = "completed"  # 停止原因
    error: str | None = None  # 错误信息
    tool_events: list[dict[str, str]] = field(default_factory=list)  # 工具事件列表
    had_injections: bool = False  # 是否有注入消息


# ============================================================================
# AgentRunner — 代理运行器核心
# ============================================================================

class AgentRunner:
    """工具型LLM代理的执行循环（不含产品层逻辑）
    
    这是nanobot的核心执行引擎，负责：
    1. 与LLM provider交互
    2. 执行工具调用
    3. 管理消息上下文
    4. 处理各种异常情况（空响应、长度限制、工具错误等）
    5. 支持生命周期钩子
    
    核心循环流程：
    1. 准备消息（上下文治理：压缩、截断等）
    2. 调用LLM获取响应
    3. 如果有工具调用，执行工具
    4. 检查是否需要继续（注入、空响应恢复等）
    5. 返回最终结果
    """

    def __init__(self, provider: LLMProvider):
        """初始化运行器
        
        Args:
            provider: LLM provider实例
        """
        self.provider = provider

    @staticmethod
    def _merge_message_content(left: Any, right: Any) -> str | list[dict[str, Any]]:
        """合并两条消息内容
        
        用于合并连续的角色相同的消息。
        如果两边都是字符串，直接拼接；否则转换为消息块后合并。
        
        Args:
            left: 左侧消息内容
            right: 右侧消息内容
            
        Returns:
            合并后的消息内容
        """
        if isinstance(left, str) and isinstance(right, str):
            return f"{left}\n\n{right}" if left else right

        def _to_blocks(value: Any) -> list[dict[str, Any]]:
            if isinstance(value, list):
                return [
                    item if isinstance(item, dict) else {"type": "text", "text": str(item)}
                    for item in value
                ]
            if value is None:
                return []
            return [{"type": "text", "text": str(value)}]

        return _to_blocks(left) + _to_blocks(right)

    @classmethod
    def _append_injected_messages(
        cls,
        messages: list[dict[str, Any]],
        injections: list[dict[str, Any]],
    ) -> None:
        """追加注入的用户消息，同时保持角色交替
        
        如果最后一条消息和注入消息都是user角色，合并内容；
        否则作为新消息追加。
        
        Args:
            messages: 消息列表
            injections: 要注入的消息列表
        """
        for injection in injections:
            if (
                messages
                and injection.get("role") == "user"
                and messages[-1].get("role") == "user"
            ):
                merged = dict(messages[-1])
                merged["content"] = cls._merge_message_content(
                    merged.get("content"),
                    injection.get("content"),
                )
                messages[-1] = merged
                continue
            messages.append(injection)

    async def _try_drain_injections(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
        assistant_message: dict[str, Any] | None,
        injection_cycles: int,
        *,
        phase: str = "after error",
        iteration: int | None = None,
    ) -> tuple[bool, int]:
        """处理待注入的消息
        
        如果有待注入的消息且未超过最大循环次数，
        将其追加到消息列表并返回继续标志。
        
        Args:
            spec: 运行配置
            messages: 消息列表
            assistant_message: 助手消息（可选）
            injection_cycles: 当前注入循环次数
            phase: 当前阶段名称（用于日志）
            iteration: 当前迭代次数
            
        Returns:
            (是否继续, 更新后的循环次数)
        """
        if injection_cycles >= _MAX_INJECTION_CYCLES:
            return False, injection_cycles
        injections = await self._drain_injections(spec)
        if not injections:
            return False, injection_cycles
        injection_cycles += 1
        if assistant_message is not None:
            messages.append(assistant_message)
            if iteration is not None:
                await self._emit_checkpoint(
                    spec,
                    {
                        "phase": "final_response",
                        "iteration": iteration,
                        "model": spec.model,
                        "assistant_message": assistant_message,
                        "completed_tool_results": [],
                        "pending_tool_calls": [],
                    },
                )
        self._append_injected_messages(messages, injections)
        logger.info(
            "Injected {} follow-up message(s) {} ({}/{})",
            len(injections), phase, injection_cycles, _MAX_INJECTION_CYCLES,
        )
        return True, injection_cycles

    async def _drain_injections(self, spec: AgentRunSpec) -> list[dict[str, Any]]:
        """通过注入回调获取待处理的用户消息
        
        从injection_callback获取待注入的消息，
        规范化后返回（最多_MAX_INJECTIONS_PER_TURN条）。
        
        Args:
            spec: 运行配置
            
        Returns:
            规范化的用户消息列表
        """
        if spec.injection_callback is None:
            return []
        try:
            signature = inspect.signature(spec.injection_callback)
            accepts_limit = (
                "limit" in signature.parameters
                or any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in signature.parameters.values()
                )
            )
            if accepts_limit:
                items = await spec.injection_callback(limit=_MAX_INJECTIONS_PER_TURN)
            else:
                items = await spec.injection_callback()
        except Exception:
            logger.exception("injection_callback failed")
            return []
        if not items:
            return []
        injected_messages: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict) and item.get("role") == "user" and "content" in item:
                injected_messages.append(item)
                continue
            text = getattr(item, "content", str(item))
            if text.strip():
                injected_messages.append({"role": "user", "content": text})
        if len(injected_messages) > _MAX_INJECTIONS_PER_TURN:
            dropped = len(injected_messages) - _MAX_INJECTIONS_PER_TURN
            logger.warning(
                "Injection callback returned {} messages, capping to {} ({} dropped)",
                len(injected_messages), _MAX_INJECTIONS_PER_TURN, dropped,
            )
            injected_messages = injected_messages[:_MAX_INJECTIONS_PER_TURN]
        return injected_messages

    async def run(self, spec: AgentRunSpec) -> AgentRunResult:
        """运行代理主循环
        
        这是核心执行方法，包含完整的代理循环逻辑：
        1. 迭代准备：上下文治理（清理、压缩、截断）
        2. LLM请求：调用模型获取响应
        3. 工具执行：如果有工具调用则执行
        4. 错误处理：空响应恢复、长度恢复、工具错误处理
        5. 注入处理：处理待注入的消息
        6. 钩子调用：在各个阶段调用生命周期钩子
        
        Args:
            spec: 运行配置
            
        Returns:
            代理运行结果
        """
        hook = spec.hook or AgentHook()
        messages = list(spec.initial_messages)
        final_content: str | None = None
        tools_used: list[str] = []
        usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
        error: str | None = None
        stop_reason = "completed"
        tool_events: list[dict[str, str]] = []
        external_lookup_counts: dict[str, int] = {}
        empty_content_retries = 0
        length_recovery_count = 0
        had_injections = False
        injection_cycles = 0

        for iteration in range(spec.max_iterations):
            try:
                # 保持持久化对话不变。上下文治理可能修复或压缩历史消息，
                # 但这些合成编辑不能改变追加边界（调用者保存新回合时使用）
                messages_for_model = self._drop_orphan_tool_results(messages)
                messages_for_model = self._backfill_missing_tool_results(messages_for_model)
                messages_for_model = self._microcompact(messages_for_model)
                messages_for_model = self._apply_tool_result_budget(spec, messages_for_model)
                messages_for_model = self._snip_history(spec, messages_for_model)
                # 截断可能产生新的孤立结果，清理它们
                messages_for_model = self._drop_orphan_tool_results(messages_for_model)
                messages_for_model = self._backfill_missing_tool_results(messages_for_model)
            except Exception as exc:
                logger.warning(
                    "Context governance failed on turn {} for {}: {}; applying minimal repair",
                    iteration,
                    spec.session_key or "default",
                    exc,
                )
                try:
                    messages_for_model = self._drop_orphan_tool_results(messages)
                    messages_for_model = self._backfill_missing_tool_results(messages_for_model)
                except Exception:
                    messages_for_model = messages
            
            # 创建钩子上下文并调用 before_iteration
            context = AgentHookContext(iteration=iteration, messages=messages)
            await hook.before_iteration(context)
            
            # 调用LLM获取响应
            response = await self._request_model(spec, messages_for_model, hook, context)
            raw_usage = self._usage_dict(response.usage)
            context.response = response
            context.usage = dict(raw_usage)
            context.tool_calls = list(response.tool_calls)
            self._accumulate_usage(usage, raw_usage)

            # 如果需要执行工具
            if response.should_execute_tools:
                if hook.wants_streaming():
                    await hook.on_stream_end(context, resuming=True)

                # 构建助手消息（包含工具调用）
                assistant_message = build_assistant_message(
                    response.content or "",
                    tool_calls=[tc.to_openai_tool_call() for tc in response.tool_calls],
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                messages.append(assistant_message)
                tools_used.extend(tc.name for tc in response.tool_calls)
                await self._emit_checkpoint(
                    spec,
                    {
                        "phase": "awaiting_tools",
                        "iteration": iteration,
                        "model": spec.model,
                        "assistant_message": assistant_message,
                        "completed_tool_results": [],
                        "pending_tool_calls": [tc.to_openai_tool_call() for tc in response.tool_calls],
                    },
                )

                await hook.before_execute_tools(context)

                # 执行工具
                results, new_events, fatal_error = await self._execute_tools(
                    spec,
                    response.tool_calls,
                    external_lookup_counts,
                )
                tool_events.extend(new_events)
                context.tool_results = list(results)
                context.tool_events = list(new_events)
                completed_tool_results: list[dict[str, Any]] = []
                for tool_call, result in zip(response.tool_calls, results):
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": self._normalize_tool_result(
                            spec,
                            tool_call.id,
                            tool_call.name,
                            result,
                        ),
                    }
                    messages.append(tool_message)
                    completed_tool_results.append(tool_message)
                
                # 处理工具执行错误
                if fatal_error is not None:
                    error = f"Error: {type(fatal_error).__name__}: {fatal_error}"
                    final_content = error
                    stop_reason = "tool_error"
                    self._append_final_message(messages, final_content)
                    context.final_content = final_content
                    context.error = error
                    context.stop_reason = stop_reason
                    await hook.after_iteration(context)
                    should_continue, injection_cycles = await self._try_drain_injections(
                        spec, messages, None, injection_cycles,
                        phase="after tool error",
                    )
                    if should_continue:
                        had_injections = True
                        continue
                    break

                await self._emit_checkpoint(
                    spec,
                    {
                        "phase": "tools_completed",
                        "iteration": iteration,
                        "model": spec.model,
                        "assistant_message": assistant_message,
                        "completed_tool_results": completed_tool_results,
                        "pending_tool_calls": [],
                    },
                )
                empty_content_retries = 0
                length_recovery_count = 0
                # 检查点1：工具执行后、下一轮LLM调用前排出注入
                _drained, injection_cycles = await self._try_drain_injections(
                    spec, messages, None, injection_cycles,
                    phase="after tool execution",
                )
                if _drained:
                    had_injections = True
                await hook.after_iteration(context)
                continue

            # 如果有工具调用但finish_reason不允许执行
            if response.has_tool_calls:
                logger.warning(
                    "Ignoring tool calls under finish_reason='{}' for {}",
                    response.finish_reason,
                    spec.session_key or "default",
                )

            # 最终内容处理（钩子）
            clean = hook.finalize_content(context, response.content)
            
            # 处理空响应
            if response.finish_reason != "error" and is_blank_text(clean):
                empty_content_retries += 1
                if empty_content_retries < _MAX_EMPTY_RETRIES:
                    logger.warning(
                        "Empty response on turn {} for {} ({}/{}); retrying",
                        iteration,
                        spec.session_key or "default",
                        empty_content_retries,
                        _MAX_EMPTY_RETRIES,
                    )
                    if hook.wants_streaming():
                        await hook.on_stream_end(context, resuming=False)
                    await hook.after_iteration(context)
                    continue
                logger.warning(
                    "Empty response on turn {} for {} after {} retries; attempting finalization",
                    iteration,
                    spec.session_key or "default",
                    empty_content_retries,
                )
                if hook.wants_streaming():
                    await hook.on_stream_end(context, resuming=False)
                # 请求最终化重试
                response = await self._request_finalization_retry(spec, messages_for_model)
                retry_usage = self._usage_dict(response.usage)
                self._accumulate_usage(usage, retry_usage)
                raw_usage = self._merge_usage(raw_usage, retry_usage)
                context.response = response
                context.usage = dict(raw_usage)
                context.tool_calls = list(response.tool_calls)
                clean = hook.finalize_content(context, response.content)

            # 处理输出截断（长度限制）
            if response.finish_reason == "length" and not is_blank_text(clean):
                length_recovery_count += 1
                if length_recovery_count <= _MAX_LENGTH_RECOVERIES:
                    logger.info(
                        "Output truncated on turn {} for {} ({}/{}); continuing",
                        iteration,
                        spec.session_key or "default",
                        length_recovery_count,
                        _MAX_LENGTH_RECOVERIES,
                    )
                    if hook.wants_streaming():
                        await hook.on_stream_end(context, resuming=True)
                    messages.append(build_assistant_message(
                        clean,
                        reasoning_content=response.reasoning_content,
                        thinking_blocks=response.thinking_blocks,
                    ))
                    # 添加长度恢复消息让模型继续
                    messages.append(build_length_recovery_message())
                    await hook.after_iteration(context)
                    continue

            # 构建助手消息
            assistant_message: dict[str, Any] | None = None
            if response.finish_reason != "error" and not is_blank_text(clean):
                assistant_message = build_assistant_message(
                    clean,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

            # 检查注入（在流结束前）
            should_continue, injection_cycles = await self._try_drain_injections(
                spec, messages, assistant_message, injection_cycles,
                phase="after final response",
                iteration=iteration,
            )
            if should_continue:
                had_injections = True

            if hook.wants_streaming():
                await hook.on_stream_end(context, resuming=should_continue)

            if should_continue:
                await hook.after_iteration(context)
                continue

            # 处理LLM错误
            if response.finish_reason == "error":
                final_content = clean or spec.error_message or _DEFAULT_ERROR_MESSAGE
                stop_reason = "error"
                error = final_content
                self._append_model_error_placeholder(messages)
                context.final_content = final_content
                context.error = error
                context.stop_reason = stop_reason
                await hook.after_iteration(context)
                should_continue, injection_cycles = await self._try_drain_injections(
                    spec, messages, None, injection_cycles,
                    phase="after LLM error",
                )
                if should_continue:
                    had_injections = True
                    continue
                break
            
            # 处理空最终响应
            if is_blank_text(clean):
                final_content = EMPTY_FINAL_RESPONSE_MESSAGE
                stop_reason = "empty_final_response"
                error = final_content
                self._append_final_message(messages, final_content)
                context.final_content = final_content
                context.error = error
                context.stop_reason = stop_reason
                await hook.after_iteration(context)
                should_continue, injection_cycles = await self._try_drain_injections(
                    spec, messages, None, injection_cycles,
                    phase="after empty response",
                )
                if should_continue:
                    had_injections = True
                    continue
                break

            # 正常完成，添加助手消息
            messages.append(assistant_message or build_assistant_message(
                clean,
                reasoning_content=response.reasoning_content,
                thinking_blocks=response.thinking_blocks,
            ))
            await self._emit_checkpoint(
                spec,
                {
                    "phase": "final_response",
                    "iteration": iteration,
                    "model": spec.model,
                    "assistant_message": messages[-1],
                    "completed_tool_results": [],
                    "pending_tool_calls": [],
                },
            )
            final_content = clean
            context.final_content = final_content
            context.stop_reason = stop_reason
            await hook.after_iteration(context)
            break
        else:
            # 达到最大迭代次数
            stop_reason = "max_iterations"
            if spec.max_iterations_message:
                final_content = spec.max_iterations_message.format(
                    max_iterations=spec.max_iterations,
                )
            else:
                final_content = render_template(
                    "agent/max_iterations_message.md",
                    strip=True,
                    max_iterations=spec.max_iterations,
                )
            self._append_final_message(messages, final_content)
            # 排出剩余注入
            drained_after_max_iterations, injection_cycles = await self._try_drain_injections(
                spec, messages, None, injection_cycles,
                phase="after max_iterations",
            )
            if drained_after_max_iterations:
                had_injections = True

        return AgentRunResult(
            final_content=final_content,
            messages=messages,
            tools_used=tools_used,
            usage=usage,
            stop_reason=stop_reason,
            error=error,
            tool_events=tool_events,
            had_injections=had_injections,
        )

    def _build_request_kwargs(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """构建LLM请求参数
        
        根据spec配置构建完整的请求参数字典。
        
        Args:
            spec: 运行配置
            messages: 消息列表
            tools: 工具定义列表
            
        Returns:
            请求参数字典
        """
        kwargs: dict[str, Any] = {
            "messages": messages,
            "tools": tools,
            "model": spec.model,
            "retry_mode": spec.provider_retry_mode,
            "on_retry_wait": spec.retry_wait_callback,
        }
        if spec.temperature is not None:
            kwargs["temperature"] = spec.temperature
        if spec.max_tokens is not None:
            kwargs["max_tokens"] = spec.max_tokens
        if spec.reasoning_effort is not None:
            kwargs["reasoning_effort"] = spec.reasoning_effort
        return kwargs

    async def _request_model(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
        hook: AgentHook,
        context: AgentHookContext,
    ):
        """请求LLM获取响应
        
        根据hook是否需要流式输出，选择流式或非流式调用。
        
        Args:
            spec: 运行配置
            messages: 消息列表
            hook: 钩子实例
            context: 钩子上下文
            
        Returns:
            LLM响应对象
        """
        kwargs = self._build_request_kwargs(
            spec,
            messages,
            tools=spec.tools.get_definitions(),
        )
        if hook.wants_streaming():
            async def _stream(delta: str) -> None:
                await hook.on_stream(context, delta)

            return await self.provider.chat_stream_with_retry(
                **kwargs,
                on_content_delta=_stream,
            )
        return await self.provider.chat_with_retry(**kwargs)

    async def _request_finalization_retry(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
    ):
        """请求最终化重试（用于空响应恢复）
        
        当LLM返回空响应时，添加特殊消息请求模型生成最终响应。
        
        Args:
            spec: 运行配置
            messages: 消息列表
            
        Returns:
            LLM响应对象
        """
        retry_messages = list(messages)
        retry_messages.append(build_finalization_retry_message())
        kwargs = self._build_request_kwargs(spec, retry_messages, tools=None)
        return await self.provider.chat_with_retry(**kwargs)

    @staticmethod
    def _usage_dict(usage: dict[str, Any] | None) -> dict[str, int]:
        """转换usage为整数字典
        
        Args:
            usage: 原始usage字典
            
        Returns:
            整数类型的usage字典
        """
        if not usage:
            return {}
        result: dict[str, int] = {}
        for key, value in usage.items():
            try:
                result[key] = int(value or 0)
            except (TypeError, ValueError):
                continue
        return result

    @staticmethod
    def _accumulate_usage(target: dict[str, int], addition: dict[str, int]) -> None:
        """累加usage到目标字典
        
        Args:
            target: 目标字典
            addition: 要累加的字典
        """
        for key, value in addition.items():
            target[key] = target.get(key, 0) + value

    @staticmethod
    def _merge_usage(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
        """合并两个usage字典
        
        Args:
            left: 左侧字典
            right: 右侧字典
            
        Returns:
            合并后的字典
        """
        merged = dict(left)
        for key, value in right.items():
            merged[key] = merged.get(key, 0) + value
        return merged

    async def _execute_tools(
        self,
        spec: AgentRunSpec,
        tool_calls: list[ToolCallRequest],
        external_lookup_counts: dict[str, int],
    ) -> tuple[list[Any], list[dict[str, str]], BaseException | None]:
        """执行工具调用
        
        将工具调用分成批次执行（如果允许并发）。
        
        Args:
            spec: 运行配置
            tool_calls: 工具调用请求列表
            external_lookup_counts: 外部查找计数（用于防止重复请求）
            
        Returns:
            (结果列表, 事件列表, 致命错误)
        """
        batches = self._partition_tool_batches(spec, tool_calls)
        tool_results: list[tuple[Any, dict[str, str], BaseException | None]] = []
        for batch in batches:
            if spec.concurrent_tools and len(batch) > 1:
                tool_results.extend(await asyncio.gather(*(
                    self._run_tool(spec, tool_call, external_lookup_counts)
                    for tool_call in batch
                )))
            else:
                for tool_call in batch:
                    tool_results.append(await self._run_tool(spec, tool_call, external_lookup_counts))

        results: list[Any] = []
        events: list[dict[str, str]] = []
        fatal_error: BaseException | None = None
        for result, event, error in tool_results:
            results.append(result)
            events.append(event)
            if error is not None and fatal_error is None:
                fatal_error = error
        return results, events, fatal_error

    async def _run_tool(
        self,
        spec: AgentRunSpec,
        tool_call: ToolCallRequest,
        external_lookup_counts: dict[str, int],
    ) -> tuple[Any, dict[str, str], BaseException | None]:
        """运行单个工具
        
        执行工具调用，处理各种错误情况。
        
        Args:
            spec: 运行配置
            tool_call: 工具调用请求
            external_lookup_counts: 外部查找计数
            
        Returns:
            (结果, 事件, 错误)
        """
        _HINT = "\n\n[Analyze the error above and try a different approach.]"
        # 检查重复的外部查找
        lookup_error = repeated_external_lookup_error(
            tool_call.name,
            tool_call.arguments,
            external_lookup_counts,
        )
        if lookup_error:
            event = {
                "name": tool_call.name,
                "status": "error",
                "detail": "repeated external lookup blocked",
            }
            if spec.fail_on_tool_error:
                return lookup_error + _HINT, event, RuntimeError(lookup_error)
            return lookup_error + _HINT, event, None
        
        # 准备工具调用
        prepare_call = getattr(spec.tools, "prepare_call", None)
        tool, params, prep_error = None, tool_call.arguments, None
        if callable(prepare_call):
            try:
                prepared = prepare_call(tool_call.name, tool_call.arguments)
                if isinstance(prepared, tuple) and len(prepared) == 3:
                    tool, params, prep_error = prepared
            except Exception:
                pass
        if prep_error:
            event = {
                "name": tool_call.name,
                "status": "error",
                "detail": prep_error.split(": ", 1)[-1][:120],
            }
            return prep_error + _HINT, event, RuntimeError(prep_error) if spec.fail_on_tool_error else None
        
        # 执行工具
        try:
            if tool is not None:
                result = await tool.execute(**params)
            else:
                result = await spec.tools.execute(tool_call.name, params)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            event = {
                "name": tool_call.name,
                "status": "error",
                "detail": str(exc),
            }
            if spec.fail_on_tool_error:
                return f"Error: {type(exc).__name__}: {exc}", event, exc
            return f"Error: {type(exc).__name__}: {exc}", event, None

        # 处理错误结果
        if isinstance(result, str) and result.startswith("Error"):
            event = {
                "name": tool_call.name,
                "status": "error",
                "detail": result.replace("\n", " ").strip()[:120],
            }
            if spec.fail_on_tool_error:
                return result + _HINT, event, RuntimeError(result)
            return result + _HINT, event, None

        # 构建成功事件
        detail = "" if result is None else str(result)
        detail = detail.replace("\n", " ").strip()
        if not detail:
            detail = "(empty)"
        elif len(detail) > 120:
            detail = detail[:120] + "..."
        return result, {"name": tool_call.name, "status": "ok", "detail": detail}, None

    async def _emit_checkpoint(
        self,
        spec: AgentRunSpec,
        payload: dict[str, Any],
    ) -> None:
        """发出检查点事件
        
        如果配置了checkpoint_callback，调用它。
        
        Args:
            spec: 运行配置
            payload: 检查点数据
        """
        callback = spec.checkpoint_callback
        if callback is not None:
            await callback(payload)

    @staticmethod
    def _append_final_message(messages: list[dict[str, Any]], content: str | None) -> None:
        """追加最终消息到列表
        
        如果最后一条是assistant消息且没有tool_calls，替换内容；
        否则追加新消息。
        
        Args:
            messages: 消息列表
            content: 消息内容
        """
        if not content:
            return
        if (
            messages
            and messages[-1].get("role") == "assistant"
            and not messages[-1].get("tool_calls")
        ):
            if messages[-1].get("content") == content:
                return
            messages[-1] = build_assistant_message(content)
            return
        messages.append(build_assistant_message(content))

    @staticmethod
    def _append_model_error_placeholder(messages: list[dict[str, Any]]) -> None:
        """追加模型错误占位符
        
        Args:
            messages: 消息列表
        """
        if messages and messages[-1].get("role") == "assistant" and not messages[-1].get("tool_calls"):
            return
        messages.append(build_assistant_message(_PERSISTED_MODEL_ERROR_PLACEHOLDER))

    def _normalize_tool_result(
        self,
        spec: AgentRunSpec,
        tool_call_id: str,
        tool_name: str,
        result: Any,
    ) -> Any:
        """规范化工具结果
        
        确保结果非空，可能持久化到文件，并截断过长结果。
        
        Args:
            spec: 运行配置
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            result: 原始结果
            
        Returns:
            规范化后的结果
        """
        result = ensure_nonempty_tool_result(tool_name, result)
        try:
            content = maybe_persist_tool_result(
                spec.workspace,
                spec.session_key,
                tool_call_id,
                result,
                max_chars=spec.max_tool_result_chars,
            )
        except Exception as exc:
            logger.warning(
                "Tool result persist failed for {} in {}: {}; using raw result",
                tool_call_id,
                spec.session_key or "default",
                exc,
            )
            content = result
        if isinstance(content, str) and len(content) > spec.max_tool_result_chars:
            return truncate_text(content, spec.max_tool_result_chars)
        return content

    @staticmethod
    def _drop_orphan_tool_results(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """删除孤立的工具结果
        
        移除没有对应assistant消息的tool结果。
        
        Args:
            messages: 消息列表
            
        Returns:
            清理后的消息列表
        """
        declared: set[str] = set()
        updated: list[dict[str, Any]] | None = None
        for idx, msg in enumerate(messages):
            role = msg.get("role")
            if role == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict) and tc.get("id"):
                        declared.add(str(tc["id"]))
            if role == "tool":
                tid = msg.get("tool_call_id")
                if tid and str(tid) not in declared:
                    if updated is None:
                        updated = [dict(m) for m in messages[:idx]]
                    continue
            if updated is not None:
                updated.append(dict(msg))

        if updated is None:
            return messages
        return updated

    @staticmethod
    def _backfill_missing_tool_results(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """为孤立的tool_use块插入合成的错误结果
        
        如果assistant消息声明了工具调用但没有对应结果，
        插入一个错误结果占位。
        
        Args:
            messages: 消息列表
            
        Returns:
            处理后的消息列表
        """
        declared: list[tuple[int, str, str]] = []  # (assistant_idx, call_id, name)
        fulfilled: set[str] = set()
        for idx, msg in enumerate(messages):
            role = msg.get("role")
            if role == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict) and tc.get("id"):
                        name = ""
                        func = tc.get("function")
                        if isinstance(func, dict):
                            name = func.get("name", "")
                        declared.append((idx, str(tc["id"]), name))
            elif role == "tool":
                tid = msg.get("tool_call_id")
                if tid:
                    fulfilled.add(str(tid))

        missing = [(ai, cid, name) for ai, cid, name in declared if cid not in fulfilled]
        if not missing:
            return messages

        updated = list(messages)
        offset = 0
        for assistant_idx, call_id, name in missing:
            insert_at = assistant_idx + 1 + offset
            while insert_at < len(updated) and updated[insert_at].get("role") == "tool":
                insert_at += 1
            updated.insert(insert_at, {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": _BACKFILL_CONTENT,
            })
            offset += 1
        return updated

    @staticmethod
    def _microcompact(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """用单行摘要替换旧的可压缩工具结果
        
        减少长工具输出占用的上下文空间。
        
        Args:
            messages: 消息列表
            
        Returns:
            处理后的消息列表
        """
        compactable_indices: list[int] = []
        for idx, msg in enumerate(messages):
            if msg.get("role") == "tool" and msg.get("name") in _COMPACTABLE_TOOLS:
                compactable_indices.append(idx)

        if len(compactable_indices) <= _MICROCOMPACT_KEEP_RECENT:
            return messages

        stale = compactable_indices[: len(compactable_indices) - _MICROCOMPACT_KEEP_RECENT]
        updated: list[dict[str, Any]] | None = None
        for idx in stale:
            msg = messages[idx]
            content = msg.get("content")
            if not isinstance(content, str) or len(content) < _MICROCOMPACT_MIN_CHARS:
                continue
            name = msg.get("name", "tool")
            summary = f"[{name} result omitted from context]"
            if updated is None:
                updated = [dict(m) for m in messages]
            updated[idx]["content"] = summary

        return updated if updated is not None else messages

    def _apply_tool_result_budget(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """应用工具结果预算限制
        
        规范化所有工具结果，确保不超过限制。
        
        Args:
            spec: 运行配置
            messages: 消息列表
            
        Returns:
            处理后的消息列表
        """
        updated = messages
        for idx, message in enumerate(messages):
            if message.get("role") != "tool":
                continue
            normalized = self._normalize_tool_result(
                spec,
                str(message.get("tool_call_id") or f"tool_{idx}"),
                str(message.get("name") or "tool"),
                message.get("content"),
            )
            if normalized != message.get("content"):
                if updated is messages:
                    updated = [dict(m) for m in messages]
                updated[idx]["content"] = normalized
        return updated

    def _snip_history(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """截断历史消息以适应上下文窗口
        
        如果消息超过上下文窗口限制，从后向前保留消息，
        直到满足预算。
        
        Args:
            spec: 运行配置
            messages: 消息列表
            
        Returns:
            截断后的消息列表
        """
        if not messages or not spec.context_window_tokens:
            return messages

        provider_max_tokens = getattr(getattr(self.provider, "generation", None), "max_tokens", 4096)
        max_output = spec.max_tokens if isinstance(spec.max_tokens, int) else (
            provider_max_tokens if isinstance(provider_max_tokens, int) else 4096
        )
        budget = spec.context_block_limit or (
            spec.context_window_tokens - max_output - _SNIP_SAFETY_BUFFER
        )
        if budget <= 0:
            return messages

        estimate, _ = estimate_prompt_tokens_chain(
            self.provider,
            spec.model,
            messages,
            spec.tools.get_definitions(),
        )
        if estimate <= budget:
            return messages

        system_messages = [dict(msg) for msg in messages if msg.get("role") == "system"]
        non_system = [dict(msg) for msg in messages if msg.get("role") != "system"]
        if not non_system:
            return messages

        system_tokens = sum(estimate_message_tokens(msg) for msg in system_messages)
        remaining_budget = max(128, budget - system_tokens)
        kept: list[dict[str, Any]] = []
        kept_tokens = 0
        for message in reversed(non_system):
            msg_tokens = estimate_message_tokens(message)
            if kept and kept_tokens + msg_tokens > remaining_budget:
                break
            kept.append(message)
            kept_tokens += msg_tokens
        kept.reverse()

        if kept:
            for i, message in enumerate(kept):
                if message.get("role") == "user":
                    kept = kept[i:]
                    break
            else:
                # 从保留窗口外恢复最近的用户消息
                for idx in range(len(non_system) - 1, -1, -1):
                    if non_system[idx].get("role") == "user":
                        kept = non_system[idx:]
                        break
            start = find_legal_message_start(kept)
            if start:
                kept = kept[start:]
        if not kept:
            kept = non_system[-min(len(non_system), 4) :]
            start = find_legal_message_start(kept)
            if start:
                kept = kept[start:]
        return system_messages + kept

    def _partition_tool_batches(
        self,
        spec: AgentRunSpec,
        tool_calls: list[ToolCallRequest],
    ) -> list[list[ToolCallRequest]]:
        """将工具调用分区为批次
        
        如果concurrent_tools为True，将并发安全的工具放在同一批次。
        
        Args:
            spec: 运行配置
            tool_calls: 工具调用列表
            
        Returns:
            工具调用批次列表
        """
        if not spec.concurrent_tools:
            return [[tool_call] for tool_call in tool_calls]

        batches: list[list[ToolCallRequest]] = []
        current: list[ToolCallRequest] = []
        for tool_call in tool_calls:
            get_tool = getattr(spec.tools, "get", None)
            tool = get_tool(tool_call.name) if callable(get_tool) else None
            can_batch = bool(tool and tool.concurrency_safe)
            if can_batch:
                current.append(tool_call)
                continue
            if current:
                batches.append(current)
                current = []
            batches.append([tool_call])
        if current:
            batches.append(current)
        return batches
