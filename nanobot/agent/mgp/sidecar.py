"""Async MGP sidecar for nanobot.

The sidecar is a thin wrapper over ``mgp_client.AsyncMGPClient`` that:

* builds canonical :class:`RuntimeState` objects from per-call channel/session info,
* fans the tool's ``recall`` requests into ``client.search_memory``,
* fans Consolidator/Dream extracted facts into ``client.write_candidate`` calls,
* swallows transport errors when ``fail_open=True`` (default) so MGP outages
  never break the host nanobot loop,
* records ``_last_recall`` / ``_last_commits`` for the ``/mgp-status`` command.

``mgp_client`` is imported lazily here — this module is only imported by
``build_sidecar`` after the optional dependency check succeeds.
"""

from __future__ import annotations

import asyncio
import getpass
import time
from typing import TYPE_CHECKING, Any

# Synthetic chat_id / sender_id placeholders that should NOT be treated as a
# real user identity. Anything matching falls through to ``default_user_id``.
_SYNTHETIC_USER_IDS = frozenset({"user", "direct", "dream"})

import httpx
from loguru import logger
from mgp_client import AsyncMGPClient
from mgp_client.errors import MGPError

from .mappers import (
    build_memory_candidate,
    build_policy_context,
    build_search_query,
    normalize_search_results,
)
from .models import (
    CommitOutcome,
    ParsedFact,
    RecallIntent,
    RecallOutcome,
    RuntimeState,
)
from .parsers import parse_consolidator_bullets, parse_dream_phase1_tags

if TYPE_CHECKING:
    from nanobot.config.schema import MGPConfig


# Cap how many CommitOutcome objects we keep for /mgp-status display.
_LAST_COMMITS_KEEP = 32


