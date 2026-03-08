"""
Task Queue System - 完整的任务队列系统
支持任务持久化、状态追踪、重启恢复、结果通知

Author: nanobot
Date: 2026-03-08
"""

import sqlite3
import json
import uuid
import threading
import time
import os
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, Callable, Any
from enum import Enum
import queue
import logging

# 配置
DATA_DIR = Path("/home/aobo/.nanobot/workspace/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_DB = DATA_DIR / "task_queue.db"
RESULTS_DIR = DATA_DIR / "task_results"
RESULTS_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"      # 待执行
    RUNNING = "running"      # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 已取消


@dataclass
class Task:
    """任务数据结构"""
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[str] = None  # JSON 字符串
    user_id: Optional[str] = None
    channel: Optional[str] = None


class TaskQueue:
    """任务队列管理器"""
    
    _instance = None
    _lock = threading.Lock()
    
    # 类级别的 channel_manager（由 nanobot gateway 设置）
    _channel_manager = None
    _message_bus = None
    
    @classmethod
    def set_channel_manager(cls, channel_manager):
        """设置 ChannelManager（由 gateway 调用）"""
        cls._channel_manager = channel_manager
        logger.info("TaskQueue 已绑定 ChannelManager")
    
    @classmethod
    def set_message_bus(cls, message_bus):
        """设置 MessageBus（由 gateway 调用）"""
        cls._message_bus = message_bus
        logger.info("TaskQueue 已绑定 MessageBus")
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._conn = None
        self._worker_thread = None
        self._stop_event = threading.Event()
        self._task_queue = queue.Queue()
        self._handlers = {}  # task_name -> handler function
        self._callbacks = {}  # task_id -> callback function
        
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        self._conn = sqlite3.connect(str(QUEUE_DB), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        
        # 创建任务表
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                result TEXT,
                error TEXT,
                metadata TEXT,
                user_id TEXT,
                channel TEXT
            )
        """)
        
        # 创建索引
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_name ON tasks(name)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)
        """)
        
        self._conn.commit()
        logger.info("TaskQueue 数据库初始化完成")
    
    def submit(
        self,
        name: str,
        metadata: dict = None,
        user_id: str = None,
        channel: str = None,
        callback: Callable = None
    ) -> str:
        """
        提交任务
        
        Args:
            name: 任务名称
            metadata: 任务参数
            user_id: 用户ID（用于通知）
            channel: 通知渠道
            callback: 完成后回调函数
        
        Returns:
            task_id
        """
        task_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        
        task = Task(
            id=task_id,
            name=name,
            status=TaskStatus.PENDING.value,
            created_at=now,
            updated_at=now,
            metadata=json.dumps(metadata) if metadata else None,
            user_id=user_id,
            channel=channel
        )
        
        self._conn.execute("""
            INSERT INTO tasks (id, name, status, created_at, updated_at, metadata, user_id, channel)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (task.id, task.name, task.status, task.created_at, task.updated_at, 
              task.metadata, task.user_id, task.channel))
        self._conn.commit()
        
        # 注册回调
        if callback:
            self._callbacks[task_id] = callback
        
        # 加入执行队列
        self._task_queue.put(task_id)
        
        logger.info(f"任务已提交: {task_id} ({name})")
        return task_id
    
    def register_handler(self, name: str, handler: Callable):
        """注册任务处理器"""
        self._handlers[name] = handler
        logger.info(f"已注册任务处理器: {name}")
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务信息"""
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        
        if row:
            return Task(**dict(row))
        return None
    
    def get_tasks_by_status(self, status: str) -> list:
        """按状态查询任务"""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
        return [Task(**dict(row)) for row in rows]
    
    def get_tasks_by_user(self, user_id: str, limit: int = 20) -> list:
        """查询用户的任务"""
        rows = self._conn.execute(
            """SELECT * FROM tasks WHERE user_id = ? 
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        return [Task(**dict(row)) for row in rows]
    
    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        task = self.get_task(task_id)
        if not task:
            return False
        
        if task.status in [TaskStatus.PENDING.value, TaskStatus.RUNNING.value]:
            self._conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (TaskStatus.CANCELLED.value, datetime.now().isoformat(), task_id)
            )
            self._conn.commit()
            return True
        return False
    
    def _update_status(self, task_id: str, status: TaskStatus, 
                       result: str = None, error: str = None):
        """更新任务状态"""
        now = datetime.now().isoformat()
        
        if status == TaskStatus.RUNNING:
            self._conn.execute("""
                UPDATE tasks SET status = ?, updated_at = ?, started_at = ?
                WHERE id = ?
            """, (status.value, now, now, task_id))
        elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
            self._conn.execute("""
                UPDATE tasks SET status = ?, updated_at = ?, completed_at = ?,
                result = ?, error = ? WHERE id = ?
            """, (status.value, now, now, result, error, task_id))
        else:
            self._conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, task_id)
            )
        
        self._conn.commit()
    
    def _process_task(self, task_id: str) -> Any:
        """处理单个任务"""
        task = self.get_task(task_id)
        if not task:
            logger.warning(f"任务不存在: {task_id}")
            return
        
        # 检查处理器是否存在
        if task.name not in self._handlers:
            error = f"未找到任务处理器: {task.name}"
            self._update_status(task_id, TaskStatus.FAILED, error=error)
            logger.error(error)
            return
        
        # 更新状态为运行中
        self._update_status(task_id, TaskStatus.RUNNING)
        
        try:
            # 获取任务参数
            metadata = json.loads(task.metadata) if task.metadata else {}
            
            # 执行处理器
            handler = self._handlers[task.name]
            result = handler(task_id, metadata)
            
            # 保存结果
            result_str = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
            self._update_status(task_id, TaskStatus.COMPLETED, result=result_str)
            
            # 触发回调
            if task_id in self._callbacks:
                try:
                    self._callbacks[task_id](task, result)
                except Exception as e:
                    logger.error(f"回调执行失败: {e}")
                del self._callbacks[task_id]
            
            # 发送通知
            self._notify_user(task, result)
            
            logger.info(f"任务完成: {task_id} ({task.name})")
            return result
            
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            self._update_status(task_id, TaskStatus.FAILED, error=error_msg)
            logger.error(f"任务失败: {task_id} - {error_msg}")
            
            # 发送失败通知
            self._notify_user(task, None, error=error_msg)
            return None
    
    def _notify_user(self, task: Task, result: Any = None, error: str = None):
        """通知用户任务结果"""
        if not task.user_id:
            return
        
        # 优先使用 ChannelManager
        if TaskQueue._channel_manager:
            self._notify_via_channel_manager(task, result, error)
        else:
            # 后备：直接使用 Bot API
            self._notify_via_api(task, result, error)
    
    def _notify_via_channel_manager(self, task: Task, result: Any = None, error: str = None):
        """通过 ChannelManager 发送通知"""
        channel_name = task.channel or "telegram"
        
        if error:
            content = f"❌ 任务失败\n\n任务: {task.name}\nID: {task.id}\n错误: {error}"
        else:
            content = f"✅ 任务完成\n\n任务: {task.name}\nID: {task.id}\n结果: {result}"
        
        # 获取 channel 实例
        channel = TaskQueue._channel_manager.get_channel(channel_name) if TaskQueue._channel_manager else None
        
        if channel:
            # 直接调用 channel.send() - 它是异步的，需要在线程中运行
            import asyncio
            try:
                # 获取或创建事件循环
                try:
                    loop = asyncio.get_running_loop()
                    # 已有运行中的循环，在新线程中执行
                    import threading
                    def _send():
                        asyncio.run(self._async_send(channel, channel_name, task.user_id, content))
                    threading.Thread(target=_send, daemon=True).start()
                except RuntimeError:
                    # 没有运行中的循环，可以直接使用 asyncio.run
                    asyncio.run(self._async_send(channel, channel_name, task.user_id, content))
            except Exception as e:
                logger.error(f"Channel 发送失败: {e}")
                # 后备方案
                self._notify_via_api(task, result, error)
        else:
            logger.warning(f"Channel {channel_name} 未找到，使用 API 后备")
            self._notify_via_api(task, result, error)
    
    async def _async_send(self, channel, channel_name: str, chat_id: str, content: str):
        """异步发送消息"""
        from nanobot.bus.events import OutboundMessage
        msg = OutboundMessage(
            channel=channel_name,
            chat_id=chat_id,
            content=content
        )
        await channel.send(msg)
        logger.info(f"通知已发送: {channel_name}:{chat_id}")
    
    def _notify_via_api(self, task: Task, result: Any = None, error: str = None):
        """通过 Telegram Bot API 发送消息（后备方案）"""
        import requests
        import os
        
        # 从环境变量获取 Bot Token
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            logger.warning("未配置 TELEGRAM_BOT_TOKEN，跳过通知")
            return
        
        if error:
            content = f"❌ 任务失败\n\n任务: {task.name}\nID: {task.id}\n错误: {error}"
        else:
            content = f"✅ 任务完成\n\n任务: {task.name}\nID: {task.id}\n结果: {result}"
        
        # 只有 Telegram 支持 Bot API
        if task.channel == "telegram" or not task.channel:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                "chat_id": task.user_id,
                "text": content,
                "parse_mode": "Markdown"
            }
            
            try:
                response = requests.post(url, json=data, timeout=10)
                if response.status_code != 200:
                    logger.error(f"Telegram API 错误: {response.text}")
                else:
                    logger.info(f"通知已发送 (API): {task.user_id}")
            except Exception as e:
                logger.error(f"API 通知失败: {e}")
        else:
            logger.warning(f"渠道 {task.channel} 不支持直接 API 通知")
    
    def _worker_loop(self):
        """工作线程主循环"""
        logger.info("TaskQueue 工作线程启动")
        
        while not self._stop_event.is_set():
            try:
                # 从队列获取任务（带超时以便检查停止事件）
                task_id = self._task_queue.get(timeout=1)
                
                # 处理任务
                self._process_task(task_id)
                
                self._task_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"工作线程错误: {e}")
        
        logger.info("TaskQueue 工作线程停止")
    
    def start(self):
        """启动任务队列"""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        
        # 恢复未完成的任务
        self._recover_pending()
        
        logger.info("TaskQueue 已启动")
    
    def stop(self):
        """停止任务队列"""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        logger.info("TaskQueue 已停止")
    
    def _recover_pending(self):
        """恢复未完成的任务"""
        # 查找所有 pending 和 running 状态的任务
        rows = self._conn.execute("""
            SELECT id FROM tasks 
            WHERE status IN (?, ?)
            ORDER BY created_at
        """, (TaskStatus.PENDING.value, TaskStatus.RUNNING.value)).fetchall()
        
        for row in rows:
            task_id = row[0]
            # 重新设置为 pending 并加入队列
            self._conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (TaskStatus.PENDING.value, datetime.now().isoformat(), task_id)
            )
            self._task_queue.put(task_id)
            logger.info(f"已恢复任务: {task_id}")
        
        self._conn.commit()
        
        if rows:
            logger.info(f"已恢复 {len(rows)} 个未完成任务")
    
    def get_stats(self) -> dict:
        """获取队列统计"""
        stats = {}
        for status in TaskStatus:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = ?",
                (status.value,)
            ).fetchone()[0]
            stats[status.value] = count
        
        stats["queue_size"] = self._task_queue.qsize()
        return stats
    
    def cleanup(self, days: int = 30):
        """清理旧任务"""
        from datetime import timedelta
        
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM tasks WHERE completed_at < ? AND status IN (?, ?)",
            (cutoff, TaskStatus.COMPLETED.value, TaskStatus.FAILED.value)
        )
        self._conn.commit()
        
        deleted = cursor.rowcount
        if deleted:
            logger.info(f"已清理 {deleted} 个旧任务")
        return deleted


# 全局单例
task_queue = TaskQueue()


# ==================== 便捷函数 ====================

def submit_task(name: str, metadata: dict = None, user_id: str = None, 
                channel: str = None) -> str:
    """提交任务的便捷函数"""
    return task_queue.submit(name, metadata, user_id, channel)


def get_task_status(task_id: str) -> Optional[Task]:
    """获取任务状态"""
    return task_queue.get_task(task_id)


def list_tasks(user_id: str = None, status: str = None, limit: int = 20) -> list:
    """列出任务"""
    if status:
        return task_queue.get_tasks_by_status(status)
    elif user_id:
        return task_queue.get_tasks_by_user(user_id, limit)
    else:
        # 返回最近的任务
        rows = task_queue._conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Task(**dict(row)) for row in rows]


# ==================== 内置任务类型 ====================

def handle_restart_service(task_id: str, metadata: dict) -> dict:
    """处理服务重启任务"""
    import subprocess
    
    service = metadata.get("service", "nanobot")
    
    # 保存状态到文件（用于重启后检查）
    status_file = DATA_DIR / f"restart_{task_id}.json"
    status_file.write_text(json.dumps({
        "task_id": task_id,
        "service": service,
        "status": "starting"
    }))
    
    # 执行重启
    try:
        subprocess.run(["sudo", "systemctl", "restart", service], check=True)
        time.sleep(3)  # 等待服务启动
        
        # 更新状态文件
        status_file.write_text(json.dumps({
            "task_id": task_id,
            "service": service,
            "status": "completed"
        }))
        
        return {"service": service, "status": "restarted"}
        
    except subprocess.CalledProcessError as e:
        status_file.write_text(json.dumps({
            "task_id": task_id,
            "service": service,
            "status": "failed",
            "error": str(e)
        }))
        raise


def handle_generic_command(task_id: str, metadata: dict) -> dict:
    """处理通用命令任务"""
    import subprocess
    
    command = metadata.get("command")
    timeout = metadata.get("timeout", 60)
    
    if not command:
        raise ValueError("缺少 command 参数")
    
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout[:5000],  # 限制输出长度
        "stderr": result.stderr[:5000]
    }


# 注册内置处理器
def register_builtin_handlers():
    """注册内置任务处理器"""
    task_queue.register_handler("restart_service", handle_restart_service)
    task_queue.register_handler("generic_command", handle_generic_command)


# 启动时自动注册
register_builtin_handlers()


if __name__ == "__main__":
    # 测试代码
    print("=== TaskQueue 测试 ===")
    
    # 启动队列
    task_queue.start()
    
    # 提交测试任务
    task_id = submit_task(
        name="test_task",
        metadata={"message": "Hello World"},
        user_id="test_user"
    )
    print(f"提交任务: {task_id}")
    
    # 查询状态
    time.sleep(1)
    task = get_task_status(task_id)
    print(f"任务状态: {task.status if task else 'Not found'}")
    
    # 查看统计
    print(f"统计: {task_queue.get_stats()}")
    
    print("测试完成")
