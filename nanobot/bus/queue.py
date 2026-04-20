"""Async message queue for decoupled channel-agent communication."""

import asyncio

from nanobot.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """异步消息总线 - 解耦聊天频道和代理核心
    
    这是一个基于 asyncio.Queue 的异步消息队列，用于实现发布-订阅模式：
    - 频道（Channel）将消息推入入站队列（inbound）
    - 代理（Agent）从入站队列消费消息，处理后推入出站队列（outbound）
    - 频道从出站队列获取响应并发送回用户
    
    架构：
    [Channel] --publish_inbound()--> [inbound queue] --consume_inbound()--> [Agent]
    [Agent] --publish_outbound()--> [outbound queue] --consume_outbound()--> [Channel]
    """

    def __init__(self):
        """初始化消息总线
        
        创建两个异步队列：
        - inbound: 接收来自频道的消息
        - outbound: 发送响应给频道
        """
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """发布入站消息（从频道发送到代理）
        
        频道调用此方法将用户消息放入队列。
        
        Args:
            msg: 入站消息对象
        """
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """消费下一个入站消息（阻塞直到有消息）
        
        代理调用此方法从队列获取用户消息。
        
        Returns:
            下一个入站消息
        """
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """发布出站消息（从代理发送到频道）
        
        代理处理完消息后调用此方法将响应放入队列。
        
        Args:
            msg: 出站消息对象
        """
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """消费下一个出站消息（阻塞直到有消息）
        
        频道调用此方法获取代理的响应。
        
        Returns:
            下一个出站消息
        """
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """获取待处理的入站消息数量
        
        Returns:
            入站队列中的消息数
        """
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """获取待处理的出站消息数量
        
        Returns:
            出站队列中的消息数
        """
        return self.outbound.qsize()