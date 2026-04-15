"""Background approval poller for AgentHiFive.

Polls pending approvals every N seconds. When an approval resolves:
- approved: replays the exact original request via vault, delivers result
- denied/expired: delivers a status message

Results are injected into nanobot via MessageBus.publish_inbound().
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from .pending_store import PendingStore
from .types import ApprovalResult, PendingApproval
from .vault_client import VaultClient

logger = logging.getLogger(__name__)


class ApprovalPoller:
    """Polls AgentHiFive for approval status changes and handles replay."""

    def __init__(
        self,
        vault_client: VaultClient,
        store: PendingStore,
        on_result: Callable[[ApprovalResult, PendingApproval], Awaitable[None]],
        poll_interval: float = 5.0,
    ):
        self.vault = vault_client
        self.store = store
        self.on_result = on_result
        self.poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Approval poller started (interval=%.1fs)", self.poll_interval)

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Approval poller stopped")

    def add_pending(self, approval: PendingApproval) -> None:
        """Register a new pending approval to watch."""
        self.store.add(approval)
        logger.info("Watching approval: %s", approval.approval_request_id)

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Error in approval poll cycle")
            await asyncio.sleep(self.poll_interval)

    async def _poll_once(self) -> None:
        pending = self.store.load()
        if not pending:
            return

        for approval in pending:
            try:
                status_data = await self.vault.poll_approval(approval.approval_request_id)
                status = status_data.get("status", "unknown")

                if status == "pending":
                    continue

                if status == "approved":
                    await self._handle_approved(approval)
                elif status in ("denied", "expired"):
                    await self._handle_denied_or_expired(approval, status)
                elif status == "consumed":
                    # Already consumed (maybe by agent cooperating) — clean up
                    logger.info(
                        "Approval %s already consumed — removing from watch",
                        approval.approval_request_id,
                    )
                    self.store.remove(approval.approval_request_id)
                elif status == "not_found":
                    logger.warning("Approval %s not found — removing", approval.approval_request_id)
                    self.store.remove(approval.approval_request_id)
                else:
                    logger.warning(
                        "Unknown approval status: %s for %s", status, approval.approval_request_id
                    )

            except Exception:
                logger.exception("Failed to poll approval %s", approval.approval_request_id)

    async def _handle_approved(self, approval: PendingApproval) -> None:
        """Replay the original request and deliver the result."""
        logger.info("Approval granted: %s — replaying", approval.approval_request_id)
        try:
            replay = await self.vault.execute_replay(
                approval.original_payload,
                approval.approval_request_id,
                filename_hint=approval.download_filename,
            )

            if replay.ok:
                # Successful execution
                await self.on_result(
                    ApprovalResult(
                        approval_request_id=approval.approval_request_id,
                        status="approved",
                        execution_result=replay.body,
                    ),
                    approval,
                )
            elif replay.is_fingerprint_mismatch:
                # Should not happen (adapter replays stored payload) but handle explicitly
                logger.error(
                    "Fingerprint mismatch on replay for %s — this is a bug",
                    approval.approval_request_id,
                )
                await self.on_result(
                    ApprovalResult(
                        approval_request_id=approval.approval_request_id,
                        status="approved",
                        error="Replay rejected: request payload fingerprint mismatch (this should not happen)",
                    ),
                    approval,
                )
            else:
                # Vault returned an error (403 policy, 500 internal, etc.)
                error_msg = replay.body.get("error", f"Vault returned HTTP {replay.status_code}")
                hint = replay.body.get("hint", "")
                logger.warning(
                    "Replay failed for %s: %s %s",
                    approval.approval_request_id,
                    replay.status_code,
                    error_msg,
                )
                await self.on_result(
                    ApprovalResult(
                        approval_request_id=approval.approval_request_id,
                        status="approved",
                        error=f"{error_msg}{(' — ' + hint) if hint else ''}",
                        execution_result=replay.body,
                    ),
                    approval,
                )
        except Exception as e:
            logger.exception("Replay network error for approval %s", approval.approval_request_id)
            await self.on_result(
                ApprovalResult(
                    approval_request_id=approval.approval_request_id,
                    status="approved",
                    error=f"Replay failed: {e}",
                ),
                approval,
            )
        finally:
            self.store.remove(approval.approval_request_id)

    async def _handle_denied_or_expired(self, approval: PendingApproval, status: str) -> None:
        """Deliver denial/expiry notification."""
        logger.info("Approval %s: %s", status, approval.approval_request_id)
        await self.on_result(
            ApprovalResult(
                approval_request_id=approval.approval_request_id,
                status=status,
            ),
            approval,
        )
        self.store.remove(approval.approval_request_id)
