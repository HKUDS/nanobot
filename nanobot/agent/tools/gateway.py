"""Gateway restart tool."""

import asyncio
import compileall
import json
import sys
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


RESTART_MARKER_PATH = Path.home() / ".nanobot" / "restart_marker.json"


def check_python_syntax(package_dir: Path) -> list[str]:
    """Check all Python files for syntax errors.
    
    Returns a list of error messages, empty if all files are valid.
    """
    errors = []
    
    # Find all .py files in the package
    for py_file in package_dir.rglob("*.py"):
        try:
            with open(py_file, "rb") as f:
                compile(f.read(), py_file, "exec")
        except SyntaxError as e:
            rel_path = py_file.relative_to(package_dir.parent)
            errors.append(f"{rel_path}:{e.lineno}: {e.msg}")
    
    return errors


def write_restart_marker(chat_id: str, channel: str, session_key: str = "", thread_id: int | None = None) -> None:
    """Write a marker file so the new gateway can confirm the restart."""
    RESTART_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    marker_data = {
        "chat_id": chat_id,
        "channel": channel,
        "session_key": session_key,
        "timestamp": time.time(),
    }
    if thread_id is not None:
        marker_data["thread_id"] = thread_id
    RESTART_MARKER_PATH.write_text(json.dumps(marker_data))


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
        outbound_msg = OutboundMessage(
            channel=marker["channel"],
            chat_id=marker["chat_id"],
            content=f"✅ Gateway restarted successfully ({age:.1f}s ago).",
        )
        if "thread_id" in marker:
            outbound_msg.thread_id = marker["thread_id"]
        await bus.publish_outbound(outbound_msg)
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

    async def _send_telegram_confirmation(self, bus, chat_id: str, force: bool = False, thread_id: int | None = None) -> str:
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
        
        outbound_msg = OutboundMessage(
            channel="telegram",
            chat_id=chat_id,
            content="🔄 **Gateway Restart Required**\n\nThe agent has requested to restart the gateway. This is needed when code changes have been made.\n\nDo you want to proceed?",
            metadata={
                "reply_markup": keyboard,
                "parse_mode": "HTML"
            }
        )
        if thread_id is not None:
            outbound_msg.thread_id = thread_id
        
        await bus.publish_outbound(outbound_msg)
        
        return "I've sent a confirmation message with buttons to the Telegram chat. Please click the 'Restart Gateway' button to proceed."

    async def execute(self, confirmed: bool = False, force: bool = False, **kwargs: Any) -> str:
        """Restart the gateway service.

        Spawns 'nanobot gateway' as a detached subprocess.
        The new gateway process will kill old ones and take over.
        """
        channel = kwargs.get("channel", "").lower()
        chat_id = kwargs.get("chat_id", "")
        bus = kwargs.get("bus")
        thread_id = kwargs.get("thread_id")
        
        # For Telegram, only send confirmation buttons if NOT already confirmed
        # (i.e., when LLM calls the tool, not when user invokes /restart_gateway command)
        if channel == "telegram" and bus and chat_id and not confirmed:
            return await self._send_telegram_confirmation(bus, chat_id, force, thread_id)
        
        # For other channels without confirmation, ask for it
        if not confirmed:
            return (
                "⚠️ Gateway restart requires user confirmation. "
                "Please ask the user if they want to restart the gateway, "
                "then call this tool again with confirmed=true."
            )

        try:
            # 0. Check Python syntax before restarting — don't kill the
            # running gateway if the new one would fail to boot due to syntax errors.
            import nanobot
            package_dir = Path(nanobot.__file__).parent
            syntax_errors = check_python_syntax(package_dir)
            if syntax_errors:
                error_list = "\n".join(syntax_errors[:5])  # Show first 5 errors
                if len(syntax_errors) > 5:
                    error_list += f"\n... and {len(syntax_errors) - 5} more errors"
                return f"❌ Python syntax errors found, aborting restart:\n```\n{error_list}\n```"

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
            thread_id = kwargs.get("thread_id")
            if chat_id:
                write_restart_marker(chat_id, channel, session_key, thread_id)

            # Build command - use same Python interpreter
            cmd = [sys.executable, "-m", "nanobot", "gateway"]
            if force:
                cmd.append("--force")

            logger.info(f"Restarting gateway with command: {' '.join(cmd)}")

            # Spawn detached process - new gateway will kill old ones
            # Capture stderr to report startup errors
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )

            logger.info(f"Spawned gateway restart: PID {process.pid}")

            # Check for immediate startup failure (within 2 seconds)
            CRASH_CHECK_DELAY = 10
            IMMEDIATE_CHECK_DELAY = 2
            
            async def check_crash():
                # First, quick check for immediate failures
                await asyncio.sleep(IMMEDIATE_CHECK_DELAY)
                
                if process.returncode is not None:
                    # Process already exited - get stderr
                    stderr = ""
                    if process.stderr:
                        stderr_bytes = await process.stderr.read()
                        stderr = stderr_bytes.decode('utf-8', errors='replace').strip()
                    
                    logger.error(f"New gateway (PID {process.pid}) crashed immediately: {stderr}")
                    
                    error_msg = f"❌ Gateway restart failed (exit code {process.returncode})"
                    if stderr:
                        # Extract key error line
                        for line in stderr.split('\n'):
                            if 'Error' in line or 'error' in line:
                                error_msg += f"\n```\n{line}\n```"
                                break
                        else:
                            error_msg += f"\n```\n{stderr[:500]}\n```"
                    
                    if bus and chat_id:
                        from nanobot.bus.events import OutboundMessage
                        outbound_msg = OutboundMessage(
                            channel=channel,
                            chat_id=chat_id,
                            content=error_msg,
                        )
                        if thread_id is not None:
                            outbound_msg.thread_id = thread_id
                        await bus.publish_outbound(outbound_msg)
                    return
                
                # Wait longer to see if new gateway takes over
                await asyncio.sleep(CRASH_CHECK_DELAY - IMMEDIATE_CHECK_DELAY)
                
                # If we get here, we're still alive = new gateway crashed
                logger.error(f"New gateway (PID {process.pid}) appears to have crashed - old gateway still running")
                
                # Check if process is still running
                if process.returncode is not None:
                    stderr = ""
                    if process.stderr:
                        stderr_bytes = await process.stderr.read()
                        stderr = stderr_bytes.decode('utf-8', errors='replace').strip()
                    error_msg = f"❌ New gateway crashed with exit code {process.returncode}"
                    if stderr:
                        error_msg += f"\n```\n{stderr[:500]}\n```"
                else:
                    error_msg = f"❌ New gateway failed to take over (old gateway still alive after {CRASH_CHECK_DELAY}s)"
                
                # Send error to user
                if bus and chat_id:
                    from nanobot.bus.events import OutboundMessage
                    outbound_msg = OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content=error_msg,
                    )
                    if thread_id is not None:
                        outbound_msg.thread_id = thread_id
                    await bus.publish_outbound(outbound_msg)
            
            # Schedule crash check in background
            asyncio.create_task(check_crash())

            return (
                f"🔄 Gateway restart initiated!\n"
                f"- New gateway PID: {process.pid}\n"
                f"- Mode: {'force kill (SIGKILL)' if force else 'graceful (SIGTERM)'}\n"
                f"- Restart confirmation will be sent automatically\n\n"
                f"Note: This conversation will disconnect momentarily."
            )

        except Exception as e:
            logger.exception("Failed to restart gateway")
            return f"Error restarting gateway: {str(e)}"
