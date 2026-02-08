"""Memory system for persistent agent memory."""

from pathlib import Path
from datetime import datetime

from nanobot.utils.helpers import ensure_dir, today_date


class MemoryStore:
    """
    Memory system for the agent.
    
    Supports daily notes (memory/YYYY-MM-DD.md) and long-term memory (MEMORY.md).
    """
    # 内存存储系统：智能体的持久化记忆管理
    # 作用：管理智能体的短期（每日笔记）和长期（MEMORY.md）记忆
    # 设计目的：实现记忆的持久化和检索，支持智能体的连续学习和个性化
    # 好处：提高智能体对话的连续性，支持个性化服务，便于知识积累和重用
    
    def __init__(self, workspace: Path):
        # 初始化内存存储系统
        # 作用：设置工作空间并创建内存目录结构
        # 设计目的：通过统一的工作空间管理所有记忆文件
        # 好处：确保记忆数据的持久化和一致性，便于备份和迁移
        self.workspace = workspace
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
    
    def get_today_file(self) -> Path:
        """Get path to today's memory file."""
        # 获取今日记忆文件路径
        # 作用：根据当前日期生成今日笔记的文件路径
        # 设计目的：支持按日期组织的记忆管理
        # 好处：便于按时间检索记忆，支持日常记录和回顾
        return self.memory_dir / f"{today_date()}.md"
    
    def read_today(self) -> str:
        """Read today's memory notes."""
        # 读取今日记忆笔记
        # 作用：读取当天记录的所有笔记内容
        # 设计目的：提供短期记忆的快速访问接口
        # 好处：支持实时记忆检索，提高智能体对近期事件的响应能力
        today_file = self.get_today_file()
        if today_file.exists():
            return today_file.read_text(encoding="utf-8")
        return ""
    
    def append_today(self, content: str) -> None:
        """Append content to today's memory notes."""
        # 追加内容到今日记忆笔记
        # 作用：将新内容添加到当天的记忆文件中
        # 设计目的：支持增量式记忆更新，避免覆盖已有记录
        # 好处：保持记忆的连续性，支持逐步积累知识和经验
        today_file = self.get_today_file()
        
        if today_file.exists():
            existing = today_file.read_text(encoding="utf-8")
            content = existing + "\n" + content
        else:
            # Add header for new day
            header = f"# {today_date()}\n\n"
            content = header + content
        
        today_file.write_text(content, encoding="utf-8")
    
    def read_long_term(self) -> str:
        """Read long-term memory (MEMORY.md)."""
        # 读取长期记忆
        # 作用：读取存储重要信息和用户偏好的长期记忆文件
        # 设计目的：提供稳定持久的记忆存储，支持个性化服务
        # 好处：保持智能体的一致性，支持跨会话的知识重用
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""
    
    def write_long_term(self, content: str) -> None:
        """Write to long-term memory (MEMORY.md)."""
        # 写入长期记忆
        # 作用：将重要信息保存到长期记忆文件中
        # 设计目的：支持记忆的持久化存储和更新
        # 好处：确保关键信息不丢失，支持智能体的长期学习和适应
        self.memory_file.write_text(content, encoding="utf-8")
    
    def get_recent_memories(self, days: int = 7) -> str:
        """
        Get memories from the last N days.
        
        Args:
            days: Number of days to look back.
        
        Returns:
            Combined memory content.
        """
        # 获取最近N天的记忆
        # 作用：检索最近几天内的记忆内容，提供短期上下文
        # 设计目的：支持基于时间窗口的记忆检索，提高相关性
        # 好处：增强智能体对近期事件的关注，提高对话的时效性
        from datetime import timedelta
        
        memories = []
        today = datetime.now().date()
        
        for i in range(days):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            file_path = self.memory_dir / f"{date_str}.md"
            
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                memories.append(content)
        
        return "\n\n---\n\n".join(memories)
    
    def list_memory_files(self) -> list[Path]:
        """List all memory files sorted by date (newest first)."""
        # 列出所有记忆文件（按日期倒序）
        # 作用：获取所有记忆文件的路径，按日期从新到旧排序
        # 设计目的：支持记忆文件的浏览和管理
        # 好处：便于记忆维护和清理，支持按时间线查看记忆历史
        if not self.memory_dir.exists():
            return []
        
        files = list(self.memory_dir.glob("????-??-??.md"))
        return sorted(files, reverse=True)
    
    def get_memory_context(self) -> str:
        """
        Get memory context for the agent.
        
        Returns:
            Formatted memory context including long-term and recent memories.
        """
        # 获取记忆上下文
        # 作用：组合长期记忆和近期记忆，形成供智能体使用的记忆上下文
        # 设计目的：提供统一的记忆访问接口，支持不同时间尺度的记忆融合
        # 好处：增强智能体回答的深度和广度，支持个性化对话体验
        parts = []
        
        # Long-term memory
        long_term = self.read_long_term()
        if long_term:
            parts.append("## Long-term Memory\n" + long_term)
        
        # Today's notes
        today = self.read_today()
        if today:
            parts.append("## Today's Notes\n" + today)
        
        return "\n\n".join(parts) if parts else ""


