"""Session management for conversation history."""

# 模块作用：会话管理器，管理智能体与用户的对话历史
# 设计目的：实现会话的持久化存储和缓存，支持跨会话连续性
# 好处：提高用户体验，支持对话恢复，便于分析和调试
import json
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir, safe_filename


# 作用：会话数据类，存储单个会话的消息和元数据
# 设计目的：使用dataclass简化定义，支持消息历史管理
# 好处：类型安全，自动序列化，内存高效
@dataclass
class Session:
    """
    A conversation session.
    
    Stores messages in JSONL format for easy reading and persistence.
    """
    
    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # 作用：添加消息到会话，更新时间戳
    # 设计目的：支持角色标记和额外元数据，自动维护更新时间
    # 好处：完整的消息记录，便于后续分析和调试
    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()
    
    # 作用：获取最近的N条消息，格式化为LLM输入格式
    # 设计目的：限制历史长度，支持LLM上下文窗口管理
    # 好处：控制上下文长度，提高性能和成本效益
    def get_history(self, max_messages: int = 50) -> list[dict[str, Any]]:
        """
        Get message history for LLM context.
        
        Args:
            max_messages: Maximum messages to return.
        
        Returns:
            List of messages in LLM format.
        """
        # Get recent messages
        recent = self.messages[-max_messages:] if len(self.messages) > max_messages else self.messages
        
        # Convert to LLM format (just role and content)
        return [{"role": m["role"], "content": m["content"]} for m in recent]
    
    # 作用：清空会话所有消息
    # 设计目的：支持会话重置，释放内存
    # 好处：支持用户重置对话，清除敏感信息
    def clear(self) -> None:
        """Clear all messages in the session."""
        self.messages = []
        self.updated_at = datetime.now()


# 作用：会话管理器核心类，管理所有会话的加载、保存和缓存
# 设计目的：基于文件系统的持久化，内存缓存优化性能
# 好处：会话数据持久化，快速访问，支持多会话并发
class SessionManager:
    """
    Manages conversation sessions.
    
    Sessions are stored as JSONL files in the sessions directory.
    """
    
    # 作用：初始化会话管理器，设置会话目录和缓存
    # 设计目的：使用用户主目录存储会话，与工作空间分离
    # 好处：会话数据与用户绑定，支持多工作空间共享会话
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(Path.home() / ".nanobot" / "sessions")
        self._cache: dict[str, Session] = {}
    
    # 作用：根据会话键生成安全的文件路径
    # 设计目的：处理特殊字符，确保文件系统安全
    # 好处：防止路径遍历攻击，支持各种会话键格式
    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"
    
    # 作用：获取或创建会话，优先从缓存加载
    # 设计目的：缓存优化，减少磁盘IO，快速会话恢复
    # 好处：高性能会话访问，自动持久化加载
    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.
        
        Args:
            key: Session key (usually channel:chat_id).
        
        Returns:
            The session.
        """
        # Check cache
        if key in self._cache:
            return self._cache[key]
        
        # Try to load from disk
        session = self._load(key)
        if session is None:
            session = Session(key=key)
        
        self._cache[key] = session
        return session
    
    # 作用：从磁盘加载会话数据，解析JSONL格式
    # 设计目的：支持元数据和消息的分离存储
    # 好处：结构化数据，便于扩展，错误恢复
    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)
        
        if not path.exists():
            return None
        
        try:
            messages = []
            metadata = {}
            created_at = None
            
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    data = json.loads(line)
                    
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                    else:
                        messages.append(data)
            
            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata
            )
        except Exception as e:
            logger.warning(f"Failed to load session {key}: {e}")
            return None
    
    # 作用：将会话保存到磁盘，JSONL格式
    # 设计目的：持久化存储，支持增量写入
    # 好处：数据安全，崩溃恢复，便于分析
    def save(self, session: Session) -> None:
        """Save a session to disk."""
        path = self._get_session_path(session.key)
        
        with open(path, "w") as f:
            # Write metadata first
            metadata_line = {
                "_type": "metadata",
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata
            }
            f.write(json.dumps(metadata_line) + "\n")
            
            # Write messages
            for msg in session.messages:
                f.write(json.dumps(msg) + "\n")
        
        self._cache[session.key] = session
    
    # 作用：删除会话，清理缓存和文件
    # 设计目的：支持会话清理，释放资源
    # 好处：完整的生命周期管理，数据清理
    def delete(self, key: str) -> bool:
        """
        Delete a session.
        
        Args:
            key: Session key.
        
        Returns:
            True if deleted, False if not found.
        """
        # Remove from cache
        self._cache.pop(key, None)
        
        # Remove file
        path = self._get_session_path(key)
        if path.exists():
            path.unlink()
            return True
        return False
    
    # 作用：列出所有会话，按更新时间排序
    # 设计目的：提供会话概览，支持管理界面
    # 好处：快速浏览会话，支持清理和维护
    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.
        
        Returns:
            List of session info dicts.
        """
        sessions = []
        
        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                # Read just the metadata line
                with open(path) as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            sessions.append({
                                "key": path.stem.replace("_", ":"),
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "path": str(path)
                            })
            except Exception:
                continue
        
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)


