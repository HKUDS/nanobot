"""Channel spawner: creates channel instances and spawns them as Pulsing actors.

Each channel is registered as ``channel.{name}`` and can be resolved by any
actor for point-to-point message delivery.  Supervision is handled by
Pulsing's built-in ``restart_policy`` on ChannelActor.
"""

from typing import Any

from loguru import logger

from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Config
from nanobot.actor.names import DEFAULT_AGENT_NAME


def create_channels(
    config: Config, agent_name: str = DEFAULT_AGENT_NAME
) -> dict[str, BaseChannel]:
    """
    Instantiate all enabled channels from config.

    Returns a ``{name: channel_instance}`` dict.  Does NOT start or spawn them.
    """
    channels: dict[str, BaseChannel] = {}

    # Telegram
    if config.channels.telegram.enabled:
        try:
            from nanobot.channels.telegram import TelegramChannel

            channels["telegram"] = TelegramChannel(
                config.channels.telegram,
                agent_name=agent_name,
                groq_api_key=config.providers.groq.api_key,
            )
            logger.info("Telegram channel created")
        except ImportError as e:
            logger.warning(f"Telegram channel not available: {e}")

    # WhatsApp
    if config.channels.whatsapp.enabled:
        try:
            from nanobot.channels.whatsapp import WhatsAppChannel

            channels["whatsapp"] = WhatsAppChannel(
                config.channels.whatsapp,
                agent_name=agent_name,
            )
            logger.info("WhatsApp channel created")
        except ImportError as e:
            logger.warning(f"WhatsApp channel not available: {e}")

    # Discord
    if config.channels.discord.enabled:
        try:
            from nanobot.channels.discord import DiscordChannel

            channels["discord"] = DiscordChannel(
                config.channels.discord,
                agent_name=agent_name,
            )
            logger.info("Discord channel created")
        except ImportError as e:
            logger.warning(f"Discord channel not available: {e}")

    # Feishu
    if config.channels.feishu.enabled:
        try:
            from nanobot.channels.feishu import FeishuChannel

            channels["feishu"] = FeishuChannel(
                config.channels.feishu,
                agent_name=agent_name,
            )
            logger.info("Feishu channel created")
        except ImportError as e:
            logger.warning(f"Feishu channel not available: {e}")

    return channels


async def spawn_channel_actors(
    channels: dict[str, BaseChannel],
) -> list[Any]:
    """
    Spawn each channel as a ``ChannelActor`` Pulsing actor.

    Each actor is named ``channel.{name}`` (e.g. ``channel.discord``) so
    that any other actor can resolve it for point-to-point messaging.

    Supervision (auto-restart on failure) is built into ChannelActor via
    Pulsing's ``restart_policy="on-failure"``.

    Returns a list of running asyncio tasks (one per channel).
    """
    import asyncio
    from nanobot.actor.channel import ChannelActor
    from nanobot.actor.names import channel_actor_name

    tasks = []
    for name, channel in channels.items():
        actor = await ChannelActor.spawn(
            channel=channel,
            name=channel_actor_name(name),
        )
        task = asyncio.create_task(actor.run())
        logger.info(f"Spawned channel.{name}")
        tasks.append(task)

    return tasks
