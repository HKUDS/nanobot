"""Auto compact: proactive compression of idle sessions to reduce token cost and latency."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.agent.memory import Consolidator


class AutoCompact:
    """自动压缩：主动压缩空闲会话以减少token成本和延迟
    
    这个类负责检测空闲会话并将其压缩存档。当用户一段时间不活跃时，
    会话的大部分历史消息会被压缩成摘要，只保留最近几条消息。
    这样可以：
    1. 减少token使用量（降低成本）
    2. 减少延迟（更少的输入token）
    3. 保持会话上下文（通过摘要）
    """

    # 保留的最新消息数量（法律上需要保留的最近消息）
    _RECENT_SUFFIX_MESSAGES = 8

    def __init__(self, sessions: SessionManager, consolidator: Consolidator,
                 session_ttl_minutes: int = 0):
        """初始化自动压缩器
        
        Args:
            sessions: 会话管理器
            consolidator:  Consolidator（用于将消息压缩成摘要）
            session_ttl_minutes: 会话空闲多少分钟后触发压缩（0表示禁用）
        """
        self.sessions = sessions
        self.consolidator = consolidator
        self._ttl = session_ttl_minutes  # 会话存活时间（分钟）
        self._archiving: set[str] = set()  # 正在归档的会话key集合
        self._summaries: dict[str, tuple[str, datetime]] = {}  # 内存中的摘要缓存

    def _is_expired(self, ts: datetime | str | None,
                    now: datetime | None = None) -> bool:
        """检查会话是否已过期（空闲时间超过TTL）
        
        Args:
            ts: 上次更新时间
            now: 当前时间（可选，默认now）
            
        Returns:
            如果会话已过期返回True
        """
        if self._ttl <= 0 or not ts:
            return False
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return ((now or datetime.now()) - ts).total_seconds() >= self._ttl * 60

    @staticmethod
    def _format_summary(text: str, last_active: datetime) -> str:
        """格式化摘要文本
        
        将压缩后的摘要转换为包含空闲时间的格式，供恢复会话时使用。
        
        Args:
            text: 会话摘要文本
            last_active: 上次活跃时间
            
        Returns:
            格式化后的摘要字符串
        """
        idle_min = int((datetime.now() - last_active).total_seconds() / 60)
        return f"Inactive for {idle_min} minutes.\nPrevious conversation summary: {text}"

    def _split_unconsolidated(
        self, session: Session,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """将实时会话尾部拆分为可归档的前缀和保留的最近_suffix
        
        会话结构：
        - 已经被压缩的部分（last_consolidated之前）- 保持不变
        - 未被压缩的尾部（last_consolidated之后）- 拆分成：
          - 可归档的前缀（较旧的消息）
          - 保留的最近_suffix（最近N条消息，法律上需要保留）
        
        Args:
            session: 会话对象
            
        Returns:
            (可归档的消息列表, 保留的最新消息列表)
        """
        # 获取未被压缩的尾部消息
        tail = list(session.messages[session.last_consolidated:])
        if not tail:
            return [], []

        # 创建一个探测会话来确定保留多少条最近消息
        probe = Session(
            key=session.key,
            messages=tail.copy(),
            created_at=session.created_at,
            updated_at=session.updated_at,
            metadata={},
            last_consolidated=0,
        )
        # 保留最近的合法消息
        probe.retain_recent_legal_suffix(self._RECENT_SUFFIX_MESSAGES)
        kept = probe.messages
        # 计算需要归档的消息数量
        cut = len(tail) - len(kept)
        return tail[:cut], kept

    def check_expired(self, schedule_background: Callable[[Coroutine], None],
                      active_session_keys: Collection[str] = ()) -> None:
        """检查并调度过期会话的归档任务
        
        检查所有会话，对过期且不在活动中的会话调度归档任务。
        跳过正在运行代理任务的活动会话（避免干扰用户）。
        
        Args:
            schedule_background: 后台任务调度函数
            active_session_keys: 活动会话的key集合（正在运行代理任务的会话）
        """
        now = datetime.now()
        for info in self.sessions.list_sessions():
            key = info.get("key", "")
            if not key or key in self._archiving:
                continue
            # 跳过活动会话
            if key in active_session_keys:
                continue
            # 检查是否过期
            if self._is_expired(info.get("updated_at"), now):
                self._archiving.add(key)
                schedule_background(self._archive(key))

    async def _archive(self, key: str) -> None:
        """归档会话的实际执行逻辑
        
        归档过程：
        1. 使会话失效（防止在归档过程中被访问）
        2. 获取会话并拆分消息
        3. 调用consolidator压缩旧消息为摘要
        4. 保存压缩后的会话（只保留最近消息+摘要）
        
        Args:
            key: 会话key
        """
        try:
            # 使会话失效
            self.sessions.invalidate(key)
            session = self.sessions.get_or_create(key)
            # 拆分消息为可归档部分和保留部分
            archive_msgs, kept_msgs = self._split_unconsolidated(session)
            if not archive_msgs and not kept_msgs:
                # 没有消息需要归档，直接更新 时间戳
                session.updated_at = datetime.now()
                self.sessions.save(session)
                return

            last_active = session.updated_at
            summary = ""
            # 压缩归档消息为摘要
            if archive_msgs:
                summary = await self.consolidator.archive(archive_msgs) or ""
            # 保存摘要到内存缓存（进程未重启时使用）
            if summary and summary != "(nothing)":
                self._summaries[key] = (summary, last_active)
                session.metadata["_last_summary"] = {"text": summary, "last_active": last_active.isoformat()}
            # 只保留最近消息
            session.messages = kept_msgs
            session.last_consolidated = 0
            session.updated_at = datetime.now()
            self.sessions.save(session)
            if archive_msgs:
                logger.info(
                    "Auto-compact: archived {} (archived={}, kept={}, summary={})",
                    key,
                    len(archive_msgs),
                    len(kept_msgs),
                    bool(summary),
                )
        except Exception:
            logger.exception("Auto-compact: failed for {}", key)
        finally:
            # 从归档集合中移除
            self._archiving.discard(key)

    def prepare_session(self, session: Session, key: str) -> tuple[Session, str | None]:
        """准备会话（恢复或创建）
        
        在处理请求前调用，检查是否需要恢复压缩的会话。
        如果会话已被归档，从摘要恢复上下文。
        
        Args:
            session: 当前会话对象
            key: 会话key
            
        Returns:
            (恢复后的会话对象, 摘要文本或None)
        """
        # 如果会话正在归档或已过期，重新加载
        if key in self._archiving or self._is_expired(session.updated_at):
            logger.info("Auto-compact: reloading session {} (archiving={})", key, key in self._archiving)
            session = self.sessions.get_or_create(key)
        
        # 优先从内存缓存获取摘要（进程未重启时）
        # 同时清理metadata副本，防止过期的_last_summary泄漏到磁盘
        entry = self._summaries.pop(key, None)
        if entry:
            session.metadata.pop("_last_summary", None)
            return session, self._format_summary(entry[0], entry[1])
        
        # 从metadata获取摘要（从磁盘加载）
        if "_last_summary" in session.metadata:
            meta = session.metadata.pop("_last_summary")
            self.sessions.save(session)
            return session, self._format_summary(meta["text"], datetime.fromisoformat(meta["last_active"]))
        return session, None