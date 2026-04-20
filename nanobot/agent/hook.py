"""Shared lifecycle hook primitives for agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMResponse, ToolCallRequest


@dataclass(slots=True)
class AgentHookContext:
    """代理运行期间每个迭代的可变状态（暴露给hook使用）
    
    这个数据类包含了代理运行时每次迭代的完整上下文信息，
    hook可以通过这些信息来监控、修改或记录代理的行为。
    
    属性说明：
    - iteration: 当前迭代计数（从1开始）
    - messages: 当前完整的消息列表
    - response: LLM的原始响应对象
    - usage: token使用统计 {'prompt': int, 'completion': int, 'total': int}
    - tool_calls: 本次迭代中LLM调用的工具请求列表
    - tool_results: 工具执行结果列表
    - tool_events: 工具执行过程中的事件日志列表
    - final_content: 最终的文本响应内容
    - stop_reason: LLM停止的原因 ('end_turn', 'max_tokens', 'tool_use', etc.)
    - error: 错误信息（如果有）
    """

    iteration: int  # 当前迭代编号
    messages: list[dict[str, Any]]  # 消息列表
    response: LLMResponse | None = None  # LLM响应对象
    usage: dict[str, int] = field(default_factory=dict)  # token使用统计
    tool_calls: list[ToolCallRequest] = field(default_factory=list)  # 工具调用请求
    tool_results: list[Any] = field(default_factory=list)  # 工具执行结果
    tool_events: list[dict[str, str]] = field(default_factory=list)  # 工具事件日志
    final_content: str | None = None  # 最终文本内容
    stop_reason: str | None = None  # 停止原因
    error: str | None = None  # 错误信息


class AgentHook:
    """代理运行器的生命周期钩子接口（基类）
    
    这是一个抽象基类，提供了代理运行期间的各个阶段的钩子方法。
    用户可以继承这个类并重写相应的方法来自定义代理行为。
    
    钩子执行顺序：
    1. before_iteration - 每次迭代开始前调用
    2. on_stream - 流式输出的每个增量块
    3. on_stream_end - 流式输出结束
    4. before_execute_tools - 执行工具前调用
    5. after_iteration - 每次迭代结束后调用
    6. finalize_content - 最终内容处理（同步方法，不是pipeline）
    
    使用示例：
    ```python
    class MyHook(AgentHook):
        async def before_iteration(self, context: AgentHookContext) -> None:
            print(f"开始第 {context.iteration} 次迭代")
        
        async def after_iteration(self, context: AgentHookContext) -> None:
            print(f"完成第 {context.iteration} 次迭代")
    ```
    """

    def __init__(self, reraise: bool = False) -> None:
        """初始化hook
        
        Args:
            reraise: 如果为True，该hook的错误不会被捕获，会导致代理循环终止
        """
        self._reraise = reraise

    def wants_streaming(self) -> bool:
        """是否需要流式输出
        
        返回True表示需要接收on_stream/on_stream_end回调。
        默认返回False，表示使用非流式模式。
        
        Returns:
            是否需要流式输出
        """
        return False

    async def before_iteration(self, context: AgentHookContext) -> None:
        """每次迭代开始前调用
        
        在LLM调用之前触发，可以用于：
        - 记录开始时间
        - 修改messages列表
        - 准备工具上下文
        
        Args:
            context: 当前迭代上下文
        """
        pass

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        """流式输出的每个增量块
        
        仅在wants_streaming()返回True时调用。
        每次LLM输出新内容时触发，可以用于：
        - 实时显示输出
        - 收集输出片段
        
        Args:
            context: 当前迭代上下文
            delta: 新增的输出文本
        """
        pass

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        """流式输出结束
        
        在LLM完成流式输出后触发。
        
        Args:
            context: 当前迭代上下文
            resuming: 是否是恢复的流式输出（中断后继续）
        """
        pass

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """执行工具前调用
        
        在工具执行前触发，可以用于：
        - 记录工具调用日志
        - 修改工具参数
        - 准备工具环境
        
        注意：此时tool_calls已填充，但工具还未执行
        
        Args:
            context: 当前迭代上下文
        """
        pass

    async def after_iteration(self, context: AgentHookContext) -> None:
        """每次迭代结束后调用
        
        在LLM响应和工具执行完成后触发，可以用于：
        - 记录迭代结果
        - 清理资源
        - 触发后续操作
        
        Args:
            context: 当前迭代上下文
        """
        pass

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        """最终内容处理（同步方法）
        
        这是唯一一个同步方法，在代理循环结束后调用。
        与其他async方法不同，这个方法会形成pipeline（链式处理），
        不会进行错误隔离，错误会直接传播。
        
        可用于：
        - 后处理输出内容
        - 添加格式 wrapper
        - 清理敏感信息
        
        Args:
            context: 当前迭代上下文
            content: 原始内容
            
        Returns:
            处理后的内容
        """
        return content


class CompositeHook(AgentHook):
    """组合钩子 - 委托给多个有序的钩子执行
    
    这是一个"扇出"模式的钩子，可以将多个钩子组合在一起。
    异步方法会为每个钩子单独调用，并进行错误隔离
    （单个钩子的错误不会影响其他钩子）。
    
    finalize_content是pipeline模式，所有钩子会链式处理内容。
    
    错误隔离说明：
    - 除了finalize_content外的async方法：每个hook独立捕获异常，单个hook错误不会终止代理
    - finalize_content：pipeline模式，错误会直接传播
    
    示例：
    ```python
    hooks = CompositeHook([
        LoggingHook(),
        MetricsHook(),
        CustomHook(),
    ])
    ```
    """

    __slots__ = ("_hooks",)

    def __init__(self, hooks: list[AgentHook]) -> None:
        """初始化组合钩子
        
        Args:
            hooks: 要组合的钩子列表，按执行顺序排列
        """
        super().__init__()
        self._hooks = list(hooks)

    def wants_streaming(self) -> bool:
        """是否需要流式输出（任一hook需要即需要）
        
        Returns:
            是否需要流式输出
        """
        return any(h.wants_streaming() for h in self._hooks)

    async def _for_each_hook_safe(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        """安全地遍历每个hook执行方法
        
        为每个hook执行指定方法，并进行错误隔离。
        如果hook设置了_reraise=True，则该hook的错误不会被捕获。
        
        Args:
            method_name: 要执行的方法名
            *args: 位置参数
            **kwargs: 关键字参数
        """
        for h in self._hooks:
            # 如果设置了reraise，则不捕获异常
            if getattr(h, "_reraise", False):
                await getattr(h, method_name)(*args, **kwargs)
                continue

            try:
                await getattr(h, method_name)(*args, **kwargs)
            except Exception:
                logger.exception("AgentHook.{} error in {}", method_name, type(h).__name__)

    async def before_iteration(self, context: AgentHookContext) -> None:
        """遍历调用所有hook的before_iteration"""
        await self._for_each_hook_safe("before_iteration", context)

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        """遍历调用所有hook的on_stream"""
        await self._for_each_hook_safe("on_stream", context, delta)

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        """遍历调用所有hook的on_stream_end"""
        await self._for_each_hook_safe("on_stream_end", context, resuming=resuming)

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """遍历调用所有hook的before_execute_tools"""
        await self._for_each_hook_safe("before_execute_tools", context)

    async def after_iteration(self, context: AgentHookContext) -> None:
        """遍历调用所有hook的after_iteration"""
        await self._for_each_hook_safe("after_iteration", context)

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        """链式调用所有hook的finalize_content
        
        与async方法不同，这是pipeline模式：
        - 前一个hook的输出作为下一个hook的输入
        - 不会进行错误隔离，错误会直接传播
        
        Args:
            context: 当前迭代上下文
            content: 原始内容
            
        Returns:
            最终处理后的内容
        """
        for h in self._hooks:
            content = h.finalize_content(context, content)
        return content