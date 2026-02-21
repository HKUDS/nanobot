"""Gateway restart tool."""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


RESTART_MARKER_PATH = Path.home() / ".nanobot" / "restart_marker.json"


def write_restart_marker(chat_id: str, channel: str, session_key: str = "") -> None:
    """Write a marker file so the new gateway can confirm the restart."""
    RESTART_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESTART_MARKER_PATH.write_text(json.dumps({
        "chat_id": chat_id,
        "channel": channel,
        "session_key": session_key,
        "timestamp": time.time(),
    }))


async def check_restart_marker(bus, session_manager=None) -> None:
    """Check for a restart marker and send confirmation to the originating chat.

    Called once during gateway startup.
    """
    if not RESTART_MARKER_PATH.exists():
        return
    try:
        marker = json.loads(RESTART_MARKER_PATH.read_text())
        RESTART_MARKER_PATH.unlink()
        age = time.time() - marker.get("timestamp", 0)
        if age > 300:  # Ignore markers older than 5 minutes
            logger.warning(f"Stale restart marker ({age:.0f}s old), ignoring")
            return
        
        # Inject system message into session so LLM knows about restart
        session_key = marker.get("session_key")
        if session_key and session_manager:
            try:
                session = session_manager.get_or_create_session(session_key)
                session.add_message("system", f"[SYSTEM] Gateway was restarted {age:.1f} seconds ago due to configuration change. The bot has been updated with new settings.")
                session_manager.save(session)
                logger.info(f"Injected restart notification into session {session_key}")
            except Exception as e:
                logger.error(f"Failed to inject restart message into session: {e}")
        
        from nanobot.bus.events import OutboundMessage
        await bus.publish_outbound(OutboundMessage(
            channel=marker["channel"],
            chat_id=marker["chat_id"],
            content=f"✅ Gateway restarted successfully ({age:.1f}s ago).",
        ))
        logger.info(f"Sent restart confirmation to {marker['channel']}:{marker['chat_id']}")
    except Exception as e:
        logger.error(f"Failed to process restart marker: {e}")
        # Clean up broken marker
        RESTART_MARKER_PATH.unlink(missing_ok=True)


class RestartGatewayTool(Tool):
    """Tool to restart the nanobot gateway service."""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "restart_gateway"

    @property
    def description(self) -> str:
        return (
            "Gracefully restart the nanobot gateway service. "
            "Use when code has been updated and needs to take effect. "
            "When called from Telegram, this will show confirmation buttons to the user. "
            "For other channels, you MUST ask the user for confirmation before calling this tool."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "confirmed": {
                    "type": "boolean",
                    "description": "Must be true. Ask the user for confirmation before setting this.",
                    "default": False
                },
                "force": {
                    "type": "boolean",
                    "description": "Force kill with SIGKILL instead of graceful SIGTERM",
                    "default": False
                }
            },
            "required": []
        }

    async def _send_telegram_confirmation(self, bus, chat_id: str, force: bool = False) -> str:
        """Send Telegram message with inline keyboard for restart confirmation.
        
        The actual restart will be triggered when user clicks the button.
        """
        from nanobot.bus.events import OutboundMessage
        
        # Build inline keyboard markup
        force_suffix = ":force" if force else ""
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Restart Gateway", "callback_data": f"restart_gateway:confirm{force_suffix}"},
                    {"text": "❌ Cancel", "callback_data": "restart_gateway:cancel"}
                ]
            ]
        }
        
        await bus.publish_outbound(OutboundMessage(
            channel="telegram",
            chat_id=chat_id,
            content="🔄 **Gateway Restart Required**\n\nThe agent has requested to restart the gateway. This is needed when code changes have been made.\n\nDo you want to proceed?",
            metadata={
                "reply_markup": keyboard,
                "parse_mode": "HTML"
            }
        ))
        
        return "I've sent a confirmation message with buttons to the Telegram chat. Please click the 'Restart Gateway' button to proceed."

    async def execute(self, confirmed: bool = False, force: bool = False, **kwargs: Any) -> str:
        """Restart the gateway service.

        Spawns 'nanobot gateway --force' as a detached subprocess.
        The new gateway process will kill old ones and take over.
        """
        channel = kwargs.get("channel", "").lower()
        chat_id = kwargs.get("chat_id", "")
        bus = kwargs.get("bus")
        
        # For Telegram, send inline keyboard buttons instead of restarting directly
        if channel == "telegram" and bus and chat_id:
            return await self._send_telegram_confirmation(bus, chat_id, force)
        
        # For other channels, require explicit confirmation
        if not confirmed:
            return (
                "⚠️ Gateway restart requires user confirmation. "
                "Please ask the user if they want to restart the gateway, "
                "then call this tool again with confirmed=true."
            )

        try:
            # Sanity-check config before restarting — don't kill the
            # running gateway if the new one would fail to boot.
            from nanobot.config.loader import get_config_path, load_config
            config_path = get_config_path()
            # 1. Check JSON syntax first (the exact failure from the logs)
            try:
                with open(config_path) as f:
                    json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                return f"❌ Config file has invalid JSON, aborting restart: {e}"
            # 2. Check it parses into a valid Config with an API key
            cfg = load_config(config_path)
            model = cfg.agents.defaults.model
            p = cfg.get_provider(model)
            if not (p and p.api_key) and not model.startswith("bedrock/"):
                return f"❌ No API key configured in {config_path}, aborting restart. The new gateway would fail to start."

            # Write restart marker so the new gateway can confirm
            chat_id = kwargs.get("chat_id", "")
            channel = kwargs.get("channel", "telegram")
            session_key = kwargs.get("session_key", "")
            if chat_id:
                write_restart_marker(chat_id, channel, session_key)

            # Build command - use same Python interpreter
            cmd = [sys.executable, "-m", "nanobot", "gateway", "--force"]
            if force:
                cmd.append("--force")

            logger.info(f"Restarting gateway with command: {' '.join(cmd)}")

            # Spawn detached process - new gateway will kill old ones
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=None,
                stderr=None,
                start_new_session=True,
            )

            logger.info(f"Spawned gateway restart: PID {process.pid}")

            return (
                f"🔄 Gateway restart initiated!\n"
                f"- New gateway PID: {process.pid}\n"
                f"- Mode: {'force kill (SIGKILL)' if force else 'graceful (SIGTERM)'}\n"
                f"- New gateway will kill old ones and take over\n"
                f"- Restart confirmation will be sent automatically\n\n"
                f"Note: This conversation will disconnect momentarily."
            )

        except Exception as e:
            logger.exception("Failed to restart gateway")
            return f"Error restarting gateway: {str(e)}"
