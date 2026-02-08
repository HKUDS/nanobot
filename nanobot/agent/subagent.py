"""Subagent manager for background task execution."""

# 模块作用：子代理管理器，处理后台异步任务执行
# 设计目的：实现轻量子代理架构，支持长时间运行任务与主代理隔离
# 好处：避免阻塞主代理，支持并行任务处理，结果自动通知
import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool


# 作用：子代理管理器核心类，管理后台任务生命周期
# 设计目的：实现任务隔离、资源管理和结果路由机制
# 好处：主代理不阻塞，任务可并行执行，自动清理完成的任务
class SubagentManager:
    """
    Manages background subagent execution.
    
    Subagents are lightweight agent instances that run in the background
    to handle specific tasks. They share the same LLM provider but have
    isolated context and a focused system prompt.
    """
    
    # 作用：初始化子代理管理器，配置共享资源和限制
    # 设计目的：依赖注入核心组件，支持配置继承和自定义
    # 好处：资源复用，配置一致，安全限制可控
    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from nanobot.config.schema import ExecToolConfig
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
    
    # 作用：创建并启动子代理执行后台任务
    # 设计目的：任务ID生成、异步任务包装、自动清理回调
    # 好处：用户友好反馈，任务生命周期管理，错误隔离
    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
    ) -> str:
        """
        Spawn a subagent to execute a task in the background.
        
        Args:
            task: The task description for the subagent.
            label: Optional human-readable label for the task.
            origin_channel: The channel to announce results to.
            origin_chat_id: The chat ID to announce results to.
        
        Returns:
            Status message indicating the subagent was started.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        
        origin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
        }
        
        # Create background task
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin)
        )
        self._running_tasks[task_id] = bg_task
        
        # Cleanup when done
        bg_task.add_done_callback(lambda _: self._running_tasks.pop(task_id, None))
        
        logger.info(f"Spawned subagent [{task_id}]: {display_label}")
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."
    
    # 作用：执行子代理任务循环，处理工具调用和结果生成
    # 设计目的：有限迭代的代理循环，专用工具集，结果格式化
    # 好处：任务执行可控，资源限制明确，结果标准化
    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info(f"Subagent [{task_id}] starting task: {label}")
        
        try:
            # Build subagent tools (no message tool, no spawn tool)
            tools = ToolRegistry()
            allowed_dir = self.workspace if self.restrict_to_workspace else None
            tools.register(ReadFileTool(allowed_dir=allowed_dir))
            tools.register(WriteFileTool(allowed_dir=allowed_dir))
            tools.register(ListDirTool(allowed_dir=allowed_dir))
            tools.register(ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            ))
            tools.register(WebSearchTool(api_key=self.brave_api_key))
            tools.register(WebFetchTool())
            
            # Build messages with subagent-specific prompt
            system_prompt = self._build_subagent_prompt(task)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]
            
            # Run agent loop (limited iterations)
            max_iterations = 15
            iteration = 0
            final_result: str | None = None
            
            while iteration < max_iterations:
                iteration += 1
                
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                )
                
                if response.has_tool_calls:
                    # Add assistant message with tool calls
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })
                    
                    # Execute tools
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments)
                        logger.debug(f"Subagent [{task_id}] executing: {tool_call.name} with arguments: {args_str}")
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    final_result = response.content
                    break
            
            if final_result is None:
                final_result = "Task completed but no final response was generated."
            
            logger.info(f"Subagent [{task_id}] completed successfully")
            await self._announce_result(task_id, label, task, final_result, origin, "ok")
            
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error(f"Subagent [{task_id}] failed: {e}")
            await self._announce_result(task_id, label, task, error_msg, origin, "error")
    
    # 作用：通过消息总线向主代理通知子代理结果
    # 设计目的：结构化结果格式化，系统消息注入，路由信息传递
    # 好处：主代理无缝处理结果，用户友好摘要，错误传播
    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"
        
        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""
        
        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )
        
        await self.bus.publish_inbound(msg)
        logger.debug(f"Subagent [{task_id}] announced result to {origin['channel']}:{origin['chat_id']}")
    
    # 作用：构建子代理专用系统提示，限制能力和明确任务
    # 设计目的：任务专注性提示，能力限制说明，工作空间信息
    # 好处：子代理行为可控，避免副作用，任务执行专注
    def _build_subagent_prompt(self, task: str) -> str:
        """Build a focused system prompt for the subagent."""
        return f"""# Subagent

