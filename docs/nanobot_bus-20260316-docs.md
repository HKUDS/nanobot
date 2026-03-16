# Project Documentation

- **Generated at:** 2026-03-16 23:10:25
- **Root Dir:** `nanobot/bus`
- **File Count:** 3
- **Total Size:** 2.81 KB

claude 解读：
*Thinking...*

> The user wants me to explain the code in detail. The document is in Chinese (the TOC and summary sections are in Chinese), so I should respond in Chinese.
> 
> Let me analyze the code structure and explain each file.

# `nanobot/bus` 模块详细解读

## 整体架构思想

这个模块实现了一个**异步消息总线（Message Bus）**，核心目的是将**聊天渠道**（Telegram、Discord、Slack、WhatsApp 等）与**智能体（Agent）核心逻辑**进行解耦。

这是一种经典的**生产者-消费者**模式：聊天渠道作为生产者将用户消息投入队列，智能体作为消费者从队列中取出消息进行处理，处理完毕后再将回复投入另一个队列，由对应的渠道消费并发送给用户。这种设计的好处是，无论接入多少种聊天平台，Agent 核心只需要面对统一的消息格式，不必关心消息来自哪里、怎么发送回去。

---

## 📄 `events.py` —— 消息事件定义

这个文件定义了在总线上流转的两种消息类型，它们是整个系统的"通用语言"。

### `InboundMessage`（入站消息）

这是从用户端到智能体方向的消息，代表"用户说了一句话"。使用 `@dataclass` 装饰器，让 Python 自动生成 `__init__`、`__repr__` 等方法，减少样板代码。

各字段含义如下：`channel` 标识消息来源平台（如 `"telegram"`）；`sender_id` 是用户的唯一标识；`chat_id` 是对话/群组的唯一标识；`content` 是消息文本正文；`timestamp` 是消息创建时间，默认取当前时间；`media` 是一个字符串列表，存放随消息附带的媒体文件 URL（如图片、语音）；`metadata` 是一个字典，用于携带各平台特有的额外数据（比如 Telegram 的 `message_id`、Discord 的 `guild_id` 等），提供了良好的可扩展性；`session_key_override` 允许调用方手动指定会话键，覆盖默认的生成逻辑。

其中 `session_key` 属性值得关注。它的逻辑是：如果调用方设置了 `session_key_override`，就直接使用它；否则自动拼接为 `"{channel}:{chat_id}"` 的形式。这个键的用途是在下游做**会话管理**——同一个 `session_key` 的消息会被路由到同一个会话上下文中，Agent 就能维持对话的连贯性。`override` 机制则提供了灵活性，比如在同一个群聊中可以按线程（thread）粒度拆分会话。

### `OutboundMessage`（出站消息）

这是从智能体到用户端方向的消息，代表"Agent 要回复一句话"。字段相对简单：`channel` 和 `chat_id` 指明要发往哪个平台的哪个对话；`content` 是回复文本；`reply_to` 是可选的，用于标记这条回复是针对哪条原始消息（某些平台支持"引用回复"功能）；`media` 和 `metadata` 的含义与入站消息对称。

注意出站消息没有 `sender_id`，因为发送者永远是 Agent 自身，无需标识。

---

## 📄 `queue.py` —— 消息总线实现

`MessageBus` 类是整个模块的核心组件，内部维护了两条独立的 `asyncio.Queue`。

`inbound` 队列承载入站消息流（渠道 → Agent），`outbound` 队列承载出站消息流（Agent → 渠道）。选择 `asyncio.Queue` 而不是普通队列，是因为整个系统运行在异步事件循环中，`asyncio.Queue` 天然支持 `await`，在队列为空时会挂起协程而非阻塞线程，非常适合高并发的 IO 密集型场景。

四个核心方法构成两对对称操作：`publish_inbound` / `consume_inbound` 操作入站队列，`publish_outbound` / `consume_outbound` 操作出站队列。`publish` 方法调用 `queue.put()` 将消息放入队列；`consume` 方法调用 `queue.get()` 从队列中取出消息，如果队列为空则异步阻塞等待直到有新消息到来。

`inbound_size` 和 `outbound_size` 两个属性用于监控，可以随时查看两个队列中积压了多少条待处理消息，便于做健康检查或背压（backpressure）控制。

---

## 📄 `__init__.py` —— 模块导出

这个文件做了两件事：一是从子模块中导入三个核心类，二是通过 `__all__` 显式声明公开 API。这样外部代码只需写 `from nanobot.bus import MessageBus, InboundMessage, OutboundMessage`，无需关心内部文件结构。

---

## 典型数据流

整个工作流程可以概括为：某个聊天平台的适配器（如 Telegram Bot）收到用户消息后，将其封装为 `InboundMessage`，调用 `bus.publish_inbound()` 投入总线；Agent 核心在另一侧通过 `bus.consume_inbound()` 不断监听并取出消息进行处理（调用大模型、查知识库等）；处理完毕后将结果封装为 `OutboundMessage`，调用 `bus.publish_outbound()` 投入出站队列；对应平台的适配器再通过 `bus.consume_outbound()` 取出回复，调用平台 API 发送给用户。

这种设计使得新增一个聊天平台只需要编写一个适配器，实现"收消息→封装→投入总线"和"从总线取回复→调用平台 API 发送"两个方向的逻辑即可，Agent 核心代码完全不用改动。

<a name="toc"></a>
## 📂 扫描目录
- [__init__.py](#📄-__init__py) (6 lines, 0.23 KB)
- [events.py](#📄-eventspy) (38 lines, 1.12 KB)
- [queue.py](#📄-queuepy) (44 lines, 1.46 KB)

---

## 📄 __init__.py

````python
"""Message bus module for decoupled channel-agent communication."""

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]

````

[⬆ 回到目录](#toc)

## 📄 events.py

````python
"""Event types for the message bus."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class InboundMessage:
    """Message received from a chat channel."""

    channel: str  # telegram, discord, slack, whatsapp
    sender_id: str  # User identifier
    chat_id: str  # Chat/channel identifier
    content: str  # Message text
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)  # Media URLs
    metadata: dict[str, Any] = field(default_factory=dict)  # Channel-specific data
    session_key_override: str | None = None  # Optional override for thread-scoped sessions

    @property
    def session_key(self) -> str:
        """Unique key for session identification."""
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """Message to send to a chat channel."""

    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)



````

[⬆ 回到目录](#toc)

## 📄 queue.py

````python
"""Async message queue for decoupled channel-agent communication."""

import asyncio

from nanobot.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()

````

[⬆ 回到目录](#toc)

---
### 📊 最终统计汇总
- **文件总数:** 3
- **代码总行数:** 88
- **物理总大小:** 2.81 KB
