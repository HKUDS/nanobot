"""Event types for the message bus."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class InboundMessage:
    """收到的聊天消息（从频道到代理）
    
    这是用户通过各种聊天频道发送的消息的数据结构。
    消息会从入站队列传递给代理进行处理。
    
    属性说明：
    - channel: 频道类型 (telegram, discord, slack, whatsapp 等)
    - sender_id: 发送者ID（用户标识）
    - chat_id: 聊天/频道ID（用于标识会话）
    - content: 消息文本内容
    - timestamp: 消息时间戳
    - media: 媒体文件URL列表（图片、语音等）
    - metadata: 频道特定数据（如telegram的message_id）
    - session_key_override: 可选的会话key覆盖（用于线程范围会话）
    """

    channel: str  # telegram, discord, slack, whatsapp
    sender_id: str  # 用户标识
    chat_id: str  # 聊天/频道标识
    content: str  # 消息文本
    timestamp: datetime = field(default_factory=datetime.now)  # 时间戳
    media: list[str] = field(default_factory=list)  # 媒体URL列表
    metadata: dict[str, Any] = field(default_factory=dict)  # 频道特定数据
    session_key_override: str | None = None  # 可选的会话key覆盖

    @property
    def session_key(self) -> str:
        """获取会话唯一标识key
        
        如果设置了session_key_override，使用覆盖值；
        否则使用 channel:chat_id 格式。
        
        Returns:
            格式: "channel:chat_id" 或自定义override
        """
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """发送的聊天消息（从代理到频道）
    
    这是代理处理完用户消息后生成的响应数据结构。
    消息会从出站队列传递给频道进行发送。
    
    属性说明：
    - channel: 目标频道类型
    - chat_id: 目标聊天/频道ID
    - content: 响应文本内容
    - reply_to: 可选的回复目标（回复特定消息的ID）
    - media: 媒体文件URL列表（可包含本地文件路径）
    - metadata: 频道特定数据（如telegram的parse_mode）
    """

    channel: str  # 目标频道类型
    chat_id: str  # 目标聊天ID
    content: str  # 响应文本
    reply_to: str | None = None  # 回复目标消息ID
    media: list[str] = field(default_factory=list)  # 媒体文件列表
    metadata: dict[str, Any] = field(default_factory=dict)  # 频道特定数据