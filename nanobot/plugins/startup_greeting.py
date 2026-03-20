"""启动问候插件 - 网关启动时发送欢迎消息"""

import asyncio
from loguru import logger
from nanobot.bus.events import InboundMessage, SystemEvent
from nanobot.bus.queue import MessageBus


class StartupGreetingPlugin:
    """在网关就绪时发送问候消息的插件"""

    def __init__(self, config, bus: MessageBus, full_config):
        self.config = config
        self.bus = bus
        self.full_config = full_config
        self._sent = False

    async def on_gateway_ready(self, event: SystemEvent) -> None:
        """处理 gateway_ready 事件，发送问候消息"""
        if event.event_type != "gateway_ready":
            return
        if self._sent:
            return

        try:
            # 等待频道完全就绪
            await asyncio.sleep(self.config.delay_seconds)

            # 获取已启用的频道，并且只发送到配置了 chat_id 的频道
            enabled_channels = self._get_enabled_channels()
            targets = []
            for channel in enabled_channels:
                if channel in self.config.target_chat_ids:
                    targets.append((channel, self.config.target_chat_ids[channel]))

            # 作为入站消息发送（由 agent 处理）
            for channel, chat_id in targets:
                msg = InboundMessage(
                    channel=channel,
                    sender_id="system",
                    chat_id=chat_id,
                    content=self.config.system_prompt,
                    metadata={"source": "startup_greeting_plugin"},
                )
                await self.bus.publish_inbound(msg)
                logger.info("启动问候已发送到 {} (chat_id: {})", channel, chat_id)

            self._sent = True
        except Exception as e:
            logger.error("发送启动问候失败: {}", e)

    def _get_enabled_channels(self) -> list[str]:
        """从配置获取已启用的频道列表"""
        channels = []
        for name in ["telegram", "discord", "slack", "feishu", "dingtalk", "wecom"]:
            section = getattr(self.full_config.channels, name, None)
            if section:
                enabled = (
                    section.get("enabled", False)
                    if isinstance(section, dict)
                    else getattr(section, "enabled", False)
                )
                if enabled:
                    channels.append(name)
        return channels