# ============================================
# 示例说明：MemoryStore 使用示例
# ============================================
#
# 1. 基本使用示例：
# ```python
# from pathlib import Path
# from nanobot.agent.memory import MemoryStore
#
# # 创建工作空间
# workspace = Path("/path/to/workspace")
# memory = MemoryStore(workspace)
#
# # 追加今日笔记（短期记忆）
# memory.append_today("用户喜欢使用Python进行数据分析")
# memory.append_today("用户提到正在学习机器学习")
#
# # 读取今日笔记
# today_notes = memory.read_today()
# print(f"今日笔记:\n{today_notes}")
#
# # 写入长期记忆（重要信息）
# long_term_content = """# 用户偏好
#
# - 编程语言: Python
# - 兴趣领域: 数据科学、机器学习
# - 沟通风格: 喜欢简洁直接的回答
# """
# memory.write_long_term(long_term_content)
#
# # 读取长期记忆
# long_term = memory.read_long_term()
# print(f"长期记忆:\n{long_term}")
#
# # 获取最近7天的记忆
# recent = memory.get_recent_memories(days=7)
# print(f"近期记忆:\n{recent}")
#
# # 获取完整记忆上下文（用于智能体）
# context = memory.get_memory_context()
# print(f"记忆上下文:\n{context}")
#
# # 列出所有记忆文件
# files = memory.list_memory_files()
# for f in files:
#     print(f"记忆文件: {f.name}")
# ```
#
# 2. 记忆文件结构：
# ```
# workspace/
# └── memory/
#     ├── MEMORY.md          # 长期记忆（用户偏好、重要信息）
#     ├── 2024-01-15.md      # 每日笔记（短期记忆）
#     ├── 2024-01-14.md
#     └── 2024-01-13.md
# ```
#
# 3. 记忆类型对比：
# | 特性 | 短期记忆（每日笔记） | 长期记忆（MEMORY.md） |
# |------|---------------------|----------------------|
# | 存储位置 | memory/YYYY-MM-DD.md | memory/MEMORY.md |
# | 更新频率 | 频繁，每天追加 | 较少，关键信息更新 |
# | 内容类型 | 日常对话、临时信息 | 用户偏好、重要事实 |
# | 检索范围 | 最近N天 | 全部 |
# | 典型用途 | 上下文连续性 | 个性化服务 |
#
# 4. 智能体集成示例：
# ```python
# # 在 ContextBuilder 中集成记忆
# def build_system_prompt(self, skill_names=None):
#     parts = []
#     
#     # 添加长期记忆
#     memory = self.memory.get_memory_context()
#     if memory:
#         parts.append(f"# Memory\n\n{memory}")
#     
#     # ... 其他提示组件
#     
#     return "\n\n---\n\n".join(parts)
# ```
#
# 5. 使用场景：
# - **个性化服务**: 记住用户偏好，提供定制化回答
# - **对话连续性**: 跨会话保持上下文，提高用户体验
# - **知识积累**: 记录重要信息，支持长期学习
# - **错误恢复**: 从记忆中恢复对话状态
#
# 6. 最佳实践：
# - 重要信息及时写入长期记忆
# - 定期清理过期的短期记忆
# - 敏感信息加密存储
# - 记忆内容定期备份
