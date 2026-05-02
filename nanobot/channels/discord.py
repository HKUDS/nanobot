"""Discord channel implementation using discord.py."""

from __future__ import annotations

import asyncio
import importlib.util
import time
import uuid
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.command.builtin import build_help_text
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.utils.helpers import safe_filename, split_message

DISCORD_AVAILABLE = importlib.util.find_spec("discord") is not None
if TYPE_CHECKING:
    import aiohttp
    import discord
    from discord import app_commands
    from discord.abc import Messageable

if DISCORD_AVAILABLE:
    import discord
    from discord import app_commands
    from discord.abc import Messageable

    _BUTTON_STYLES = {
        "primary": discord.ButtonStyle.primary,
        "secondary": discord.ButtonStyle.secondary,
        "success": discord.ButtonStyle.success,
        "danger": discord.ButtonStyle.danger,
    }
    _TEXT_INPUT_STYLES = {
        "short": discord.TextStyle.short,
        "paragraph": discord.TextStyle.paragraph,
    }

    # discord.py 2.6 added Label + Select-in-modal; 2.7 added RadioGroup + CheckboxGroup.
    # Feature-detect so older discord.py installs still work for plain TextInput modals.
    _MODAL_LABEL = getattr(discord.ui, "Label", None)
    _MODAL_RADIO = getattr(discord.ui, "RadioGroup", None)
    _MODAL_RADIO_OPT = getattr(discord, "RadioGroupOption", None)
    _MODAL_CHECKBOX = getattr(discord.ui, "CheckboxGroup", None)
    _MODAL_CHECKBOX_OPT = getattr(discord, "CheckboxGroupOption", None)

    class _NanobotModal(discord.ui.Modal):
        """Stateless Modal — submission is routed via on_interaction by custom_id."""

        def __init__(self, *, title: str, custom_id: str) -> None:
            super().__init__(title=title, custom_id=custom_id, timeout=None)

        async def on_submit(self, interaction: discord.Interaction) -> None:
            # No-op: the global on_interaction handler dispatches modal_submit
            # interactions by custom_id, so this Modal subclass holds no state.
            return


MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000  # Discord message character limit
TYPING_INTERVAL_S = 8

# Discord component limits
MAX_BUTTON_LABEL = 80
MAX_CUSTOM_ID = 100
MAX_SELECT_OPTIONS = 25
MAX_SELECT_LABEL = 100
MAX_MODAL_INPUTS = 5
MAX_ROWS = 5
MAX_BTNS_PER_ROW = 5
MAX_TEXT_INPUT_LABEL = 45
MAX_MODAL_TITLE = 45
MODAL_SPEC_CAP = 1024
MODAL_CID_SUFFIX = ":m"
ZERO_WIDTH_SPACE = "​"


def _truncate(value: str, limit: int) -> str:
    """Truncate a string to the given Discord limit."""
    if value is None:
        return ""
    if len(value) <= limit:
        return value
    return value[:limit]


@dataclass
class _StreamBuf:
    """Per-chat streaming accumulator for progressive Discord message edits."""

    text: str = ""
    message: Any | None = None
    last_edit: float = 0.0
    stream_id: str | None = None


class DiscordConfig(Base):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    allow_channels: list[str] = Field(default_factory=list)  # Allowed channel IDs (empty = all)
    intents: int = 37377
    group_policy: Literal["mention", "open"] = "mention"
    read_receipt_emoji: str = "👀"
    working_emoji: str = "🔧"
    working_emoji_delay: float = 2.0
    streaming: bool = True
    proxy: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None


