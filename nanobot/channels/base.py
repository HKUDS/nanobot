"""Base channel interface for chat platforms."""

# 模块作用：通道抽象基类，定义所有聊天通道的统一接口
# 设计目的：通过抽象类强制实现核心方法，保证通道一致性
# 好处：接口标准化，易于扩展新通道，多态处理
from abc import ABC, abstractmethod
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


# 作用：聊天通道抽象基类，定义通道必须实现的核心方法
# 设计目的：通过ABC强制实现标准接口，提供通用功能
# 好处：通道实现一致，易于测试，功能复用
class BaseChannel(ABC):
    """
    Abstract base class for chat channel implementations.
    
    Each channel (Telegram, Discord, etc.) should implement this interface
    to integrate with the nanobot message bus.
    """
    
    name: str = "base"
    
    # 作用：初始化通道基类，存储配置和消息总线
    # 设计目的：统一初始化逻辑，提供基础状态管理
    # 好处：配置集中管理，状态跟踪，减少重复代码
    def __init__(self, config: Any, bus: MessageBus):
        """
        Initialize the channel.
        
        Args:
            config: Channel-specific configuration.
            bus: The message bus for communication.
        """
        self.config = config
        self.bus = bus
        self._running = False
    
    # 作用：启动通道监听消息的抽象方法
    # 设计目的：强制实现连接建立和消息监听逻辑
    # 好处：统一启动流程，保证通道正确初始化
    @abstractmethod
    async def start(self) -> None:
        """
        Start the channel and begin listening for messages.
        
        This should be a long-running async task that:
        1. Connects to the chat platform
        2. Listens for incoming messages
        3. Forwards messages to the bus via _handle_message()
        """
        pass
    
    # 作用：停止通道并清理资源的抽象方法
    # 设计目的：强制实现资源释放和连接关闭逻辑
    # 好处：统一关闭流程，防止资源泄漏
    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources."""
        pass
    
    # 作用：发送消息到聊天平台的抽象方法
    # 设计目的：强制实现消息发送逻辑，适配不同平台API
    # 好处：统一发送接口，错误处理标准化
    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through this channel.
        
        Args:
            msg: The message to send.
        """
        pass
    
    # 作用：检查发送者是否有权限使用该通道
    # 设计目的：基于allow_list配置实现访问控制
    # 好处：灵活的权限管理，支持白名单，默认开放
    def is_allowed(self, sender_id: str) -> bool:
        """
        Check if a sender is allowed to use this bot.
        
        Args:
            sender_id: The sender's identifier.
        
        Returns:
            True if allowed, False otherwise.
        """
        allow_list = getattr(self.config, "allow_from", [])
        
        # If no allow list, allow everyone
        if not allow_list:
            return True
        
        sender_str = str(sender_id)
        if sender_str in allow_list:
            return True
        if "|" in sender_str:
            for part in sender_str.split("|"):
                if part and part in allow_list:
                    return True
        return False
    
    # 作用：处理来自聊天平台的入站消息
    # 设计目的：权限检查、消息封装、总线发布
    # 好处：统一消息处理流程，权限控制，错误日志
    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None
    ) -> None:
        """
        Handle an incoming message from the chat platform.
        
        This method checks permissions and forwards to the bus.
        
        Args:
            sender_id: The sender's identifier.
            chat_id: The chat/channel identifier.
            content: Message text content.
            media: Optional list of media URLs.
            metadata: Optional channel-specific metadata.
        """
        if not self.is_allowed(sender_id):
            logger.warning(
                f"Access denied for sender {sender_id} on channel {self.name}. "
                f"Add them to allowFrom list in config to grant access."
            )
            return
        
        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=metadata or {}
        )
        
        await self.bus.publish_inbound(msg)
    
    # 作用：检查通道是否正在运行的属性
    # 设计目的：提供运行状态查询，支持状态监控
    # 好处：统一的运行状态接口，便于管理
    @property
    def is_running(self) -> bool:
        """Check if the channel is running."""
        return self._running


