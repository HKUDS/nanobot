"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.
    
    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """
    # 上下文构建器：组装智能体提示的核心组件
    # 作用：整合引导文件、内存系统、技能框架和会话历史，构建完整的LLM输入
    # 设计目的：实现可扩展的上下文管理，支持动态加载和组合不同信息源
    # 好处：分离关注点，便于定制系统提示，支持多源信息融合，提高智能体表现
    
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    
    def __init__(self, workspace: Path):
        # 初始化上下文构建器
        # 作用：设置工作空间并加载内存和技能系统
        # 设计目的：通过工作空间路径统一管理所有资源
        # 好处：确保内存和技能数据与工作空间一致，便于持久化和同步
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
    
    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """
        Build the system prompt from bootstrap files, memory, and skills.
        
        Args:
            skill_names: Optional list of skills to include.
        
        Returns:
            Complete system prompt.
        """
        # 构建系统提示
        # 作用：组合核心身份、引导文件、内存和技能信息，形成完整的系统提示
        # 设计目的：提供统一的提示构建接口，支持动态技能加载
        # 好处：提示结构化，便于调试和优化，支持渐进式技能加载减少上下文长度
        parts = []
        
        # Core identity
        parts.append(self._get_identity())
        
        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
        
        # Memory context
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")
        
        # Skills - progressive loading
        # 1. Always-loaded skills: include full content
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")
        
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
        # 获取核心身份信息
        # 作用：生成智能体的基础身份描述，包括时间、运行环境和工作空间信息
        # 设计目的：为智能体提供稳定的自我认知和上下文基础
        # 好处：提高智能体回答的准确性和相关性，便于用户了解智能体能力
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"
        
        return f"""# nanobot 🐈

You are nanobot, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks

## Current Time
{now}

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Memory files: {workspace_path}/memory/MEMORY.md
- Daily notes: {workspace_path}/memory/YYYY-MM-DD.md
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool.

Always be helpful, accurate, and concise. When using tools, explain what you're doing.
When remembering something, write to {workspace_path}/memory/MEMORY.md"""
    
    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        # 加载引导文件
        # 作用：读取工作空间中的引导文件（如AGENTS.md, SOUL.md），提供智能体行为指导
        # 设计目的：支持用户自定义智能体行为和知识
        # 好处：灵活定制智能体，便于调整行为策略，支持个性化配置
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
        # 构建消息列表
        # 作用：将系统提示、会话历史和当前消息组装成LLM API所需的格式
        # 设计目的：提供统一的LLM输入接口，支持多媒体内容和会话上下文
        # 好处：标准化消息格式，便于不同LLM提供商兼容，支持复杂交互场景
        messages = []

        # System prompt
        system_prompt = self.build_system_prompt(skill_names)
        if channel and chat_id:
            system_prompt += f"\n\n## Current Session\nChannel: {channel}\nChat ID: {chat_id}"
        messages.append({"role": "system", "content": system_prompt})

        # History
        messages.extend(history)

        # Current message (with optional image attachments)
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        # 构建用户消息内容（支持图片）
        # 作用：处理文本和多媒体内容，将图片转换为base64编码格式
        # 设计目的：支持多模态输入，扩展智能体感知能力
        # 好处：增强用户体验，支持视觉任务处理，兼容主流LLM的多模态API
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
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str
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
        # 添加工具执行结果到消息列表
        # 作用：将工具执行结果格式化为LLM可识别的消息格式
        # 设计目的：支持工具调用链，实现LLM与工具的交互循环
        # 好处：保持对话上下文的完整性，支持复杂的多步工具调用流程
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        })
        return messages
    
    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        Add an assistant message to the message list.
        
        Args:
            messages: Current message list.
            content: Message content.
            tool_calls: Optional tool calls.
        
        Returns:
            Updated message list.
        """
        # 添加助手消息到消息列表
        # 作用：将LLM的响应（可能包含工具调用）添加到对话历史
        # 设计目的：支持工具调用格式标准化，保持对话状态同步
        # 好处：确保LLM能够正确理解工具调用上下文，支持连续的工具调用
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        
        if tool_calls:
            msg["tool_calls"] = tool_calls
        
        messages.append(msg)
        return messages