if DISCORD_AVAILABLE:

    class DiscordBotClient(discord.Client):
        """discord.py client that forwards events to the channel."""

        def __init__(
            self,
            channel: DiscordChannel,
            *,
            intents: discord.Intents,
            proxy: str | None = None,
            proxy_auth: aiohttp.BasicAuth | None = None,
        ) -> None:
            super().__init__(intents=intents, proxy=proxy, proxy_auth=proxy_auth)
            self._channel = channel
            self.tree = app_commands.CommandTree(self)
            self._register_app_commands()

        async def on_ready(self) -> None:
            self._channel._bot_user_id = str(self.user.id) if self.user else None
            logger.info("Discord bot connected as user {}", self._channel._bot_user_id)
            try:
                synced = await self.tree.sync()
                logger.info("Discord app commands synced: {}", len(synced))
            except Exception as e:
                logger.warning("Discord app command sync failed: {}", e)

        async def on_message(self, message: discord.Message) -> None:
            await self._channel._handle_discord_message(message)

        async def on_thread_delete(self, thread: discord.Thread) -> None:
            self._channel._forget_channel(thread)

        async def on_thread_update(self, before: discord.Thread, after: discord.Thread) -> None:
            if getattr(after, "archived", False):
                self._channel._forget_channel(after)
            else:
                self._channel._remember_channel(after)

        async def on_interaction(self, interaction: discord.Interaction) -> None:
            """Route Discord component & modal-submit interactions to the agent.

            Slash-command interactions are handled by CommandTree separately;
            this dispatcher only processes type=component (button/select) and
            type=modal_submit. The 3-second response window is preserved by
            deferring immediately on every path that doesn't open a modal.
            """
            try:
                interaction_type = getattr(interaction, "type", None)
                # discord.py's enum: InteractionType.component / .modal_submit
                if interaction_type == discord.InteractionType.component:
                    await self._handle_component_interaction(interaction)
                elif interaction_type == discord.InteractionType.modal_submit:
                    await self._handle_modal_submit(interaction)
            except Exception as e:
                logger.warning("Discord on_interaction error: {}", e)

        async def _interaction_auth_ok(
            self, interaction: discord.Interaction
        ) -> tuple[bool, Any | None]:
            """Run the same allow_from / allow_channels checks slash commands use."""
            sender_id = str(interaction.user.id)
            if not self._channel.is_allowed(sender_id):
                await self._reply_ephemeral(interaction, "You are not allowed to use this bot.")
                return False, None
            channel = await self._resolve_interaction_channel(interaction)
            if not await self._interaction_channel_allowed(interaction, channel):
                await self._reply_ephemeral(
                    interaction, "This channel is not allowed for this bot."
                )
                return False, None
            return True, channel

        def _interaction_session_metadata(
            self,
            interaction: discord.Interaction,
            channel: Any | None,
        ) -> tuple[dict[str, Any], str | None]:
            """Mirror _forward_slash_command's metadata + thread session-key shape."""
            channel_id = interaction.channel_id
            metadata: dict[str, Any] = {
                "interaction_id": str(interaction.id),
                "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                "is_callback": True,
            }
            session_key: str | None = None
            if channel is not None and channel_id is not None:
                parent_channel_id = self._channel._channel_parent_key(channel)
                if parent_channel_id is not None:
                    metadata["parent_channel_id"] = parent_channel_id
                    metadata["context_chat_id"] = parent_channel_id
                    metadata["thread_id"] = str(channel_id)
                    session_key = f"{self._channel.name}:{parent_channel_id}:thread:{channel_id}"
            return metadata, session_key

        async def _handle_component_interaction(self, interaction: discord.Interaction) -> None:
            ok, channel = await self._interaction_auth_ok(interaction)
            if not ok:
                return

            data = getattr(interaction, "data", None) or {}
            custom_id = str(data.get("custom_id") or "")
            component_type = data.get("component_type")
            channel_id = interaction.channel_id

            if channel_id is None or not custom_id:
                return

            modal_spec = self._channel._modal_specs.get(custom_id)
            if component_type == 2 and modal_spec is not None:
                modal = self._build_modal(modal_spec, button_custom_id=custom_id)
                if modal is None:
                    await self._reply_ephemeral(interaction, "Form unavailable.")
                    return
                try:
                    await interaction.response.send_modal(modal)
                except Exception as e:
                    logger.warning("Discord send_modal failed: {}", e)
                return

            with suppress(Exception):
                await interaction.response.defer()

            metadata, session_key = self._interaction_session_metadata(interaction, channel)
            metadata["custom_id"] = custom_id
            message = getattr(interaction, "message", None)
            if message is not None:
                metadata["message_id"] = str(getattr(message, "id", "") or "")

            if component_type == 2:
                # Button click without a registered modal.
                button_label = self._extract_button_label(interaction, custom_id) or custom_id
                metadata["interaction_type"] = "button"
                metadata["button_label"] = button_label
                content = button_label
            elif component_type == 3:
                values = list(data.get("values") or [])
                labels = self._resolve_select_labels(interaction, custom_id, values)
                metadata["interaction_type"] = "select"
                metadata["values"] = values
                metadata["labels"] = labels
                content = ", ".join(labels) if labels else ", ".join(values)
            else:
                logger.debug("Discord ignoring component_type={}", component_type)
                return

            await self._channel._handle_message(
                sender_id=str(interaction.user.id),
                chat_id=str(channel_id),
                content=content,
                metadata=metadata,
                session_key=session_key,
            )

        async def _handle_modal_submit(self, interaction: discord.Interaction) -> None:
            ok, channel = await self._interaction_auth_ok(interaction)
            if not ok:
                return

            data = getattr(interaction, "data", None) or {}
            modal_custom_id = str(data.get("custom_id") or "")
            button_cid = self._channel._modal_to_button.get(modal_custom_id)
            if not button_cid:
                logger.info(
                    "Discord modal_submit with unknown cid {}; form expired", modal_custom_id
                )
                with suppress(Exception):
                    await interaction.response.send_message(
                        "This form has expired. Please request it again.", ephemeral=True
                    )
                return

            spec = self._channel._modal_specs.get(button_cid) or {}
            input_specs = {
                str(item.get("custom_id") or item.get("label") or ""): item
                for item in (spec.get("inputs") or [])
                if isinstance(item, dict)
            }

            # Modal submit payload tree: top-level entries can be ActionRow (type 1,
            # legacy TextInput wrapping) or Label (type 18, 2.6+ wrapper for Select /
            # RadioGroup / CheckboxGroup / TextInput). Walk recursively to leaves —
            # be permissive on shape (ActionRow nests under `components`, Label nests
            # under `component`; some fixtures omit the explicit `type` integer).
            leaves: list[dict[str, Any]] = []

            def _collect(items: list[Any]) -> None:
                for item in items or []:
                    if not isinstance(item, dict):
                        continue
                    if isinstance(item.get("components"), list):  # ActionRow shape
                        _collect(item["components"])
                    elif isinstance(item.get("component"), dict):  # Label shape
                        _collect([item["component"]])
                    elif item.get("custom_id"):
                        leaves.append(item)

            _collect(data.get("components") or [])

            form_values: dict[str, str] = {}
            content_lines: list[str] = []
            for component in leaves:
                cid = str(component.get("custom_id") or "")
                if not cid:
                    continue
                # TextInput + RadioGroup carry singular `value`; Select +
                # CheckboxGroup carry list `values`. Flatten lists with ", ".
                if "values" in component:
                    raw_values = [str(v) for v in (component.get("values") or [])]
                    value = ", ".join(raw_values)
                else:
                    value = str(component.get("value") or "")
                form_values[cid] = value
                if cid in input_specs:
                    label = str(input_specs[cid].get("label") or cid)
                else:
                    label = cid
                content_lines.append(f"{label}: {value}")

            with suppress(Exception):
                await interaction.response.defer()

            metadata, session_key = self._interaction_session_metadata(interaction, channel)
            metadata["custom_id"] = button_cid
            metadata["interaction_type"] = "modal_submit"
            metadata["form_values"] = form_values
            parent_message = getattr(interaction, "message", None)
            if parent_message is not None:
                metadata["parent_message_id"] = str(getattr(parent_message, "id", "") or "")

            content = "\n".join(content_lines) if content_lines else ""
            channel_id = interaction.channel_id
            if channel_id is None:
                return

            await self._channel._handle_message(
                sender_id=str(interaction.user.id),
                chat_id=str(channel_id),
                content=content,
                metadata=metadata,
                session_key=session_key,
            )

        @staticmethod
        def _extract_button_label(interaction: discord.Interaction, custom_id: str) -> str | None:
            """Pull the clicked button's label from the originating message components."""
            message = getattr(interaction, "message", None)
            if message is None:
                return None
            for action_row in getattr(message, "components", None) or []:
                for child in getattr(action_row, "children", None) or []:
                    if getattr(child, "custom_id", None) == custom_id:
                        return getattr(child, "label", None)
            return None

        @staticmethod
        def _resolve_select_labels(
            interaction: discord.Interaction,
            custom_id: str,
            values: list[str],
        ) -> list[str]:
            """Map selected values back to display labels using the original message."""
            label_for: dict[str, str] = {}
            message = getattr(interaction, "message", None)
            if message is not None:
                for action_row in getattr(message, "components", None) or []:
                    for child in getattr(action_row, "children", None) or []:
                        if getattr(child, "custom_id", None) != custom_id:
                            continue
                        for option in getattr(child, "options", None) or []:
                            label = getattr(option, "label", None)
                            value = getattr(option, "value", None)
                            if label and value is not None:
                                label_for[str(value)] = str(label)
            return [label_for.get(v, v) for v in values]

        def _build_modal(
            self, spec: dict[str, Any], *, button_custom_id: str
        ) -> "discord.ui.Modal | None":
            """Instantiate a Modal subclass from a stored spec.

            Each input dict is dispatched on its ``type``:
              - "text" / "paragraph" / unset → TextInput (legacy default)
              - "select" → String Select wrapped in a Label (discord.py 2.6+)
              - "radio"  → RadioGroup wrapped in a Label (discord.py 2.7+)
              - "checkbox" → CheckboxGroup wrapped in a Label (discord.py 2.7+)
            """
            inputs = spec.get("inputs") or []
            if not isinstance(inputs, list) or not inputs:
                return None

            title = _truncate(str(spec.get("title") or "Form"), MAX_MODAL_TITLE)
            modal_custom_id = f"{button_custom_id}{MODAL_CID_SUFFIX}"
            modal = _NanobotModal(title=title, custom_id=_truncate(modal_custom_id, MAX_CUSTOM_ID))

            for index, item in enumerate(inputs[:MAX_MODAL_INPUTS]):
                if not isinstance(item, dict):
                    continue
                cid = _truncate(
                    str(item.get("custom_id") or item.get("label") or f"f{index}"),
                    MAX_CUSTOM_ID,
                )
                label_text = _truncate(
                    str(item.get("label") or f"Field {index + 1}"), MAX_TEXT_INPUT_LABEL
                )
                description = item.get("description")
                description = _truncate(str(description), 100) if description else None

                item_type = str(item.get("type") or "").lower()
                # Back-compat: no `type`, only `style` → TextInput.
                if not item_type:
                    item_type = (
                        "paragraph"
                        if str(item.get("style") or "").lower() == "paragraph"
                        else "text"
                    )

                if item_type in ("text", "short", "paragraph"):
                    style = (
                        discord.TextStyle.paragraph
                        if item_type == "paragraph"
                        or str(item.get("style") or "").lower() == "paragraph"
                        else discord.TextStyle.short
                    )
                    placeholder = item.get("placeholder")
                    default = item.get("value") or item.get("default")
                    modal.add_item(
                        discord.ui.TextInput(
                            label=label_text,
                            style=style,
                            custom_id=cid,
                            placeholder=str(placeholder)[:100] if placeholder else None,
                            default=str(default)[:4000] if default else None,
                            required=bool(item.get("required", True)),
                            min_length=item.get("min_length"),
                            max_length=item.get("max_length"),
                        )
                    )
                    continue

                if _MODAL_LABEL is None:
                    logger.warning(
                        "Discord modal input type {!r} requires discord.py 2.6+ (Label); skipping",
                        item_type,
                    )
                    continue

                inner = self._build_modal_input(item_type, item, cid)
                if inner is None:
                    continue
                modal.add_item(
                    _MODAL_LABEL(text=label_text, description=description, component=inner)
                )

            return modal

        @staticmethod
        def _build_modal_options(item: dict[str, Any], cls: Any) -> list[Any]:
            """Coerce an `options` list into RadioGroupOption / CheckboxGroupOption / SelectOption."""
            options_raw = item.get("options") or []
            if not isinstance(options_raw, list):
                return []
            out: list[Any] = []
            for opt in options_raw[:MAX_SELECT_OPTIONS]:
                if isinstance(opt, str):
                    label, value, desc, default = opt, opt, None, False
                elif isinstance(opt, dict):
                    label = str(opt.get("label") or opt.get("value") or "")
                    value = str(opt.get("value") or opt.get("label") or "")
                    desc = opt.get("description")
                    desc = str(desc) if desc else None
                    default = bool(opt.get("default", False))
                else:
                    continue
                label = _truncate(label, MAX_SELECT_LABEL)
                value = _truncate(value, MAX_CUSTOM_ID)
                if not label or not value:
                    continue
                if cls is discord.SelectOption:
                    out.append(
                        discord.SelectOption(
                            label=label, value=value, description=desc, default=default
                        )
                    )
                else:
                    out.append(cls(label=label, value=value, description=desc, default=default))
            return out

        def _build_modal_input(
            self, item_type: str, item: dict[str, Any], cid: str
        ) -> "discord.ui.Item | None":
            """Build the inner widget for a Label-wrapped modal input."""
            if item_type == "select":
                options = self._build_modal_options(item, discord.SelectOption)
                if not options:
                    return None
                placeholder = item.get("placeholder")
                placeholder = _truncate(str(placeholder), 150) if placeholder else None
                return discord.ui.Select(
                    custom_id=cid,
                    placeholder=placeholder,
                    min_values=max(0, int(item.get("min_values", 1))),
                    max_values=max(1, min(int(item.get("max_values", 1)), len(options))),
                    options=options,
                    required=bool(item.get("required", True)),
                )
            if item_type == "radio":
                if _MODAL_RADIO is None or _MODAL_RADIO_OPT is None:
                    logger.warning("Radio in modal requires discord.py 2.7+; skipping")
                    return None
                options = self._build_modal_options(item, _MODAL_RADIO_OPT)
                if len(options) < 2:
                    logger.warning("RadioGroup needs ≥ 2 options; skipping")
                    return None
                return _MODAL_RADIO(
                    custom_id=cid,
                    options=options[:10],  # RadioGroup hard-capped at 10 options.
                    required=bool(item.get("required", True)),
                )
            if item_type == "checkbox":
                if _MODAL_CHECKBOX is None or _MODAL_CHECKBOX_OPT is None:
                    logger.warning("Checkbox in modal requires discord.py 2.7+; skipping")
                    return None
                options = self._build_modal_options(item, _MODAL_CHECKBOX_OPT)
                if not options:
                    return None
                return _MODAL_CHECKBOX(
                    custom_id=cid,
                    options=options,
                    min_values=item.get("min_values"),
                    max_values=item.get("max_values"),
                    required=bool(item.get("required", True)),
                )
            logger.warning("unknown modal input type: {!r}", item_type)
            return None

        async def _reply_ephemeral(self, interaction: discord.Interaction, text: str) -> bool:
            """Send an ephemeral interaction response and report success."""
            try:
                await interaction.response.send_message(text, ephemeral=True)
                return True
            except Exception as e:
                logger.warning("Discord interaction response failed: {}", e)
                return False

        async def _resolve_interaction_channel(
            self,
            interaction: discord.Interaction,
        ) -> Any | None:
            channel_id = interaction.channel_id
            if channel_id is None:
                return None
            channel = getattr(interaction, "channel", None) or self.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(channel_id)
                except Exception as e:
                    logger.warning("Discord interaction channel {} unavailable: {}", channel_id, e)
                    return None
            self._channel._remember_channel(channel)
            return channel

        async def _interaction_channel_allowed(
            self,
            interaction: discord.Interaction,
            channel: Any | None,
        ) -> bool:
            allow_channels = self._channel.config.allow_channels
            if not allow_channels:
                return True
            if channel is None:
                channel_id = interaction.channel_id
                return channel_id is not None and str(channel_id) in allow_channels
            channel_ids = self._channel._channel_allow_keys(channel)
            return not channel_ids.isdisjoint(allow_channels)

        async def _forward_slash_command(
            self,
            interaction: discord.Interaction,
            command_text: str,
        ) -> None:
            sender_id = str(interaction.user.id)
            channel_id = interaction.channel_id

            if channel_id is None:
                logger.warning("Discord slash command missing channel_id: {}", command_text)
                return

            if not self._channel.is_allowed(sender_id):
                await self._reply_ephemeral(interaction, "You are not allowed to use this bot.")
                return

            channel = await self._resolve_interaction_channel(interaction)
            if not await self._interaction_channel_allowed(interaction, channel):
                await self._reply_ephemeral(
                    interaction, "This channel is not allowed for this bot."
                )
                return

            await self._reply_ephemeral(interaction, f"Processing {command_text}...")

            metadata: dict[str, Any] = {
                "interaction_id": str(interaction.id),
                "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                "is_slash_command": True,
            }
            session_key = None
            if channel is not None:
                parent_channel_id = self._channel._channel_parent_key(channel)
                if parent_channel_id is not None:
                    metadata["parent_channel_id"] = parent_channel_id
                    metadata["context_chat_id"] = parent_channel_id
                    metadata["thread_id"] = str(channel_id)
                    session_key = f"{self._channel.name}:{parent_channel_id}:thread:{channel_id}"

            await self._channel._handle_message(
                sender_id=sender_id,
                chat_id=str(channel_id),
                content=command_text,
                metadata=metadata,
                session_key=session_key,
            )

        def _register_app_commands(self) -> None:
            commands = (
                ("new", "Stop current task and start a new conversation", "/new"),
                ("stop", "Stop the current task", "/stop"),
                ("restart", "Restart the bot", "/restart"),
                ("status", "Show bot status", "/status"),
                ("history", "Show recent conversation messages", "/history"),
            )

            for name, description, command_text in commands:

                @self.tree.command(name=name, description=description)
                async def command_handler(
                    interaction: discord.Interaction,
                    _command_text: str = command_text,
                ) -> None:
                    await self._forward_slash_command(interaction, _command_text)

            @self.tree.command(name="help", description="Show available commands")
            async def help_command(interaction: discord.Interaction) -> None:
                sender_id = str(interaction.user.id)
                if not self._channel.is_allowed(sender_id):
                    await self._reply_ephemeral(interaction, "You are not allowed to use this bot.")
                    return
                channel = await self._resolve_interaction_channel(interaction)
                if not await self._interaction_channel_allowed(interaction, channel):
                    await self._reply_ephemeral(
                        interaction, "This channel is not allowed for this bot."
                    )
                    return
                await self._reply_ephemeral(interaction, build_help_text())

            @self.tree.error
            async def on_app_command_error(
                interaction: discord.Interaction,
                error: app_commands.AppCommandError,
            ) -> None:
                command_name = interaction.command.qualified_name if interaction.command else "?"
                logger.warning(
                    "Discord app command failed user={} channel={} cmd={} error={}",
                    interaction.user.id,
                    interaction.channel_id,
                    command_name,
                    error,
                )

        async def send_outbound(self, msg: OutboundMessage) -> None:
            """Send a nanobot outbound message using Discord transport rules."""
            channel_id = int(msg.chat_id)

            channel = self._channel._known_channels.get(msg.chat_id) or self.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(channel_id)
                except Exception as e:
                    logger.warning("Discord channel {} unavailable: {}", msg.chat_id, e)
                    return

            reference, mention_settings = self._build_reply_context(channel, msg.reply_to)
            sent_media = False
            failed_media: list[str] = []

            for index, media_path in enumerate(msg.media or []):
                if await self._send_file(
                    channel,
                    media_path,
                    reference=reference if index == 0 else None,
                    mention_settings=mention_settings,
                ):
                    sent_media = True
                else:
                    failed_media.append(Path(media_path).name)

            view = self._build_view(self._components_from(msg))
            chunks = self._build_chunks(msg.content or "", failed_media, sent_media)
            last_index = len(chunks) - 1

            for index, chunk in enumerate(chunks):
                kwargs: dict[str, Any] = {"content": chunk}
                if index == 0 and reference is not None and not sent_media:
                    kwargs["reference"] = reference
                    kwargs["allowed_mentions"] = mention_settings
                if view is not None and index == last_index:
                    kwargs["view"] = view
                await channel.send(**kwargs)

            if view is not None and not chunks:
                # No text/fallback to attach the view to. Discord requires content
                # or an embed for a message that carries components, so we send
                # one trailing zero-width-space message to host the view.
                await channel.send(content=ZERO_WIDTH_SPACE, view=view)

        @staticmethod
        def _components_from(msg: OutboundMessage) -> list[Any] | None:
            """Pick the component source for an outbound message.

            Rich components (with styles, selects, modals) ride on
            metadata['_components']; the legacy buttons field is used only when
            no rich components are present, and only contains plain labels.
            """
            metadata = msg.metadata or {}
            rich = metadata.get("_components")
            if isinstance(rich, list) and rich:
                return rich
            if msg.buttons:
                return list(msg.buttons)
            return None

        async def _send_file(
            self,
            channel: Messageable,
            file_path: str,
            *,
            reference: discord.PartialMessage | None,
            mention_settings: discord.AllowedMentions,
        ) -> bool:
            """Send a file attachment via discord.py."""
            path = Path(file_path)
            if not path.is_file():
                logger.warning("Discord file not found, skipping: {}", file_path)
                return False

            if path.stat().st_size > MAX_ATTACHMENT_BYTES:
                logger.warning("Discord file too large (>20MB), skipping: {}", path.name)
                return False

            try:
                kwargs: dict[str, Any] = {"file": discord.File(path)}
                if reference is not None:
                    kwargs["reference"] = reference
                    kwargs["allowed_mentions"] = mention_settings
                await channel.send(**kwargs)
                logger.info("Discord file sent: {}", path.name)
                return True
            except Exception as e:
                logger.error("Error sending Discord file {}: {}", path.name, e)
                return False

        def _build_view(self, rows: list[Any] | None) -> discord.ui.View | None:
            """Render component rows (str | dict cells) into a persistent View.

            Rows may contain plain string labels (-> primary buttons), button
            dicts ({type:'button'|'link', ...}), or a single select dict
            ({type:'select', ...}) which takes the whole row. Button rows wider
            than 5 are auto-rewrapped into multiple action rows. >5 rows total
            are dropped with a warning. The View has timeout=None so custom_ids
            stay dispatchable; we never store the View itself — dispatch is
            keyed on custom_id by on_interaction.
            """
            if not rows:
                return None

            seed = uuid.uuid4().hex[:12]
            view = discord.ui.View(timeout=None)
            row_index = 0

            for input_row in rows:
                if row_index >= MAX_ROWS:
                    logger.warning("Discord components: dropping rows beyond {}", MAX_ROWS)
                    break
                if not isinstance(input_row, list):
                    continue

                select_cell = self._extract_select(input_row)
                if select_cell is not None:
                    select = self._build_select(select_cell, seed=seed, row=row_index)
                    if select is not None:
                        select.row = row_index
                        view.add_item(select)
                        row_index += 1
                    continue

                # Button row: auto-rewrap if >5 buttons.
                buttons: list[discord.ui.Button] = []
                for col, cell in enumerate(input_row):
                    btn = self._build_button(cell, seed=seed, row=row_index, col=col)
                    if btn is not None:
                        buttons.append(btn)

                while buttons:
                    if row_index >= MAX_ROWS:
                        logger.warning("Discord components: button overflow past {} rows", MAX_ROWS)
                        break
                    chunk = buttons[:MAX_BTNS_PER_ROW]
                    buttons = buttons[MAX_BTNS_PER_ROW:]
                    for btn in chunk:
                        btn.row = row_index
                        view.add_item(btn)
                    row_index += 1

            return view if view.children else None

        @staticmethod
        def _extract_select(row: list[Any]) -> dict[str, Any] | None:
            """Return a select dict if the row contains exactly one select cell."""
            for cell in row:
                if isinstance(cell, dict) and (cell.get("type") == "select" or "select" in cell):
                    return cell.get("select", cell) if cell.get("type") != "select" else cell
            return None

        def _build_button(
            self,
            cell: Any,
            *,
            seed: str,
            row: int,
            col: int,
        ) -> discord.ui.Button | None:
            """Build one Button from a string label or button/link dict."""
            if isinstance(cell, str):
                label = cell
                spec: dict[str, Any] = {"type": "button", "label": label}
            elif isinstance(cell, dict):
                spec = cell
                label = str(spec.get("label") or "")
                if spec.get("type") not in (None, "button", "link"):
                    return None
            else:
                return None

            label = _truncate(label, MAX_BUTTON_LABEL)
            if not label:
                return None

            if spec.get("type") == "link" or spec.get("url"):
                url = str(spec.get("url") or "").strip()
                if not url:
                    return None
                return discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label=label,
                    url=url,
                )

            style_name = str(spec.get("style") or "primary").lower()
            style = _BUTTON_STYLES.get(style_name, discord.ButtonStyle.primary)

            custom_id = str(spec.get("custom_id") or "").strip()
            if not custom_id:
                custom_id = f"nb:{seed}:{row}:{col}"
            custom_id = _truncate(custom_id, MAX_CUSTOM_ID)

            modal_spec = spec.get("modal")
            if isinstance(modal_spec, dict) and modal_spec.get("inputs"):
                self._channel._record_modal_spec(custom_id, modal_spec)

            return discord.ui.Button(style=style, label=label, custom_id=custom_id)

        @staticmethod
        def _build_select(
            spec: dict[str, Any],
            *,
            seed: str,
            row: int,
        ) -> discord.ui.Select | None:
            """Build a string-select Select from a dict spec."""
            options_raw = spec.get("options") or []
            if not isinstance(options_raw, list) or not options_raw:
                return None

            if len(options_raw) > MAX_SELECT_OPTIONS:
                logger.warning(
                    "Discord select truncated to {} options (had {})",
                    MAX_SELECT_OPTIONS,
                    len(options_raw),
                )
                options_raw = options_raw[:MAX_SELECT_OPTIONS]

            options: list[discord.SelectOption] = []
            for opt in options_raw:
                if isinstance(opt, str):
                    label, value = opt, opt
                elif isinstance(opt, dict):
                    label = str(opt.get("label") or opt.get("value") or "")
                    value = str(opt.get("value") or opt.get("label") or "")
                else:
                    continue
                label = _truncate(label, MAX_SELECT_LABEL)
                value = _truncate(value, MAX_CUSTOM_ID)
                if not label or not value:
                    continue
                options.append(discord.SelectOption(label=label, value=value))

            if not options:
                return None

            custom_id = _truncate(
                str(spec.get("custom_id") or "").strip() or f"nb:{seed}:{row}:s",
                MAX_CUSTOM_ID,
            )
            placeholder = spec.get("placeholder")
            placeholder = _truncate(str(placeholder), 150) if placeholder else None
            min_values = max(0, int(spec.get("min_values", 1)))
            max_values = max(1, min(int(spec.get("max_values", 1)), len(options)))

            return discord.ui.Select(
                custom_id=custom_id,
                placeholder=placeholder,
                min_values=min_values,
                max_values=max_values,
                options=options,
            )

        @staticmethod
        def _build_chunks(content: str, failed_media: list[str], sent_media: bool) -> list[str]:
            """Build outbound text chunks, including attachment-failure fallback text."""
            chunks = split_message(content, MAX_MESSAGE_LEN)
            if chunks or not failed_media or sent_media:
                return chunks
            fallback = "\n".join(f"[attachment: {name} - send failed]" for name in failed_media)
            return split_message(fallback, MAX_MESSAGE_LEN)

        @staticmethod
        def _build_reply_context(
            channel: Messageable,
            reply_to: str | None,
        ) -> tuple[discord.PartialMessage | None, discord.AllowedMentions]:
            """Build reply context for outbound messages."""
            mention_settings = discord.AllowedMentions(replied_user=False)
            if not reply_to:
                return None, mention_settings
            try:
                message_id = int(reply_to)
            except ValueError:
                logger.warning("Invalid Discord reply target: {}", reply_to)
                return None, mention_settings

            return channel.get_partial_message(message_id), mention_settings


