# Project Documentation

- **Generated at:** 2026-03-16 23:11:15
- **Root Dir:** `nanobot/session`
- **File Count:** 2
- **Total Size:** 7.40 KB
 claude 解读：
 *Thinking...*

> The user has shared a document containing the source code for a session management module in a project called "nanobot". They said "详细解释" which is Chinese for "detailed explanation". Let me provide a thorough explanation of this code in Chinese.

# Nanobot Session 模块详细解析

这个模块负责管理对话会话（conversation session）的生命周期，包括创建、加载、持久化和检索。整体采用 JSONL（每行一个 JSON 对象）作为存储格式，设计上强调**追加式写入**以配合 LLM 的缓存机制。下面逐层拆解。

---

## 一、`Session` 数据类

`Session` 是一个用 `@dataclass` 定义的会话实体，核心字段包括：

`key` 是会话的唯一标识符，格式为 `channel:chat_id`，将渠道（如 Telegram、Discord）和具体聊天 ID 绑定在一起，使得不同平台、不同对话各自独立。`messages` 是一个字典列表，存储所有历史消息。`last_consolidated` 是一个整数指针，记录已经被"整合"（consolidation）到外部文件（如 MEMORY.md / HISTORY.md）的消息数量——这个设计的关键意图是：整合后并不删除原始消息，而只是移动指针，保证 LLM prompt 缓存不被破坏。

### `add_message` 方法

每条消息被包装成一个字典，包含 `role`、`content`、`timestamp`，以及通过 `**kwargs` 传入的额外字段（如 `tool_calls`、`tool_call_id` 等，用于支持工具调用场景）。消息被直接追加到列表末尾，同时更新 `updated_at` 时间戳。

### `get_history` 方法

这是为 LLM 构造输入上下文的核心方法。它的逻辑分三步：

第一步，从 `last_consolidated` 位置开始切片，只取尚未整合的消息。这意味着已被摘要化的早期消息不会重复发给 LLM，节省 token 开销。第二步，对切片再做一次尾部截取（默认最多 500 条），防止上下文窗口溢出。第三步，也是最精巧的一步——向前扫描，丢弃开头所有非 `user` 角色的消息，直到遇到第一条 `user` 消息为止。这是为了避免出现"孤立的 tool_result 块"：如果上下文的开头是一条 `assistant` 消息或 `tool` 结果，而没有对应的 `user` 请求，Claude 等模型的 API 会报错或产生混淆。最终输出时只保留 `role`、`content` 以及工具调用相关的字段，剥离了 `timestamp` 等 LLM 不需要的元信息。

### `clear` 方法

重置整个会话状态：清空消息列表、将整合指针归零。这是一个硬清除操作。

---

## 二、`SessionManager` 管理器

`SessionManager` 是会话的工厂和仓库，负责会话的查找、加载、保存和列举。

### 初始化与路径管理

构造函数接收一个 `workspace` 路径，在其下创建 `sessions/` 子目录。同时通过 `get_legacy_sessions_dir()` 获取旧版全局路径（`~/.nanobot/sessions/`），这体现了一个**迁移策略**：项目从全局存储迁移到了工作空间级别的存储，但仍然兼容旧数据。

`_get_session_path` 将会话 key 中的冒号替换为下划线，再通过 `safe_filename` 做文件名安全化处理，最终生成如 `telegram_12345678.jsonl` 这样的文件名。

### `get_or_create` 方法

这是外部获取会话的主入口，采用了**内存缓存 + 磁盘回退**的两级查找策略。先查 `_cache` 字典，命中则直接返回；未命中则尝试从磁盘加载；仍然找不到就创建一个空白会话。加载或创建后都会放入缓存，避免后续重复 I/O。

### `_load` 方法

从 JSONL 文件中恢复会话。它首先检查工作空间路径，如果不存在则检查旧版路径，并尝试用 `shutil.move` 做原地迁移——这是一次性的操作，迁移后旧路径的文件就不存在了。

JSONL 文件的第一行是元数据行（通过 `_type: "metadata"` 标记区分），包含 `created_at`、`metadata`、`last_consolidated` 等信息。后续每一行都是一条消息。这种格式的优点在于：读取元数据只需读第一行，而消息部分天然支持逐行追加。异常处理上，如果文件损坏则返回 `None`，由调用方创建新会话。

### `save` 方法

写入时采用**全量覆盖**策略（`"w"` 模式），先写元数据行，再逐条写消息。虽然 JSONL 格式理论上支持 append-only 写入，但这里选择全量写入是为了同步更新元数据行中的 `last_consolidated` 和 `updated_at` 等字段。保存完成后同步更新内存缓存。

### `invalidate` 方法

从缓存中移除指定会话。这在外部修改了会话文件（如手动编辑或整合操作后）时有用，下次 `get_or_create` 会重新从磁盘加载最新状态。

### `list_sessions` 方法

遍历 `sessions/` 目录下所有 `.jsonl` 文件，只读取每个文件的第一行元数据，提取 key、创建时间和更新时间。结果按更新时间降序排列。这个设计很高效——不需要加载完整的消息历史就能展示会话列表。

---

## 三、整体设计亮点总结

这个模块有几个值得注意的设计决策。首先是**追加式消息 + 指针式整合**：`last_consolidated` 指针让整合过程不需要修改消息列表本身，这对 LLM prompt 缓存非常友好——如果消息被删除或重排，缓存就会失效，导致每次请求都要重新计算所有 token。其次是**JSONL 格式**的选择：相比单个大 JSON 文件，JSONL 更适合流式追加和部分读取，也更容易人工调试。第三是**两级存储迁移**：从全局目录到工作空间目录的平滑过渡，用户无感知。最后是**防御性编程**：文件加载、迁移等操作都包裹在 try/except 中，用 loguru 记录异常但不中断程序运行。

<a name="toc"></a>
## 📂 扫描目录
- [__init__.py](#📄-__init__py) (5 lines, 0.13 KB)
- [manager.py](#📄-managerpy) (213 lines, 7.27 KB)

---

## 📄 __init__.py

````python
"""Session management module."""

from nanobot.session.manager import Session, SessionManager

__all__ = ["SessionManager", "Session"]

````

[⬆ 回到目录](#toc)

## 📄 manager.py

````python
"""Session management for conversation history."""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_legacy_sessions_dir
from nanobot.utils.helpers import ensure_dir, safe_filename


@dataclass
class Session:
    """
    A conversation session.

    Stores messages in JSONL format for easy reading and persistence.

    Important: Messages are append-only for LLM cache efficiency.
    The consolidation process writes summaries to MEMORY.md/HISTORY.md
    but does NOT modify the messages list or get_history() output.
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files

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

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input, aligned to a user turn."""
        unconsolidated = self.messages[self.last_consolidated:]
        sliced = unconsolidated[-max_messages:]

        # Drop leading non-user messages to avoid orphaned tool_result blocks
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break

        out: list[dict[str, Any]] = []
        for m in sliced:
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files in the sessions directory.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: dict[str, Session] = {}

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        """Legacy global session path (~/.nanobot/sessions/)."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            last_consolidated = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    def save(self, session: Session) -> None:
        """Save a session to disk."""
        path = self._get_session_path(session.key)

        with open(path, "w", encoding="utf-8") as f:
            metadata_line = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)

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
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            key = data.get("key") or path.stem.replace("_", ":", 1)
                            sessions.append({
                                "key": key,
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "path": str(path)
                            })
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)

````

[⬆ 回到目录](#toc)

---
### 📊 最终统计汇总
- **文件总数:** 2
- **代码总行数:** 218
- **物理总大小:** 7.40 KB
