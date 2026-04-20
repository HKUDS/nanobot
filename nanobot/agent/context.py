"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
from importlib.resources import files as pkg_files
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.utils.helpers import build_assistant_message, current_time_str, detect_image_mime
from nanobot.utils.prompt_templates import render_template


class ContextBuilder:
    """构建代理提示词（系统提示 + 消息列表）的类"""

    # 引导文件名列表 - 这些文件会在启动时加载
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    # 运行时上下文标记 - 用于插入元数据（如时间、频道等），不是指令
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"
    # 最大历史记录数量 - 控制最近历史部分的显示条数
    _MAX_RECENT_HISTORY = 50
    # 运行时上下文结束标记
    _RUNTIME_CONTEXT_END = "[/Runtime Context]"

    def __init__(self, workspace: Path, timezone: str | None = None, disabled_skills: list[str] | None = None):
        """初始化 ContextBuilder
        
        Args:
            workspace: 工作目录路径
            timezone: 时区设置
            disabled_skills: 禁用的技能列表
        """
        self.workspace = workspace
        self.timezone = timezone
        # 初始化记忆存储
        self.memory = MemoryStore(workspace)
        # 初始化技能加载器
        self.skills = SkillsLoader(workspace, disabled_skills=set(disabled_skills) if disabled_skills else None)

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        channel: str | None = None,
    ) -> str:
        """构建系统提示词
        
        系统提示词由以下部分组成：
        1. 身份信息（identity）
        2. 引导文件内容（bootstrap files）
        3. 记忆上下文（memory）
        4. 常用技能（always skills）
        5. 技能摘要（skills summary）
        6. 最近历史记录（recent history）
        
        Args:
            skill_names: 要加载的技能名称列表
            channel: 频道标识
            
        Returns:
            构建好的系统提示词字符串
        """
        parts = [self._get_identity(channel=channel)]

        # 加载引导文件
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # 获取记忆上下文
        memory = self.memory.get_memory_context()
        if memory and not self._is_template_content(self.memory.read_memory(), "memory/MEMORY.md"):
            parts.append(f"# Memory\n\n{memory}")

        # 加载常用技能（始终启用的技能）
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        # 构建技能摘要
        skills_summary = self.skills.build_skills_summary(exclude=set(always_skills))
        if skills_summary:
            parts.append(render_template("agent/skills_section.md", skills_summary=skills_summary))

        # 获取最近的未处理历史记录
        entries = self.memory.read_unprocessed_history(since_cursor=self.memory.get_last_dream_cursor())
        if entries:
            capped = entries[-self._MAX_RECENT_HISTORY:]
            parts.append("# Recent History\n\n" + "\n".join(
                f"- [{e['timestamp']}] {e['content']}" for e in capped
            ))

        return "\n\n---\n\n".join(parts)

    def _get_identity(self, channel: str | None = None) -> str:
        """获取核心身份部分
        
        身份信息包括：
        - 工作目录路径
        - 运行时环境（操作系统、机器架构、Python版本）
        - 平台策略
        - 频道信息（可选）
        
        Args:
            channel: 频道标识
            
        Returns:
            渲染好的身份模板内容
        """
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return render_template(
            "agent/identity.md",
            workspace_path=workspace_path,
            runtime=runtime,
            platform_policy=render_template("agent/platform_policy.md", system=system),
            channel=channel or "",
        )

    @staticmethod
    def _build_runtime_context(
        channel: str | None, chat_id: str | None, timezone: str | None = None,
        session_summary: str | None = None,
    ) -> str:
        """构建不可信的运行时元数据块
        
        这是一个特殊的标记块，用于在用户消息前注入元数据信息。
        标记为"不可信"是因为这些信息来自外部输入，不是用户直接提供的内容。
        用于提供当前时间、频道、聊天ID、会话摘要等信息。
        
        Args:
            channel: 频道标识
            chat_id: 聊天ID
            timezone: 时区
            session_summary: 会话摘要（用于恢复会话）
            
        Returns:
            格式化的运行时上下文字符串
        """
        lines = [f"Current Time: {current_time_str(timezone)}"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        if session_summary:
            lines += ["", "[Resumed Session]", session_summary]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines) + "\n" + ContextBuilder._RUNTIME_CONTEXT_END

    @staticmethod
    def _merge_message_content(left: Any, right: Any) -> str | list[dict[str, Any]]:
        """合并两条消息内容
        
        用于合并连续的角色相同的消息，避免有些提供商拒绝连续同角色的消息。
        如果两边都是字符串，直接拼接；否则转换为消息块后合并。
        
        Args:
            left: 左侧消息内容
            right: 右侧消息内容
            
        Returns:
            合并后的消息内容（字符串或消息块列表）
        """
        if isinstance(left, str) and isinstance(right, str):
            return f"{left}\n\n{right}" if left else right

        def _to_blocks(value: Any) -> list[dict[str, Any]]:
            if isinstance(value, list):
                return [item if isinstance(item, dict) else {"type": "text", "text": str(item)} for item in value]
            if value is None:
                return []
            return [{"type": "text", "text": str(value)}]

        return _to_blocks(left) + _to_blocks(right)

    def _load_bootstrap_files(self) -> str:
        """加载所有引导文件
        
        引导文件是工作目录下的特殊文件，用于定义代理的身份和行为：
        - AGENTS.md: 代理的角色定义
        - SOUL.md: 代理的灵魂/价值观
        - USER.md: 用户信息
        - TOOLS.md: 可用工具列表
        
        Returns:
            合并后的引导文件内容
        """
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _is_template_content(content: str, template_path: str) -> bool:
        """检查内容是否与内置模板相同
        
        用于判断用户是否自定义了某个模板（记忆模板）。如果没有自定义，
        则不使用默认内容，让记忆部分更简洁。
        
        Args:
            content: 要检查的内容
            template_path: 模板路径
            
        Returns:
            如果内容与模板完全相同返回True
        """
        try:
            tpl = pkg_files("nanobot") / "templates" / template_path
            if tpl.is_file():
                return content.strip() == tpl.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        return False

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        current_role: str = "user",
        session_summary: str | None = None,
    ) -> list[dict[str, Any]]:
        """构建完整的消息列表用于LLM调用
        
        消息列表结构：
        1. 系统消息（system）- 包含完整的系统提示词
        2. 历史消息（history）- 对话历史
        3. 当前用户消息（user）- 包含运行时上下文和用户内容
        
        Args:
            history: 对话历史记录
            current_message: 当前用户消息
            skill_names: 技能名称列表
            media: 附件媒体路径列表
            channel: 频道标识
            chat_id: 聊天ID
            current_role: 当前消息角色
            session_summary: 会话摘要
            
        Returns:
            完整的消息列表
        """
        # 构建运行时上下文
        runtime_ctx = self._build_runtime_context(channel, chat_id, self.timezone, session_summary=session_summary)
        # 构建用户内容（支持图片）
        user_content = self._build_user_content(current_message, media)

        # 合并运行时上下文和用户内容，避免连续同角色消息
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content
        
        # 构建消息列表
        messages = [
            {"role": "system", "content": self.build_system_prompt(skill_names, channel=channel)},
            *history,
        ]
        
        # 如果最后一条消息与当前角色相同，合并内容
        if messages[-1].get("role") == current_role:
            last = dict(messages[-1])
            last["content"] = self._merge_message_content(last.get("content"), merged)
            messages[-1] = last
            return messages
        messages.append({"role": current_role, "content": merged})
        return messages

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """构建用户消息内容，支持base64编码的图片
        
        将图片转换为适用于多模态LLM的格式：
        - 读取图片文件
        - 检测MIME类型
        - base64编码
        - 包装成image_url格式
        
        Args:
            text: 文本消息内容
            media: 媒体文件路径列表
            
        Returns:
            用户消息内容（文本或包含图片的多模态内容）
        """
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(raw).decode()
            images.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
                "_meta": {"path": str(p)},
            })

        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: Any,
    ) -> list[dict[str, Any]]:
        """添加工具执行结果到消息列表
        
        在消息列表中添加工具调用结果，供LLM生成后续响应。
        
        Args:
            messages: 消息列表
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            result: 工具执行结果
            
        Returns:
            添加工具结果后的消息列表
        """
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages

    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """添加助手消息到消息列表
        
        用于记录LLM的响应，包括：
        - 文本内容
        - 工具调用请求
        - 推理过程（thinking）
        
        Args:
            messages: 消息列表
            content: 文本内容
            tool_calls: 工具调用列表
            reasoning_content: 推理内容
            thinking_blocks: 推理块列表
            
        Returns:
            添加助手消息后的消息列表
        """
        messages.append(build_assistant_message(
            content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        ))
        return messages