# ============================================
# 示例说明：SessionManager 使用示例
# ============================================
#
# 1. 基本使用示例：
# ```python
# from pathlib import Path
# from nanobot.session.manager import SessionManager
#
# # 创建工作空间
# workspace = Path("/path/to/workspace")
# session_manager = SessionManager(workspace)
#
# # 获取或创建会话（键格式：channel:chat_id）
# session = session_manager.get_or_create("telegram:user123")
#
# # 添加消息到会话
# session.add_message("user", "你好，请帮我分析代码")
# session.add_message("assistant", "好的，请提供代码文件路径")
#
# # 获取历史记录（用于LLM上下文）
# history = session.get_history(max_messages=10)
# for msg in history:
#     print(f"{msg['role']}: {msg['content'][:50]}...")
#
# # 保存会话到磁盘
# session_manager.save(session)
#
# # 列出所有会话
# all_sessions = session_manager.list_sessions()
# for info in all_sessions:
#     print(f"会话: {info['key']}, 更新: {info['updated_at']}")
#
# # 删除会话
# deleted = session_manager.delete("telegram:user123")
# print(f"删除成功: {deleted}")
# ```
#
# 2. 会话文件格式（JSONL）：
# ```
# ~/.nanobot/sessions/telegram_user123.jsonl
#
# {"_type": "metadata", "created_at": "2024-01-15T10:30:00", 
#  "updated_at": "2024-01-15T11:00:00", "metadata": {}}
# {"role": "user", "content": "你好", "timestamp": "2024-01-15T10:30:00"}
# {"role": "assistant", "content": "你好！有什么可以帮你的？", 
#  "timestamp": "2024-01-15T10:30:05"}
# ```
#
# 3. 缓存机制说明：
# ```
# SessionManager 使用两级存储：
# 1. 内存缓存 (_cache): dict[str, Session]
#    - 快速访问活跃会话
#    - 减少磁盘IO
#    
# 2. 磁盘存储 (JSONL文件): ~/.nanobot/sessions/
#    - 持久化存储
#    - 支持程序重启后恢复
#    
# get_or_create() 查找顺序：
# 1. 检查内存缓存
# 2. 尝试从磁盘加载
# 3. 创建新会话
# ```
#
# 4. 会话键设计：
# - 格式: "{channel}:{chat_id}"
# - 示例: "telegram:123456789", "discord:guild123_channel456"
# - 唯一标识用户在不同平台的会话
# - 支持同一用户多平台会话隔离
#
# 5. 使用场景：
# - **对话连续性**: 跨请求保持上下文
# - **多用户支持**: 每个用户独立会话
# - **历史检索**: 查看过往对话
# - **会话管理**: 清理、归档旧会话
#
# 6. 性能优化：
# - 限制历史消息数量（默认50条）
# - 内存缓存热点会话
# - 延迟加载非活跃会话
# - JSONL格式支持流式读取
