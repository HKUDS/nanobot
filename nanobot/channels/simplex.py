"""SimpleX bridge launcher built around the existing CLI bridge script."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.loader import get_config_path
from nanobot.config.schema import Base


class SimplexConfig(Base):
    """SimpleX bridge configuration."""

    enabled: bool = False
    websocket_url: str = ""
    client_id: str = ""
    chat_id: str = ""
    contact: str = ""
    simplex_cmd: str = "simplex-chat"
    simplex_timeout: int = Field(default=3, ge=1)
    state_file: str = ""
    poll_interval: float = Field(default=2.0, ge=0.1)
    receive_limit: int = Field(default=20, ge=1)
    bootstrap: Literal["latest", "all"] = "latest"
    reconnect_delay: float = Field(default=5.0, ge=0.1)


def _bridge_script_path() -> Path:
    """Locate the packaged or source-tree SimpleX bridge script."""
    current_file = Path(__file__)
    pkg_bridge = current_file.parent.parent / "bridge" / "simplex_bridge.py"
    src_bridge = current_file.parent.parent.parent / "bridge" / "simplex_bridge.py"

    if pkg_bridge.exists():
        return pkg_bridge
    if src_bridge.exists():
        return src_bridge
    raise RuntimeError(
        "SimpleX bridge source not found. "
        "Try reinstalling: pip install --force-reinstall nanobot"
    )


def _bridge_cwd(script_path: Path) -> Path | None:
    """Use the repository root as cwd when running from a source checkout."""
    candidate = script_path.parent.parent
    if (candidate / "bridge").is_dir() and (candidate / "nanobot").is_dir():
        return candidate
    return None


class SimplexChannel(BaseChannel):
    """Channel wrapper that launches the existing SimpleX bridge process."""

    name = "simplex"
    display_name = "SimpleX"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return SimplexConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = SimplexConfig.model_validate(config)
        super().__init__(config, bus)
        self._process: asyncio.subprocess.Process | None = None

    def _bridge_command(self) -> tuple[list[str], Path | None]:
        script_path = _bridge_script_path()
        config_path = get_config_path().expanduser().resolve(strict=False)
        return [sys.executable, str(script_path), "--config", str(config_path)], _bridge_cwd(script_path)

    async def login(self, force: bool = False) -> bool:
        """SimpleX does not provide an interactive login flow."""
        if force:
            logger.info("SimpleX login does not support --force")
        logger.error("SimpleX has no login flow. Enable channels.simplex and run `nanobot gateway`.")
        return False

    async def start(self) -> None:
        """Run the bridge as a managed subprocess for gateway mode."""
        self._running = True

        while self._running:
            command, cwd = self._bridge_command()
            logger.info("Starting SimpleX bridge...")
            self._process = await asyncio.create_subprocess_exec(*command, cwd=cwd)

            try:
                returncode = await self._process.wait()
            finally:
                self._process = None

            if not self._running:
                break

            logger.warning(
                "SimpleX bridge exited with status {}. Restarting in {:.1f}s...",
                returncode,
                self.config.reconnect_delay,
            )
            await asyncio.sleep(self.config.reconnect_delay)

    async def stop(self) -> None:
        """Stop the managed bridge subprocess."""
        self._running = False
        if not self._process or self._process.returncode is not None:
            return

        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5)
        except asyncio.TimeoutError:
            self._process.kill()
            await self._process.wait()

    async def send(self, msg: OutboundMessage) -> None:
        """SimpleX replies are delivered through the bridge's WebSocket session."""
        raise RuntimeError(
            "SimpleX outbound delivery is handled by bridge/simplex_bridge.py via the websocket channel"
        )
