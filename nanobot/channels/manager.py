"""Channel manager for coordinating chat channels."""

# 模块作用：通道管理器，协调多个聊天通道的启动、停止和消息路由
# 设计目的：统一管理不同聊天平台集成，提供一致的生命周期管理
# 好处：通道解耦，动态启用/禁用，错误隔离，统一状态监控
import asyncio
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Config


# 作用：通道管理器核心类，管理所有聊天通道的生命周期
# 设计目的：基于配置动态初始化通道，提供统一启动/停止接口
# 好处：配置驱动，插件式架构，通道间完全隔离
class ChannelManager:
    """
    Manages chat channels and coordinates message routing.
    
    Responsibilities:
    - Initialize enabled channels (Telegram, WhatsApp, etc.)
    - Start/stop channels
    - Route outbound messages
    """
    
    # 作用：初始化通道管理器，基于配置加载启用通道
    # 设计目的：延迟导入通道实现，优雅处理缺失依赖
    # 好处：配置即代码，依赖可选，启动时错误检测
    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        
        self._init_channels()
    
    # 作用：根据配置初始化所有启用的通道
    # 设计目的：遍历配置通道，动态导入实现类，错误处理
    # 好处：模块化通道加载，依赖缺失不影响其他通道
    def _init_channels(self) -> None:
        """Initialize channels based on config."""
        
        # Telegram channel
        if self.config.channels.telegram.enabled:
            try:
                from nanobot.channels.telegram import TelegramChannel
                self.channels["telegram"] = TelegramChannel(
                    self.config.channels.telegram,
                    self.bus,
                    groq_api_key=self.config.providers.groq.api_key,
                )
                logger.info("Telegram channel enabled")
            except ImportError as e:
                logger.warning(f"Telegram channel not available: {e}")
        
        # WhatsApp channel
        if self.config.channels.whatsapp.enabled:
            try:
                from nanobot.channels.whatsapp import WhatsAppChannel
                self.channels["whatsapp"] = WhatsAppChannel(
                    self.config.channels.whatsapp, self.bus
                )
                logger.info("WhatsApp channel enabled")
            except ImportError as e:
                logger.warning(f"WhatsApp channel not available: {e}")

        # Discord channel
        if self.config.channels.discord.enabled:
            try:
                from nanobot.channels.discord import DiscordChannel
                self.channels["discord"] = DiscordChannel(
                    self.config.channels.discord, self.bus
                )
                logger.info("Discord channel enabled")
            except ImportError as e:
                logger.warning(f"Discord channel not available: {e}")
        
        # Feishu channel
        if self.config.channels.feishu.enabled:
            try:
                from nanobot.channels.feishu import FeishuChannel
                self.channels["feishu"] = FeishuChannel(
                    self.config.channels.feishu, self.bus
                )
                logger.info("Feishu channel enabled")
            except ImportError as e:
                logger.warning(f"Feishu channel not available: {e}")
    
    # 作用：启动单个通道，包装异常处理
    # 设计目的：隔离通道启动错误，防止单个通道失败影响整体
    # 好处：健壮的启动过程，详细错误日志
    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception as e:
            logger.error(f"Failed to start channel {name}: {e}")

    # 作用：启动所有通道和出站消息分发器
    # 设计目的：并行启动通道，创建后台分发任务
    # 好处：系统完全启动，异步消息处理，高并发支持
    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        if not self.channels:
            logger.warning("No channels enabled")
            return
        
        # Start outbound dispatcher
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
        
        # Start channels
        tasks = []
        for name, channel in self.channels.items():
            logger.info(f"Starting {name} channel...")
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))
        
        # Wait for all to complete (they should run forever)
        await asyncio.gather(*tasks, return_exceptions=True)
    
    # 作用：停止所有通道和分发器，清理资源
    # 设计目的：优雅关闭，任务取消，异常处理
    # 好处：干净的系统关闭，资源释放，防止内存泄漏
    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
        logger.info("Stopping all channels...")
        
        # Stop dispatcher
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        
        # Stop all channels
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info(f"Stopped {name} channel")
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")
    
    # 作用：分发出站消息到对应通道的后台任务
    # 设计目的：持续监听出站队列，路由消息，错误处理
    # 好处：异步消息路由，通道解耦，发送失败不影响系统
    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")
        
        while True:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0
                )
                
                channel = self.channels.get(msg.channel)
                if channel:
                    try:
                        await channel.send(msg)
                    except Exception as e:
                        logger.error(f"Error sending to {msg.channel}: {e}")
                else:
                    logger.warning(f"Unknown channel: {msg.channel}")
                    
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
    
    # 作用：按名称获取通道实例
    # 设计目的：提供通道访问接口，支持动态通道查找
    # 好处：灵活的通道访问，支持运行时通道管理
    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a channel by name."""
        return self.channels.get(name)
    
    # 作用：获取所有通道的状态信息
    # 设计目的：统一状态报告格式，便于监控和调试
    # 好处：系统状态可视化，故障诊断支持
    def get_status(self) -> dict[str, Any]:
        """Get status of all channels."""
        return {
            name: {
                "enabled": True,
                "running": channel.is_running
            }
            for name, channel in self.channels.items()
        }
    
    # 作用：获取已启用通道的名称列表
    # 设计目的：提供只读属性访问当前活跃通道
    # 好处：便捷的通道枚举，配置验证
    @property
    def enabled_channels(self) -> list[str]:
        """Get list of enabled channel names."""
        return list(self.channels.keys())


# ============================================
# 示例说明：ChannelManager 使用示例
# ============================================
#
# 1. 配置示例（config.toml）：
# ```toml
# [channels.telegram]
# enabled = true
# bot_token = "YOUR_BOT_TOKEN"
# allow_from = ["user123", "user456"]
#
# [channels.discord]
# enabled = true
# bot_token = "YOUR_DISCORD_TOKEN"
#
# [channels.whatsapp]
# enabled = false  # 未启用
#
# [channels.feishu]
# enabled = true
# app_id = "your_app_id"
# app_secret = "your_app_secret"
# ```
#
# 2. 基本使用示例：
# ```python
# from nanobot.channels.manager import ChannelManager
# from nanobot.config.loader import load_config
# from nanobot.bus.queue import MessageBus
# import asyncio
#
# async def example():
#     # 加载配置
#     config = load_config("config.toml")
#     
#     # 创建消息总线
#     bus = MessageBus()
#     
#     # 创建通道管理器
#     manager = ChannelManager(config, bus)
#     
#     # 启动所有通道
#     await manager.start_all()
#     print(f"已启动通道: {manager.enabled_channels}")
#     
#     # 获取通道状态
#     status = manager.get_status()
#     for name, info in status.items():
#         print(f"{name}: 启用={info['enabled']}, 运行中={info['running']}")
#     
#     # 获取特定通道
#     telegram_channel = manager.get_channel("telegram")
#     if telegram_channel:
#         print(f"Telegram通道运行状态: {telegram_channel.is_running}")
#     
#     # 运行一段时间后停止
#     await asyncio.sleep(10)
#     await manager.stop_all()
#     print("所有通道已停止")
# 
# # 运行示例
# asyncio.run(example())
# ```
#
# 3. 消息路由流程：
# ```
# 1. 通道接收用户消息 -> _handle_message() -> bus.publish_inbound()
# 2. 智能体处理消息 -> bus.publish_outbound() -> 出站队列
# 3. _dispatch_outbound() 后台任务：
#    - 从出站队列获取消息
#    - 查找对应通道
#    - 调用 channel.send(msg)
#    - 错误处理并记录日志
# ```
#
# 4. 通道初始化逻辑：
# ```
# 1. 检查配置中每个通道的 enabled 标志
# 2. 动态导入对应通道模块（try/except ImportError）
# 3. 实例化通道类，传入配置和消息总线
# 4. 添加到 channels 字典
# 5. 记录日志（成功启用或警告）
# ```
#
# 5. 错误处理策略：
# - 导入失败：记录警告，继续初始化其他通道
# - 启动失败：记录错误，不影响其他通道
# - 发送失败：记录错误，继续处理下条消息
# - 配置错误：使用默认值或跳过
#
# 6. 扩展新通道步骤：
# 1. 在 nanobot/channels/ 下创建新通道类，继承 BaseChannel
# 2. 实现 start(), stop(), send() 抽象方法
# 3. 在配置模式中添加对应配置节
# 4. 在 _init_channels() 中添加初始化逻辑
# 5. 通道自动被管理器加载和管理
