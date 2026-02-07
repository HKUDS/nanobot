"""Channel spawner: spawns each channel as a Pulsing actor by name.

Each channel is registered as ``channel.{name}``. Use
``(await pul.resolve(f"channel.{{name}}")).as_any()`` for p2p send_text.
"""

import asyncio
from typing import Any

from loguru import logger

from nanobot.config.schema import Config


async def spawn_channels(
    config: Config, agent_name: str = "agent"
) -> list[asyncio.Task[Any]]:
    """
    Spawn each enabled channel as its own Pulsing actor (channel.{name}).

    Returns a list of asyncio tasks running each channel's start() loop.
    """
    tasks: list[asyncio.Task[Any]] = []

    if config.channels.telegram.enabled:
        try:
            from nanobot.channels.telegram import TelegramChannel

            actor = await TelegramChannel.spawn(
                config=config.channels.telegram,
                agent_name=agent_name,
                groq_api_key=config.providers.groq.api_key or "",
                name="channel.telegram",
            )
            tasks.append(asyncio.create_task(actor.start()))
            logger.info("Spawned channel.telegram")
        except ImportError as e:
            logger.warning(f"Telegram channel not available: {e}")

    if config.channels.whatsapp.enabled:
        try:
            from nanobot.channels.whatsapp import WhatsAppChannel

            actor = await WhatsAppChannel.spawn(
                config=config.channels.whatsapp,
                agent_name=agent_name,
                name="channel.whatsapp",
            )
            tasks.append(asyncio.create_task(actor.start()))
            logger.info("Spawned channel.whatsapp")
        except ImportError as e:
            logger.warning(f"WhatsApp channel not available: {e}")

    if config.channels.discord.enabled:
        try:
            from nanobot.channels.discord import DiscordChannel

            actor = await DiscordChannel.spawn(
                config=config.channels.discord,
                agent_name=agent_name,
                name="channel.discord",
            )
            tasks.append(asyncio.create_task(actor.start()))
            logger.info("Spawned channel.discord")
        except ImportError as e:
            logger.warning(f"Discord channel not available: {e}")

    if config.channels.feishu.enabled:
        try:
            from nanobot.channels.feishu import FeishuChannel

            actor = await FeishuChannel.spawn(
                config=config.channels.feishu,
                agent_name=agent_name,
                name="channel.feishu",
            )
            tasks.append(asyncio.create_task(actor.start()))
            logger.info("Spawned channel.feishu")
        except ImportError as e:
            logger.warning(f"Feishu channel not available: {e}")

    return tasks
