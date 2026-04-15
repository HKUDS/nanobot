"""Main adapter entry point — wires vault client, poller, hook, and result injector.

Usage from nanobot gateway integration:

    from agenthifive_nanobot.adapter import AgentHiFiveAdapter

    adapter = AgentHiFiveAdapter.from_mcp_server_config(
        bus=bus,
        server_config=config.tools.mcp_servers["agenthifive"],
    )
    agent_loop = AgentLoop(bus=bus, hooks=[adapter.hook], ...)
    await adapter.start()
    # ... when shutting down:
    await adapter.stop()
"""

from __future__ import annotations

import logging
from typing import Any

from .approval_poller import ApprovalPoller
from .auth import build_runtime_config_from_mcp_server
from .hooks import AgentHiFiveHook
from .pending_store import PendingStore
from .result_injector import ResultInjector
from .types import PendingApproval
from .vault_client import VaultClient

logger = logging.getLogger(__name__)


class AgentHiFiveAdapter:
    """Orchestrates the AgentHiFive integration for nanobot.

    Connects the vault client, approval poller, pending store, hook,
    and result injector into a single lifecycle.
    """

    def __init__(
        self,
        vault_client: VaultClient,
        store: PendingStore,
        injector: ResultInjector,
        poll_interval: float = 5.0,
    ):
        self.vault = vault_client
        self.store = store
        self.injector = injector
        self.poller = ApprovalPoller(
            vault_client=vault_client,
            store=store,
            on_result=injector.deliver,
            poll_interval=poll_interval,
        )
        self.hook = AgentHiFiveHook(adapter=self)

        # Session context — set before each message is processed,
        # read by the hook when it detects a 202 approval response.
        self.current_session_context: dict[str, Any] = {}

    @classmethod
    def from_mcp_server_config(
        cls,
        *,
        bus: Any,
        server_config: Any,
        store_path: str | None = None,
    ) -> AgentHiFiveAdapter:
        """Create adapter from the shared MCP server config block."""
        runtime = build_runtime_config_from_mcp_server(server_config)
        vault = VaultClient(base_url=runtime.base_url, auth=runtime.auth, timeout=runtime.timeout)
        store = PendingStore(path=store_path) if store_path else PendingStore()
        injector = ResultInjector(bus=bus)

        return cls(
            vault_client=vault,
            store=store,
            injector=injector,
            poll_interval=runtime.poll_interval,
        )

    def set_session_context(
        self,
        channel: str | None = None,
        chat_id: str | None = None,
        sender_id: str | None = None,
        session_key: str | None = None,
    ) -> None:
        """Update the current session context for approval routing.

        Called by the gateway integration before each message is processed.
        """
        self.current_session_context = {
            "channel": channel,
            "chat_id": chat_id,
            "sender_id": sender_id,
            "session_key": session_key,
        }

    async def start(self) -> None:
        """Start the approval poller."""
        await self.vault.start()
        logger.info("AgentHiFive adapter starting (base_url=%s)", self.vault.base_url)
        await self.poller.start()

    async def stop(self) -> None:
        """Stop the approval poller."""
        await self.poller.stop()
        logger.info("AgentHiFive adapter stopped")

    def track_approval(
        self,
        approval_request_id: str,
        original_payload: dict[str, Any],
        download_filename: str | None = None,
        session_key: str | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        sender_id: str | None = None,
    ) -> None:
        """Register a pending approval for background tracking and replay."""
        self.poller.add_pending(
            PendingApproval(
                approval_request_id=approval_request_id,
                original_payload=original_payload,
                download_filename=download_filename,
                session_key=session_key,
                channel=channel,
                chat_id=chat_id,
                sender_id=sender_id,
            )
        )