class AsyncMGPSidecar:
    """Async wrapper around ``mgp_client.AsyncMGPClient`` tailored for nanobot.

    One instance per :class:`AgentLoop`. The underlying httpx client is created
    lazily on first use and reused thereafter; call :meth:`close` on shutdown.
    """

    def __init__(self, config: "MGPConfig", *, workspace_id: str | None = None) -> None:
        self.config = config
        # workspace_id is optional but recommended — used both as tenant
        # fallback (workspace_as_tenant) and as the stable subject for
        # agent-scoped Dream commits.
        self._workspace_id = workspace_id or "nanobot-workspace"
        self._client: AsyncMGPClient | None = None
        self._client_lock = asyncio.Lock()
        self._last_recall: RecallOutcome | None = None
        self._last_recall_query: str | None = None
        self._last_recall_latency_ms: float | None = None
        self._last_recall_at: float | None = None
        self._last_commits: list[CommitOutcome] = []

    def _default_user_id(self) -> str:
        """Resolve the fallback subject for synthetic-channel runtimes.

        Priority: ``config.default_user_id`` (explicit) → ``getpass.getuser()``
        (OS login) → ``"user"`` (last-resort literal, only hit on exotic OSes
        where ``getpass`` raises).
        """
        if self.config.default_user_id:
            return self.config.default_user_id
        try:
            return getpass.getuser() or "user"
        except Exception:  # noqa: BLE001 - getpass can raise on misconfigured envs
            return "user"

    # -- runtime construction ----------------------------------------------

    def build_runtime(
        self,
        *,
        channel: str | None,
        chat_id: str | None,
        session_key: str | None = None,
        sender_id: str | None = None,
    ) -> RuntimeState:
        """Construct a :class:`RuntimeState` from per-call routing context.

        ``user_id`` derivation priority:
            1. ``sender_id`` (when provided and not a synthetic placeholder
               like ``"user"``)
            2. ``chat_id`` (when not a synthetic placeholder like ``"direct"``
               or ``"dream"``)
            3. ``config.default_user_id`` (configured fallback)
            4. ``getpass.getuser()`` (OS login — keeps separate workstations /
               accounts isolated even when nothing is configured)

        Treating ``"direct"``/``"dream"`` as synthetic is critical for the
        Dream commit path: Dream operates at workspace scope but its
        ``[USER]`` tags MUST land under the real subject the CLI uses, or
        ``recall_memory(scope="user")`` will never find them.

        ``tenant_id`` derivation:
            1. ``config.tenant_id`` if set,
            2. else ``self._workspace_id`` when ``workspace_as_tenant=True``,
            3. else ``None``.
        """
        resolved_channel = channel or "cli"
        resolved_chat_id = chat_id
        resolved_session_key = session_key or (
            f"{resolved_channel}:{resolved_chat_id}" if resolved_chat_id else f"{resolved_channel}:direct"
        )

        if sender_id and sender_id not in _SYNTHETIC_USER_IDS:
            user_id = sender_id
        elif resolved_chat_id and resolved_chat_id not in _SYNTHETIC_USER_IDS:
            user_id = resolved_chat_id
        else:
            user_id = self._default_user_id()

        if self.config.tenant_id:
            tenant_id = self.config.tenant_id
        elif self.config.workspace_as_tenant:
            tenant_id = self._workspace_id
        else:
            tenant_id = None

        return RuntimeState(
            actor_agent=self.config.actor_agent,
            user_id=user_id,
            session_key=resolved_session_key,
            workspace_id=self._workspace_id,
            channel=resolved_channel,
            chat_id=resolved_chat_id,
            tenant_id=tenant_id,
        )

    # -- client lifecycle --------------------------------------------------

    async def _get_client(self) -> AsyncMGPClient:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                headers: dict[str, str] = {}
                if self.config.api_key:
                    headers["Authorization"] = f"Bearer {self.config.api_key}"
                self._client = AsyncMGPClient(
                    self.config.gateway_url,
                    timeout=self.config.timeout,
                    headers=headers or None,
                )
        return self._client

    async def close(self) -> None:
        """Close the underlying httpx client. Idempotent."""
        if self._client is None:
            return
        try:
            await self._client.close()
        except Exception:  # noqa: BLE001 - shutdown best-effort
            logger.debug("MGP sidecar: error during client close (ignored)")
        finally:
            self._client = None

    # -- recall ------------------------------------------------------------

    async def recall(self, runtime: RuntimeState, intent: RecallIntent) -> RecallOutcome:
        """Run a single ``search_memory`` call. ``fail_open`` swallows errors."""
        started = time.monotonic()
        self._last_recall_query = intent.query
        try:
            client = await self._get_client()
            policy_context = build_policy_context(runtime, "search")
            query = build_search_query(runtime, intent)
            response = await client.search_memory(policy_context, query)
            items = normalize_search_results(response.data)
            outcome = RecallOutcome(
                executed=True,
                degraded=False,
                results=items,
                request_id=response.request_id,
            )
        except (MGPError, httpx.HTTPError, ValueError) as exc:
            if not self.config.fail_open:
                raise
            outcome = RecallOutcome(
                executed=False,
                degraded=True,
                error_code=getattr(exc, "code", type(exc).__name__),
                error_message=str(exc),
            )
            logger.warning("MGP recall degraded ({}): {}", outcome.error_code, outcome.error_message)
        finally:
            self._last_recall_latency_ms = (time.monotonic() - started) * 1000.0
            self._last_recall_at = time.time()

        self._last_recall = outcome
        return outcome

    # -- commit ------------------------------------------------------------

    async def commit_bullets(self, runtime: RuntimeState, summary: str) -> list[CommitOutcome]:
        """Parse a Consolidator summary into facts and fan out write_candidate."""
        if not self.config.enable_consolidator_commit:
            return []
        facts = parse_consolidator_bullets(
            summary,
            source_ref=f"nanobot:{runtime.channel}:{runtime.session_key}:consolidator",
        )
        return await self._commit_facts(runtime, facts)

    async def commit_dream_tags(self, runtime: RuntimeState, analysis: str) -> list[CommitOutcome]:
        """Parse a Dream Phase-1 analysis into facts and fan out write_candidate."""
        if not self.config.enable_dream_commit:
            return []
        facts = parse_dream_phase1_tags(
            analysis,
            source_ref=f"nanobot:{runtime.workspace_id}:dream",
        )
        return await self._commit_facts(runtime, facts)

    async def _commit_facts(self, runtime: RuntimeState, facts: list[ParsedFact]) -> list[CommitOutcome]:
        if not facts:
            return []
        client = await self._get_client()
        policy_context = build_policy_context(runtime, "write")
        candidates = [build_memory_candidate(runtime, f) for f in facts]

        async def _one(candidate: Any) -> CommitOutcome:
            try:
                response = await client.write_candidate(
                    policy_context,
                    candidate,
                    merge_hint=candidate.merge_hint,
                )
                returned_memory = (response.data or {}).get("memory") or {}
                return CommitOutcome(
                    executed=True,
                    written=True,
                    memory_id=returned_memory.get("memory_id"),
                    request_id=response.request_id,
                )
            except (MGPError, httpx.HTTPError, ValueError) as exc:
                if not self.config.fail_open:
                    raise
                outcome = CommitOutcome(
                    executed=False,
                    written=False,
                    error_code=getattr(exc, "code", type(exc).__name__),
                    error_message=str(exc),
                )
                logger.warning(
                    "MGP commit degraded ({}): {}", outcome.error_code, outcome.error_message,
                )
                return outcome

        outcomes = await asyncio.gather(*[_one(c) for c in candidates], return_exceptions=False)
        # Track recent commits for /mgp-status (bounded ring).
        self._last_commits.extend(outcomes)
        if len(self._last_commits) > _LAST_COMMITS_KEEP:
            self._last_commits = self._last_commits[-_LAST_COMMITS_KEEP:]
        return list(outcomes)

    # -- /mgp-status helpers ----------------------------------------------

    @property
    def last_recall(self) -> RecallOutcome | None:
        return self._last_recall

    @property
    def last_recall_query(self) -> str | None:
        return self._last_recall_query

    @property
    def last_recall_latency_ms(self) -> float | None:
        return self._last_recall_latency_ms

    @property
    def last_recall_at(self) -> float | None:
        return self._last_recall_at

    @property
    def last_commits(self) -> list[CommitOutcome]:
        return list(self._last_commits)