# ============================================
# 示例说明：BaseChannel 使用示例
# ============================================
#
# 1. 实现新通道的步骤：
# ```python
# from nanobot.channels.base import BaseChannel
# from nanobot.bus.events import OutboundMessage
# from nanobot.bus.queue import MessageBus
# from typing import Any
# import asyncio
#
# class MyCustomChannel(BaseChannel):
#     """自定义聊天通道实现示例。"""
#     
#     name = "custom"  # 通道唯一标识
#     
#     def __init__(self, config: Any, bus: MessageBus):
#         super().__init__(config, bus)
#         self.api_key = config.api_key
#         self.webhook_url = config.webhook_url
#         self._client = None  # 平台客户端
#     
#     async def start(self) -> None:
#         """启动通道，连接到聊天平台。"""
#         # 1. 初始化客户端
#         self._client = CustomPlatformClient(self.api_key)
#         
#         # 2. 设置消息处理器
#         self._client.on_message = self._on_platform_message
#         
#         # 3. 连接到平台
#         await self._client.connect()
#         self._running = True
#         
#         # 4. 保持运行（通常是无限循环）
#         while self._running:
#             await asyncio.sleep(1)
#     
#     async def stop(self) -> None:
#         """停止通道，清理资源。"""
#         self._running = False
#         if self._client:
#             await self._client.disconnect()
#             self._client = None
#     
#     async def send(self, msg: OutboundMessage) -> None:
#         """发送消息到聊天平台。"""
#         try:
#             await self._client.send_message(
#                 chat_id=msg.chat_id,
#                 text=msg.content
#             )
#         except Exception as e:
#             logger.error(f"Failed to send message: {e}")
#             raise
#     
#     async def _on_platform_message(self, event: dict) -> None:
#         """处理来自平台的消息事件。"""
#         # 调用基类方法处理消息（权限检查、封装、发布）
#         await self._handle_message(
#             sender_id=event["user_id"],
#             chat_id=event["chat_id"],
#             content=event["text"],
#             metadata={"platform": "custom"}
#         )
# ```
#
# 2. 在 ChannelManager 中注册新通道：
# ```python
# # nanobot/channels/manager.py 的 _init_channels 方法中添加：
# def _init_channels(self) -> None:
#     # ... 现有通道初始化 ...
#     
#     # Custom channel
#     if self.config.channels.custom.enabled:
#         try:
#             from nanobot.channels.custom import MyCustomChannel
#             self.channels["custom"] = MyCustomChannel(
#                 self.config.channels.custom, self.bus
#             )
#             logger.info("Custom channel enabled")
#         except ImportError as e:
#             logger.warning(f"Custom channel not available: {e}")
# ```
#
# 3. 配置示例（config.toml）：
# ```toml
# [channels.custom]
# enabled = true
# api_key = "your-api-key"
# webhook_url = "https://api.custom-platform.com/webhook"
# allow_from = ["user1", "user2"]  # 可选的白名单
# ```
#
# 4. 权限控制工作原理：
# ```
# is_allowed(sender_id) 检查逻辑：
# 1. 获取配置中的 allow_from 列表
# 2. 如果列表为空，允许所有人访问
# 3. 检查 sender_id 是否在列表中
# 4. 支持复合ID（如 "telegram|user123"）分割检查
# 5. 拒绝未授权用户，记录警告日志
# ```
#
# 5. 消息处理流程：
# ```
# _handle_message() 执行步骤：
# 1. 权限检查：is_allowed(sender_id)
#    - 拒绝：记录日志，直接返回
#    - 允许：继续处理
# 2. 消息封装：创建 InboundMessage 对象
#    - channel: 通道名称
#    - sender_id: 发送者ID
#    - chat_id: 聊天ID（用于回复）
#    - content: 消息内容
#    - media: 媒体文件列表
#    - metadata: 额外元数据
# 3. 消息发布：bus.publish_inbound(msg)
#    - 发送到消息总线
#    - 等待智能体处理
# ```
#
# 6. 设计原则：
# - **单一职责**：每个通道只负责一个平台
# - **接口一致**：所有通道实现相同接口
# - **错误隔离**：单个通道失败不影响系统
# - **权限控制**：统一的白名单机制
# - **异步处理**：充分利用 asyncio 性能