class DiscordChannel(BaseChannel):
    """Discord channel using discord.py."""

    name = "discord"
    display_name = "Discord"
    _STREAM_EDIT_INTERVAL = 0.8

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return DiscordConfig().model_dump(by_alias=True)

    @staticmethod
    def _channel_key(channel_or_id: Any) -> str:
        """Normalize channel-like objects and ids to a stable string key."""
        channel_id = getattr(channel_or_id, "id", channel_or_id)
        return str(channel_id)

    @classmethod
    def _channel_allow_keys(cls, channel: Any) -> set[str]:
        """Return channel IDs that can satisfy allow_channels for this channel."""
        keys = {cls._channel_key(channel)}
        if parent_key := cls._channel_parent_key(channel):
            keys.add(parent_key)
        return keys

    @classmethod
    def _channel_parent_key(cls, channel: Any) -> str | None:
        """Return the parent channel key for a Discord thread-like channel."""
        parent_id = getattr(channel, "parent_id", None)
        if parent_id is not None:
            return cls._channel_key(parent_id)
        parent = getattr(channel, "parent", None)
        if parent is not None:
            return cls._channel_key(parent)
        return None

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = DiscordConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: DiscordConfig = config
        self._client: DiscordBotClient | None = None
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}
        self._bot_user_id: str | None = None
        self._pending_reactions: dict[str, Any] = {}  # chat_id -> message object
        self._working_emoji_tasks: dict[str, asyncio.Task[None]] = {}
        self._stream_bufs: dict[str, _StreamBuf] = {}
        self._known_channels: dict[str, Any] = {}
        # Modal flow state. Lost on restart; orphaned button clicks degrade to
        # plain button-click dispatch, modal_submit with unknown cid is dropped.
        self._modal_specs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._modal_to_button: OrderedDict[str, str] = OrderedDict()

    def _record_modal_spec(self, button_custom_id: str, spec: dict[str, Any]) -> None:
        """Cache a modal spec keyed by its trigger button's custom_id (FIFO-bounded)."""
        modal_custom_id = f"{button_custom_id}{MODAL_CID_SUFFIX}"
        self._modal_specs[button_custom_id] = spec
        self._modal_specs.move_to_end(button_custom_id)
        self._modal_to_button[modal_custom_id] = button_custom_id
        self._modal_to_button.move_to_end(modal_custom_id)
        while len(self._modal_specs) > MODAL_SPEC_CAP:
            evicted_button_cid, _ = self._modal_specs.popitem(last=False)
            self._modal_to_button.pop(f"{evicted_button_cid}{MODAL_CID_SUFFIX}", None)
        while len(self._modal_to_button) > MODAL_SPEC_CAP:
            self._modal_to_button.popitem(last=False)

    def _remember_channel(self, channel: Any) -> None:
        self._known_channels[self._channel_key(channel)] = channel

    def _forget_channel(self, channel_or_id: Any) -> None:
        self._known_channels.pop(self._channel_key(channel_or_id), None)

    async def start(self) -> None:
        """Start the Discord client."""
        if not DISCORD_AVAILABLE:
            logger.error("discord.py not installed. Run: pip install nanobot-ai[discord]")
            return

        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        try:
            intents = discord.Intents.none()
            intents.value = self.config.intents

            proxy_auth = None
            has_user = bool(self.config.proxy_username)
            has_pass = bool(self.config.proxy_password)
            if has_user and has_pass:
                import aiohttp

                proxy_auth = aiohttp.BasicAuth(
                    login=self.config.proxy_username,
                    password=self.config.proxy_password,
                )
            elif has_user != has_pass:
                logger.warning(
                    "Discord proxy auth incomplete: both proxy_username and "
                    "proxy_password must be set; ignoring partial credentials",
                )

            self._client = DiscordBotClient(
                self,
                intents=intents,
                proxy=self.config.proxy,
                proxy_auth=proxy_auth,
            )
        except Exception as e:
            logger.error("Failed to initialize Discord client: {}", e)
            self._client = None
            self._running = False
            return

        self._running = True
        logger.info("Starting Discord client via discord.py...")

        try:
            await self._client.start(self.config.token)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Discord client startup failed: {}", e)
        finally:
            self._running = False
            await self._reset_runtime_state(close_client=True)

    async def stop(self) -> None:
        """Stop the Discord channel."""
        self._running = False
        await self._reset_runtime_state(close_client=True)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Discord using discord.py."""
        client = self._client
        if client is None or not client.is_ready():
            logger.warning("Discord client not ready; dropping outbound message")
            return

        is_progress = bool((msg.metadata or {}).get("_progress"))

        try:
            await client.send_outbound(msg)
        except Exception as e:
            logger.error("Error sending Discord message: {}", e)
            raise
        finally:
            if not is_progress:
                await self._stop_typing(msg.chat_id)
                await self._clear_reactions(msg.chat_id)

    async def send_delta(
        self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Progressive Discord delivery: send once, then edit until the stream ends."""
        client = self._client
        if client is None or not client.is_ready():
            logger.warning("Discord client not ready; dropping stream delta")
            return

        meta = metadata or {}
        stream_id = meta.get("_stream_id")

        if meta.get("_stream_end"):
            buf = self._stream_bufs.get(chat_id)
            if not buf or buf.message is None or not buf.text:
                return
            if stream_id is not None and buf.stream_id is not None and buf.stream_id != stream_id:
                return
            await self._finalize_stream(chat_id, buf)
            return

        buf = self._stream_bufs.get(chat_id)
        if buf is None or (
            stream_id is not None and buf.stream_id is not None and buf.stream_id != stream_id
        ):
            buf = _StreamBuf(stream_id=stream_id)
            self._stream_bufs[chat_id] = buf
        elif buf.stream_id is None:
            buf.stream_id = stream_id

        buf.text += delta
        if not buf.text.strip():
            return

        target = await self._resolve_channel(chat_id)
        if target is None:
            logger.warning("Discord stream target {} unavailable", chat_id)
            return

        now = time.monotonic()
        if buf.message is None:
            try:
                buf.message = await target.send(content=buf.text)
                buf.last_edit = now
            except Exception as e:
                logger.warning("Discord stream initial send failed: {}", e)
                raise
            return

        if (now - buf.last_edit) < self._STREAM_EDIT_INTERVAL:
            return

        try:
            await buf.message.edit(content=DiscordBotClient._build_chunks(buf.text, [], False)[0])
            buf.last_edit = now
        except Exception as e:
            logger.warning("Discord stream edit failed: {}", e)
            raise

    async def _handle_discord_message(self, message: discord.Message) -> None:
        """Handle incoming Discord messages from discord.py.

        Self-loop guard: only drop messages from this bot's own account. Messages
        from other bots are allowed through so multi-agent setups (one bot asking
        another for help, a bot mentioning another by @name, etc.) can work.
        Bot-from-bot loops are still prevented per-instance because each bot
        still ignores its own outbound messages. (#3217)
        """
        if self._bot_user_id is not None and str(message.author.id) == self._bot_user_id:
            return
        if self._is_system_message(message):
            return

        sender_id = str(message.author.id)
        channel_id = self._channel_key(message.channel)
        self._remember_channel(message.channel)
        content = message.content or ""

        if not self._should_accept_inbound(message, sender_id, content):
            return

        media_paths, attachment_markers = await self._download_attachments(message.attachments)
        full_content = self._compose_inbound_content(content, attachment_markers)
        metadata = self._build_inbound_metadata(message)
        parent_channel_id = self._channel_parent_key(message.channel)
        session_key = None
        if parent_channel_id is not None:
            metadata["parent_channel_id"] = parent_channel_id
            metadata["context_chat_id"] = parent_channel_id
            metadata["thread_id"] = channel_id
            session_key = f"{self.name}:{parent_channel_id}:thread:{channel_id}"

        await self._start_typing(message.channel)

        # Add read receipt reaction immediately, working emoji after delay
        try:
            await message.add_reaction(self.config.read_receipt_emoji)
            self._pending_reactions[channel_id] = message
        except Exception as e:
            logger.debug("Failed to add read receipt reaction: {}", e)

        # Delayed working indicator (cosmetic — not tied to subagent lifecycle)
        async def _delayed_working_emoji() -> None:
            await asyncio.sleep(self.config.working_emoji_delay)
            try:
                await message.add_reaction(self.config.working_emoji)
            except Exception:
                pass

        self._working_emoji_tasks[channel_id] = asyncio.create_task(_delayed_working_emoji())

        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=channel_id,
                content=full_content,
                media=media_paths,
                metadata=metadata,
                session_key=session_key,
            )
        except Exception:
            await self._clear_reactions(channel_id)
            await self._stop_typing(channel_id)
            raise

    async def _on_message(self, message: discord.Message) -> None:
        """Backward-compatible alias for legacy tests/callers."""
        await self._handle_discord_message(message)

    async def _resolve_channel(self, chat_id: str) -> Any | None:
        """Resolve a Discord channel from cache first, then network fetch."""
        client = self._client
        if client is None or not client.is_ready():
            return None
        channel = self._known_channels.get(chat_id)
        if channel is not None:
            return channel
        channel_id = int(chat_id)
        channel = client.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await client.fetch_channel(channel_id)
        except Exception as e:
            logger.warning("Discord channel {} unavailable: {}", chat_id, e)
            return None

    async def _finalize_stream(self, chat_id: str, buf: _StreamBuf) -> None:
        """Commit the final streamed content and flush overflow chunks."""
        chunks = DiscordBotClient._build_chunks(buf.text, [], False)
        if not chunks:
            self._stream_bufs.pop(chat_id, None)
            return

        try:
            await buf.message.edit(content=chunks[0])
        except Exception as e:
            logger.warning("Discord final stream edit failed: {}", e)
            raise

        target = getattr(buf.message, "channel", None) or await self._resolve_channel(chat_id)
        if target is None:
            logger.warning("Discord stream follow-up target {} unavailable", chat_id)
            self._stream_bufs.pop(chat_id, None)
            return

        for extra_chunk in chunks[1:]:
            await target.send(content=extra_chunk)

        self._stream_bufs.pop(chat_id, None)
        await self._stop_typing(chat_id)
        await self._clear_reactions(chat_id)

    def _should_accept_inbound(
        self,
        message: discord.Message,
        sender_id: str,
        content: str,
    ) -> bool:
        """Check if inbound Discord message should be processed."""
        if not self.is_allowed(sender_id):
            return False
        # Channel-based filtering: only respond in allowed channels
        allow_channels = self.config.allow_channels
        if allow_channels:
            channel_ids = self._channel_allow_keys(message.channel)
            if channel_ids.isdisjoint(allow_channels):
                return False
        if message.guild is not None and not self._should_respond_in_group(message, content):
            return False
        return True

    async def _download_attachments(
        self,
        attachments: list[discord.Attachment],
    ) -> tuple[list[str], list[str]]:
        """Download supported attachments and return paths + display markers."""
        media_paths: list[str] = []
        markers: list[str] = []
        media_dir = get_media_dir("discord")

        for attachment in attachments:
            filename = attachment.filename or "attachment"
            if attachment.size and attachment.size > MAX_ATTACHMENT_BYTES:
                markers.append(f"[attachment: {filename} - too large]")
                continue
            try:
                media_dir.mkdir(parents=True, exist_ok=True)
                safe_name = safe_filename(filename)
                file_path = media_dir / f"{attachment.id}_{safe_name}"
                await attachment.save(file_path)
                media_paths.append(str(file_path))
                markers.append(f"[attachment: {file_path.name}]")
            except Exception as e:
                logger.warning("Failed to download Discord attachment: {}", e)
                markers.append(f"[attachment: {filename} - download failed]")

        return media_paths, markers

    @staticmethod
    def _compose_inbound_content(content: str, attachment_markers: list[str]) -> str:
        """Combine message text with attachment markers."""
        content_parts = [content] if content else []
        content_parts.extend(attachment_markers)
        return "\n".join(part for part in content_parts if part) or "[empty message]"

    @staticmethod
    def _is_system_message(message: discord.Message) -> bool:
        """Return True for Discord system messages that carry no user prompt."""
        message_type = getattr(message, "type", discord.MessageType.default)
        return message_type not in {discord.MessageType.default, discord.MessageType.reply}

    @staticmethod
    def _build_inbound_metadata(message: discord.Message) -> dict[str, str | None]:
        """Build metadata for inbound Discord messages."""
        reply_to = (
            str(message.reference.message_id)
            if message.reference and message.reference.message_id
            else None
        )
        return {
            "message_id": str(message.id),
            "guild_id": str(message.guild.id) if message.guild else None,
            "reply_to": reply_to,
        }

    def _should_respond_in_group(self, message: discord.Message, content: str) -> bool:
        """Check if the bot should respond in a guild channel based on policy."""
        if self.config.group_policy == "open":
            return True

        if self.config.group_policy == "mention":
            bot_user_id = self._bot_user_id
            if bot_user_id is None and self._client and self._client.user:
                bot_user_id = str(self._client.user.id)
            if bot_user_id is None:
                logger.debug(
                    "Discord message in {} ignored (bot identity unavailable)", message.channel.id
                )
                return False

            if any(str(user.id) == bot_user_id for user in message.mentions):
                return True
            if bot_user_id in {str(user_id) for user_id in getattr(message, "raw_mentions", [])}:
                return True
            if f"<@{bot_user_id}>" in content or f"<@!{bot_user_id}>" in content:
                return True
            if self._references_bot_message(message, bot_user_id):
                return True

            logger.debug("Discord message in {} ignored (bot not mentioned)", message.channel.id)
            return False

        return True

    @staticmethod
    def _references_bot_message(message: discord.Message, bot_user_id: str) -> bool:
        """Return True when a Discord reply targets a message authored by this bot."""
        reference = getattr(message, "reference", None)
        if reference is None:
            return False
        referenced_message = getattr(reference, "resolved", None) or getattr(
            reference, "cached_message", None
        )
        author = getattr(referenced_message, "author", None)
        return str(getattr(author, "id", "")) == bot_user_id

    async def _start_typing(self, channel: Messageable) -> None:
        """Start periodic typing indicator for a channel."""
        channel_id = self._channel_key(channel)
        await self._stop_typing(channel_id)

        async def typing_loop() -> None:
            while self._running:
                try:
                    async with channel.typing():
                        await asyncio.sleep(TYPING_INTERVAL_S)
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    logger.debug("Discord typing indicator failed for {}: {}", channel_id, e)
                    return

        self._typing_tasks[channel_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, channel_id: str) -> None:
        """Stop typing indicator for a channel."""
        task = self._typing_tasks.pop(self._channel_key(channel_id), None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _clear_reactions(self, chat_id: str) -> None:
        """Remove all pending reactions after bot replies."""
        # Cancel delayed working emoji if it hasn't fired yet
        task = self._working_emoji_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

        msg_obj = self._pending_reactions.pop(chat_id, None)
        if msg_obj is None:
            return
        bot_user = self._client.user if self._client else None
        for emoji in (self.config.read_receipt_emoji, self.config.working_emoji):
            try:
                await msg_obj.remove_reaction(emoji, bot_user)
            except Exception:
                pass

    async def _cancel_all_typing(self) -> None:
        """Stop all typing tasks."""
        channel_ids = list(self._typing_tasks)
        for channel_id in channel_ids:
            await self._stop_typing(channel_id)

    async def _reset_runtime_state(self, close_client: bool) -> None:
        """Reset client and typing state."""
        await self._cancel_all_typing()
        self._stream_bufs.clear()
        self._known_channels.clear()
        if close_client and self._client is not None and not self._client.is_closed():
            try:
                await self._client.close()
            except Exception as e:
                logger.warning("Discord client close failed: {}", e)
        self._client = None
        self._bot_user_id = None
