"""
TaskQueue Gateway 集成模块

在 nanobot gateway 启动时调用此函数来初始化任务队列：
    from scripts.task_queue_gateway import integrate_task_queue
    integrate_task_queue(agent, bus, config)

Author: nanobot
Date: 2026-03-08
"""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 任务队列模块路径
TASK_QUEUE_MODULE = "/home/aobo/.nanobot/workspace/scripts/task_queue.py"


def integrate_task_queue(agent, bus, config, channels=None):
    """
    将任务队列集成到 nanobot gateway
    
    Args:
        agent: AgentLoop 实例
        bus: MessageBus 实例
        config: Config 实例
        channels: ChannelManager 实例（可选）
    """
    import sys
    from pathlib import Path
    
    # 添加 nanobot 路径（确保可以导入 nanobot 模块）
    nanobot_path = Path(__file__).parent.parent / ".local/share/uv/tools/nanobot-ai/lib/python3.11/site-packages"
    if nanobot_path.exists():
        sys.path.insert(0, str(nanobot_path))
    
    sys.path.insert(0, str(Path(TASK_QUEUE_MODULE).parent))
    
    # 导入任务队列模块
    from task_queue import task_queue, TaskQueue
    
    # 设置 ChannelManager 和 MessageBus
    if channels:
        TaskQueue.set_channel_manager(channels)
        logger.info("TaskQueue 已集成 ChannelManager")
    
    TaskQueue.set_message_bus(bus)
    logger.info("TaskQueue 已集成 MessageBus")
    
    # 启动任务队列
    task_queue.start()
    logger.info("TaskQueue 已启动")
    
    # 注册任务处理器
    _register_task_handlers(task_queue, agent)
    
    return task_queue


def _register_task_handlers(task_queue, agent):
    """注册任务处理器"""
    
    def handle_agent_task(task_id: str, metadata: dict) -> dict:
        """处理需要 agent 执行的任务"""
        import asyncio
        
        message = metadata.get("message")
        channel = metadata.get("channel", "telegram")
        user_id = metadata.get("user_id")
        
        if not message:
            raise ValueError("缺少 message 参数")
        
        # 在 asyncio 事件循环中运行 agent
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(
                agent.process_direct(
                    message,
                    session_key=f"task:{task_id}",
                    channel=channel,
                    chat_id=user_id or "direct"
                )
            )
            return {"response": response, "message": message}
        finally:
            loop.close()
    
    # 注册 agent 任务处理器
    task_queue.register_handler("agent_task", handle_agent_task)
    
    # 注册通用命令处理器（已内置）
    # task_queue.register_handler("generic_command", ...)
    
    # 注册重启服务处理器（已内置）
    # task_queue.register_handler("restart_service", ...)
    
    logger.info("已注册任务处理器: agent_task, generic_command, restart_service")


def create_task_command(task_queue):
    """
    创建任务命令的便捷函数（供 CLI 使用）
    """
    def submit_and_notify(
        name: str,
        metadata: dict = None,
        user_id: str = None,
        channel: str = None,
        wait: bool = False,
        timeout: int = 60
    ):
        """
        提交任务并可选地等待结果
        
        Args:
            name: 任务名称
            metadata: 任务参数
            user_id: 用户ID（用于通知）
            channel: 通知渠道
            wait: 是否等待完成
            timeout: 等待超时（秒）
        
        Returns:
            task_id 或任务结果
        """
        import time
        
        task_id = task_queue.submit(
            name=name,
            metadata=metadata,
            user_id=user_id,
            channel=channel
        )
        
        if wait:
            start_time = time.time()
            while time.time() - start_time < timeout:
                task = task_queue.get_task(task_id)
                if task and task.status in ["completed", "failed"]:
                    return {
                        "task_id": task_id,
                        "status": task.status,
                        "result": task.result,
                        "error": task.error
                    }
                time.sleep(0.5)
            
            return {
                "task_id": task_id,
                "status": "timeout",
                "message": f"等待超时 ({timeout}秒)"
            }
        
        return {"task_id": task_id, "status": "queued"}
    
    return submit_and_notify


# ==================== 便捷调用 ====================

def submit_task(name: str, metadata: dict = None, user_id: str = None, 
                channel: str = None, wait: bool = False, timeout: int = 60):
    """
    提交任务的便捷函数
    
    用法:
        from scripts.task_queue_gateway import submit_task
        
        # 异步提交
        task_id = submit_task("agent_task", {"message": "你好"}, user_id="123")
        
        # 同步等待
        result = submit_task("agent_task", {"message": "你好"}, wait=True, timeout=30)
    """
    import sys
    from pathlib import Path
    
    # 动态导入
    sys.path.insert(0, str(Path(TASK_QUEUE_MODULE).parent))
    from task_queue import task_queue
    
    # 确保队列已启动
    if not task_queue._worker_thread or not task_queue._worker_thread.is_alive():
        task_queue.start()
    
    return create_task_command(task_queue)(name, metadata, user_id, channel, wait, timeout)


if __name__ == "__main__":
    # 测试导入
    print("TaskQueue Gateway 集成模块加载成功")
    print(f"模块路径: {TASK_QUEUE_MODULE}")
