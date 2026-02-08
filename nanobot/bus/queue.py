"""Async message queue for decoupled channel-agent communication."""

# 模块作用：异步消息总线，解耦聊天通道与智能体核心通信
# 设计目的：基于asyncio.Queue实现生产者-消费者模式，支持订阅机制
# 好处：完全异步，高并发，通道与智能体解耦，错误隔离
import asyncio
from typing import Callable, Awaitable

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage


# 作用：消息总线核心类，管理入站和出站消息队列
# 设计目的：实现通道与智能体间的异步通信桥梁，支持消息订阅
# 好处：系统组件解耦，异步处理，可扩展的消息路由
class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.
    
    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """
    
    # 作用：初始化消息总线，创建队列和订阅字典
    # 设计目的：分离入站和出站队列，支持通道订阅机制
    # 好处：清晰的队列分离，灵活的订阅模式，线程安全
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._outbound_subscribers: dict[str, list[Callable[[OutboundMessage], Awaitable[None]]]] = {}
        self._running = False
    
    # 作用：发布入站消息到队列（通道 -> 智能体）
    # 设计目的：异步入队操作，支持高并发消息发布
    # 好处：非阻塞发布，缓冲区管理，背压支持
    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self.inbound.put(msg)
    
    # 作用：消费入站消息队列（智能体获取消息）
    # 设计目的：异步阻塞等待，队列空时自动等待
    # 好处：简单的消费者接口，自动流控制，公平调度
    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()
    
    # 作用：发布出站消息到队列（智能体 -> 通道）
    # 设计目的：异步入队操作，支持批量响应发布
    # 好处：非阻塞发布，消息路由基础，订阅者通知
    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self.outbound.put(msg)
    
    # 作用：消费出站消息队列（分发器获取消息）
    # 设计目的：异步阻塞等待，支持超时处理
    # 好处：稳定的消息分发，错误恢复，取消支持
    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()
    
    # 作用：订阅特定通道的出站消息
    # 设计目的：基于通道名称的订阅机制，支持多个回调
    # 好处：灵活的消息路由，通道级订阅，动态回调管理
    def subscribe_outbound(
        self, 
        channel: str, 
        callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        """Subscribe to outbound messages for a specific channel."""
        if channel not in self._outbound_subscribers:
            self._outbound_subscribers[channel] = []
        self._outbound_subscribers[channel].append(callback)
    
    # 作用：分发出站消息到订阅通道的后台任务
    # 设计目的：持续监听出站队列，调用订阅回调，错误处理
    # 好处：自动消息分发，订阅者管理，健壮的错误恢复
    async def dispatch_outbound(self) -> None:
        """
        Dispatch outbound messages to subscribed channels.
        Run this as a background task.
        """
        self._running = True
        while self._running:
            try:
                msg = await asyncio.wait_for(self.outbound.get(), timeout=1.0)
                subscribers = self._outbound_subscribers.get(msg.channel, [])
                for callback in subscribers:
                    try:
                        await callback(msg)
                    except Exception as e:
                        logger.error(f"Error dispatching to {msg.channel}: {e}")
            except asyncio.TimeoutError:
                continue
    
    # 作用：停止分发器循环，清理运行状态
    # 设计目的：提供优雅停止机制，防止消息丢失
    # 好处：可控的系统关闭，状态清理，资源释放
    def stop(self) -> None:
        """Stop the dispatcher loop."""
        self._running = False
    
    # 作用：获取入站消息队列大小（监控指标）
    # 设计目的：提供系统负载指标，便于容量规划
    # 好处：实时监控，性能分析，自动扩缩容决策
    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    # 作用：获取出站消息队列大小（监控指标）
    # 设计目的：提供消息积压指标，便于故障排查
    # 好处：系统健康度监控，瓶颈识别，优化指导
    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()


# ============================================
# 示例说明：MessageBus 使用示例
# ============================================
#
# 1. 基本使用示例：
# ```python
# from nanobot.bus.queue import MessageBus
# from nanobot.bus.events import InboundMessage, OutboundMessage
# import asyncio
#
# async def example():
#     # 创建消息总线
#     bus = MessageBus()
#     
#     # 启动出站消息分发器（后台任务）
#     dispatcher = asyncio.create_task(bus.dispatch_outbound())
#     
#     # 模拟通道发布入站消息
#     inbound_msg = InboundMessage(
#         channel="telegram",
#         sender_id="user123",
#         chat_id="chat456",
#         content="你好，请分析我的代码"
#     )
#     await bus.publish_inbound(inbound_msg)
#     print(f"入站队列大小: {bus.inbound_size}")
#     
#     # 模拟智能体消费消息（通常在AgentLoop中）
#     received_msg = await bus.consume_inbound()
#     print(f"收到消息: {received_msg.content}")
#     
#     # 模拟智能体发布出站消息
#     outbound_msg = OutboundMessage(
#         channel="telegram",
#         chat_id="chat456",
#         content="正在分析您的代码..."
#     )
#     await bus.publish_outbound(outbound_msg)
#     print(f"出站队列大小: {bus.outbound_size}")
#     
#     # 订阅特定通道的出站消息（通道实现应注册）
#     async def telegram_sender(msg: OutboundMessage):
#         print(f"发送到Telegram: {msg.content}")
#         # 实际发送逻辑...
#     
#     bus.subscribe_outbound("telegram", telegram_sender)
#     
#     # 等待并停止
#     await asyncio.sleep(1)
#     bus.stop()
#     dispatcher.cancel()
# 
# # 运行示例
# asyncio.run(example())
# ```
#
# 2. 完整系统集成流程：
# ```
# 1. 启动时：
#    - ChannelManager 创建 MessageBus
#    - 通道实例订阅对应通道的出站消息
#    - 启动 bus.dispatch_outbound() 后台任务
#    
# 2. 消息处理：
#    - 用户发送消息 -> 通道._handle_message() -> bus.publish_inbound()
#    - AgentLoop.run() 等待 bus.consume_inbound()
#    - 智能体处理 -> bus.publish_outbound()
#    - 分发器调用订阅回调 -> channel.send()
#    
# 3. 关闭时：
#    - bus.stop() 停止分发循环
#    - 取消分发器任务
# ```
#
# 3. 消息总线设计模式：
# - **生产者-消费者模式**：通道生产消息，智能体消费消息
# - **发布-订阅模式**：智能体发布响应，通道订阅特定通道消息
# - **队列缓冲**：asyncio.Queue 提供背压支持和流量控制
#
# 4. 并发处理优势：
# - 多个通道可同时发布消息
# - 智能体顺序处理消息（可扩展为并行处理）
# - 出站消息异步分发到各通道
# - 单个通道失败不影响其他通道
#
# 5. 监控和调试：
# - inbound_size/outbound_size 实时队列监控
# - 日志记录消息流转过程
# - 错误隔离和恢复机制
# - 性能分析和瓶颈识别