You are a subagent spawned by the main agent to complete a specific task.

## Your Task
{task}

## Rules
1. Stay focused - complete only the assigned task, nothing else
2. Your final response will be reported back to the main agent
3. Do not initiate conversations or take on side tasks
4. Be concise but informative in your findings

## What You Can Do
- Read and write files in the workspace
- Execute shell commands
- Search the web and fetch web pages
- Complete the task thoroughly

## What You Cannot Do
- Send messages directly to users (no message tool available)
- Spawn other subagents
- Access the main agent's conversation history

## Workspace
Your workspace is at: {self.workspace}

When you have completed the task, provide a clear summary of your findings or actions."""
    
    # 作用：获取当前运行中的子代理数量
    # 设计目的：监控任务负载，资源使用统计
    # 好处：系统状态监控，负载均衡决策支持
    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)


# ============================================
# 示例说明：SubagentManager 使用示例
# ============================================
#
# 1. 基本使用（通过智能体工具调用）：
# ```python
# # 通常在智能体工具中调用，例如SpawnTool
# # 用户请求："请后台分析我的项目依赖"
# # 智能体响应："好的，我会在后台分析。"
# # 然后调用 subagent_manager.spawn() 启动后台任务
# ```
#
# 2. 直接使用示例：
# ```python
# from nanobot.agent.subagent import SubagentManager
# from nanobot.providers.groq import GroqProvider
# from nanobot.bus.queue import MessageBus
# from pathlib import Path
# import asyncio
#
# async def example():
#     # 初始化组件
#     provider = GroqProvider(api_key="your-api-key")
#     bus = MessageBus()
#     workspace = Path("/path/to/workspace")
#     
#     # 创建子代理管理器
#     manager = SubagentManager(
#         provider=provider,
#         workspace=workspace,
#         bus=bus,
#         model="llama-3.3-70b-versatile",
#         restrict_to_workspace=True
#     )
#     
#     # 启动后台任务
#     task = "分析项目根目录下的requirements.txt文件，找出过时的依赖包并建议更新"
#     status = await manager.spawn(
#         task=task,
#         label="依赖分析",
#         origin_channel="telegram",
#         origin_chat_id="user123"
#     )
#     print(f"任务状态: {status}")
#     
#     # 检查运行中的任务数
#     count = manager.get_running_count()
#     print(f"当前运行中的子代理: {count}")
# 
# # 运行示例
# asyncio.run(example())
# ```
#
# 3. 子代理任务执行流程：
# ```
# 1. spawn() 创建任务 -> 生成唯一ID -> 启动异步任务
# 2. _run_subagent() 执行：
#    - 构建专用工具集（无消息/生成工具）
#    - 创建任务专注的系统提示
#    - 运行有限迭代的代理循环（最大15轮）
#    - 执行工具调用（文件、Shell、Web）
# 3. 任务完成：
#    - 成功：_announce_result() 发送成功消息
#    - 失败：_announce_result() 发送错误消息
# 4. 结果通知：
#    - 通过消息总线发送系统消息到主代理
#    - 主代理接收并生成用户友好摘要
# ```
#
# 4. 子代理系统提示示例（自动生成）：
# ```
# # Subagent
#
# You are a subagent spawned by the main agent to complete a specific task.
#
# ## Your Task
# 分析项目根目录下的requirements.txt文件...
#
# ## Rules
# 1. Stay focused - complete only the assigned task, nothing else
# 2. Your final response will be reported back to the main agent
# 3. Do not initiate conversations or take on side tasks
# 4. Be concise but informative in your findings
#
# ## What You Can Do
# - Read and write files in the workspace
# - Execute shell commands
# - Search the web and fetch web pages
# - Complete the task thoroughly
#
# ## What You Cannot Do
# - Send messages directly to users (no message tool available)
# - Spawn other subagents
# - Access the main agent's conversation history
#
# ## Workspace
# Your workspace is at: /path/to/workspace
# ```
#
# 5. 使用场景：
# - 长时间运行的分析任务（代码分析、数据统计）
# - 资源密集型操作（文件处理、数据处理）
# - 需要专注不受干扰的任务（复杂问题解决）
# - 并行处理多个独立请求
