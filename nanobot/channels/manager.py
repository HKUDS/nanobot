"""Channel spawner: spawns each channel as a Pulsing actor by name.

Each channel implementation (TelegramChannel, DiscordChannel, etc.) is an actor
registered as ``channel.{name}``. Resolve via get_channel_actor(name) for p2p send_text.
"""

import asyncio
from typing import Any

from loguru import logger

from nanobot.config.schema import Config


def _channel_classes() -> dict[str, Any]:
    """Lazy mapping name -> channel class (avoids importing all at once)."""
    classes: dict[str, Any] = {}
    try:
        from nanobot.channels.telegram import TelegramChannel
        classes["telegram"] = TelegramChannel
    except ImportError:
        pass
    try:
        from nanobot.channels.whatsapp import WhatsAppChannel
        classes["whatsapp"] = WhatsAppChannel
    except ImportError:
        pass
    try:
        from nanobot.channels.discord import DiscordChannel
        classes["discord"] = DiscordChannel
    except ImportError:
        pass
    try:
        from nanobot.channels.feishu import FeishuChannel
        classes["feishu"] = FeishuChannel
    except ImportError:
        pass
    return classes


async def get_channel_actor(name: str):
    """Resolve channel actor by name (e.g. 'discord' -> channel.discord)."""
    classes = _channel_classes()
    if name not in classes:
        raise ValueError(f"Unknown or unavailable channel: {name}")
    return await classes[name].resolve(f"channel.{name}")


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