# ============================================
# 示例说明：ContextBuilder 使用示例
# ============================================
#
# 1. 基本使用示例：
# ```python
# from pathlib import Path
# from nanobot.agent.context import ContextBuilder
# from nanobot.agent.memory import MemoryStore
#
# # 创建工作空间
# workspace = Path("/path/to/workspace")
# context_builder = ContextBuilder(workspace)
#
# # 构建系统提示（包含所有组件）
# system_prompt = context_builder.build_system_prompt()
# print(f"系统提示长度: {len(system_prompt)} 字符")
# print(f"系统提示预览:\n{system_prompt[:500]}...")
#
# # 构建带特定技能的消息列表
# history = [
#     {"role": "user", "content": "你好"},
#     {"role": "assistant", "content": "你好！有什么我可以帮你的吗？"}
# ]
# current_message = "请分析这个Python文件"
# skill_names = ["python-analysis", "code-review"]
#
# messages = context_builder.build_messages(
#     history=history,
#     current_message=current_message,
#     skill_names=skill_names
# )
# print(f"消息列表包含 {len(messages)} 条消息")
#
# # 构建带图片的消息
# media_paths = ["/path/to/image1.png", "/path/to/image2.jpg"]
# messages_with_images = context_builder.build_messages(
#     history=history,
#     current_message="分析这些图片",
#     media=media_paths,
#     channel="telegram",
#     chat_id="user123"
# )
# ```
#
# 2. 引导文件（Bootstrap Files）：
# ```
# 工作空间中可放置以下文件定制智能体行为：
#
# AGENTS.md   - 定义智能体角色和行为准则
# SOUL.md     - 定义智能体个性和沟通风格
# USER.md     - 用户信息和偏好
# TOOLS.md    - 工具使用指南
# IDENTITY.md - 智能体身份信息
#
# 示例 AGENTS.md：
# ---
# # 智能体角色
#
# 你是一个专业的代码审查助手。
#
# ## 行为准则
# 1. 优先关注代码安全性
# 2. 提供具体的改进建议
# 3. 保持礼貌和建设性
# ---
# ```
#
# 3. 上下文构建流程：
# ```
# build_system_prompt() 构建顺序：
# 1. 核心身份 (_get_identity)
#    - 智能体名称和能力
#    - 当前时间和运行环境
#    - 工作空间路径
# 
# 2. 引导文件 (_load_bootstrap_files)
#    - AGENTS.md, SOUL.md 等
#    - 用户自定义行为指导
# 
# 3. 记忆上下文 (memory.get_memory_context)
#    - 长期记忆 (MEMORY.md)
#    - 今日笔记 (YYYY-MM-DD.md)
# 
# 4. 技能框架
#    - 始终加载的技能 (always=true)
#    - 可用技能摘要 (渐进式加载)
# 
# build_messages() 构建顺序：
# 1. 系统提示
# 2. 会话历史
# 3. 当前消息（支持多媒体）
# ```
#
# 4. 工具调用消息构建示例：
# ```python
# # 初始消息列表
# messages = context_builder.build_messages(
#     history=[],
#     current_message="搜索Python最佳实践"
# )
#
# # LLM 返回工具调用
# tool_calls = [
#     {
#         "id": "call_123",
#         "type": "function",
#         "function": {
#             "name": "web_search",
#             "arguments": '{"query": "Python best practices 2024"}'
#         }
#     }
# ]
#
# # 添加助手消息（包含工具调用）
# messages = context_builder.add_assistant_message(
#     messages,
#     content=None,
#     tool_calls=tool_calls
# )
#
# # 执行工具并添加结果
# result = "Python最佳实践包括..."
# messages = context_builder.add_tool_result(
#     messages,
#     tool_call_id="call_123",
#     tool_name="web_search",
#     result=result
# )
#
# # 现在可以再次调用 LLM
# response = await provider.chat(messages=messages, tools=tool_definitions)
# ```
#
# 5. 渐进式技能加载：
# ```python
# # 策略1：始终加载关键技能
# always_skills = context_builder.skills.get_always_skills()
# # 这些技能的完整内容包含在系统提示中
#
# # 策略2：按需加载（推荐）
# # 系统提示只包含技能摘要
# # 智能体使用 read_file 工具读取需要的技能
# # 好处：减少上下文长度，提高效率
#
# # 技能摘要示例：
# # <skills>
# #   <skill available="true">
# #     <name>git-expert</name>
# #     <description>Git版本控制专家</description>
# #     <location>/workspace/skills/git-expert/SKILL.md</location>
# #   </skill>
# #   <skill available="false">
# #     <name>docker-advanced</name>
# #     <requires>CLI: docker-compose</requires>
# #   </skill>
# # </skills>
# ```
#
# 6. 多模态内容处理：
# ```python
# # 图片处理流程
# media_paths = ["/path/to/chart.png"]
# user_content = context_builder._build_user_content(
#     text="分析这张图表",
#     media=media_paths
# )
# # 返回格式（OpenAI Vision API 兼容）：
# # [
# #   {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
# #   {"type": "text", "text": "分析这张图表"}
# # ]
#
# # 添加到消息列表
# messages.append({"role": "user", "content": user_content})
# ```
#
# 7. 性能优化建议：
# - 使用渐进式技能加载减少上下文长度
# - 定期清理旧的会话历史
# - 缓存系统提示（无变化时重用）
# - 压缩图片以减少base64编码大小
