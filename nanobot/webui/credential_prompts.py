"""Pending credential-form requests between agent tools and WebUI clients.

A tool opens a request, the WebUI renders a form for it, and a dedicated
``credential_submit``/``credential_cancel`` envelope resolves the pending
future. Submitted values travel only from the socket into the future; they
are never written to the chat transcript or surfaced to the model.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

STATUS_SUBMITTED = "submitted"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"

_RESOLVED_KEEP_LIMIT = 200
_RESOLVED_KEEP_SECONDS = 15 * 60


@dataclass(frozen=True)
class CredentialField:
    """One input row in a credential form. ``key`` is the secret key name the
    submitted value is stored under (e.g. ``LINKEDIN_EMAIL``)."""

    key: str
    label: str
    sensitive: bool = True
    required: bool = True

    def wire(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "sensitive": self.sensitive,
            "required": self.required,
        }


@dataclass
class CredentialPrompt:
    """One open credential request awaiting a WebUI form submission."""

    request_id: str
    chat_id: str
    fields: tuple[CredentialField, ...]
    expires_at: float
    future: asyncio.Future[dict[str, object]] = field(repr=False)

    def field_keys(self) -> set[str]:
        return {f.key for f in self.fields}


class CredentialPromptRegistry:
    """Process-local pending credential requests, keyed by request id."""

    def __init__(self) -> None:
        self._pending: dict[str, CredentialPrompt] = {}
        self._resolved: dict[str, tuple[str, float]] = {}

    def open(
        self,
        chat_id: str,
        fields: list[CredentialField],
        timeout_seconds: int,
    ) -> CredentialPrompt:
        prompt = CredentialPrompt(
            request_id=uuid.uuid4().hex,
            chat_id=chat_id,
            fields=tuple(fields),
            expires_at=time.time() + timeout_seconds,
            future=asyncio.get_running_loop().create_future(),
        )
        self._pending[prompt.request_id] = prompt
        return prompt

    def get(self, request_id: str) -> CredentialPrompt | None:
        """Return the open prompt, lazily expiring it when past ``expires_at``."""
        prompt = self._pending.get(request_id)
        if prompt is not None and prompt.expires_at <= time.time():
            self._finish(request_id, STATUS_EXPIRED, {})
            return None
        return prompt

    def resolved_status(self, request_id: str) -> str | None:
        """Final status for a request that already left ``_pending``."""
        self._prune_resolved()
        entry = self._resolved.get(request_id)
        return entry[0] if entry is not None else None

    def resolve(
        self,
        request_id: str,
        values: dict[str, object],
    ) -> CredentialPrompt | None:
        """Complete a pending prompt with user-submitted values.

        Only keys declared on the request are kept; everything else is dropped
        so the resolved payload never carries unexpected material.
        """
        prompt = self.get(request_id)
        if prompt is None:
            return None
        filtered = {
            field.key: str(values.get(field.key, ""))
            for field in prompt.fields
        }
        return self._finish(request_id, STATUS_SUBMITTED, filtered)

    def cancel(self, request_id: str) -> CredentialPrompt | None:
        """Complete a pending prompt as cancelled by the user."""
        if self.get(request_id) is None:
            return None
        return self._finish(request_id, STATUS_CANCELLED, {})

    def cancel_chat_prompts(self, chat_id: str) -> list[str]:
        """Cancel every pending request for a chat whose last client left."""
        cancelled: list[str] = []
        for request_id, prompt in list(self._pending.items()):
            if prompt.chat_id == chat_id:
                if self._finish(request_id, STATUS_CANCELLED, {}) is not None:
                    cancelled.append(request_id)
        return cancelled

    def drop(self, request_id: str) -> None:
        """Discard a pending entry without completing the future (tool cleanup)."""
        self._pending.pop(request_id, None)

    def _finish(
        self,
        request_id: str,
        status: str,
        values: dict[str, str],
    ) -> CredentialPrompt | None:
        prompt = self._pending.pop(request_id, None)
        if prompt is None:
            return None
        self._resolved[request_id] = (status, time.time())
        self._prune_resolved()
        if not prompt.future.done():
            prompt.future.set_result({"status": status, "values": values})
        return prompt

    def _prune_resolved(self) -> None:
        cutoff = time.time() - _RESOLVED_KEEP_SECONDS
        for key in [k for k, (_s, when) in self._resolved.items() if when < cutoff]:
            self._resolved.pop(key, None)
        while len(self._resolved) > _RESOLVED_KEEP_LIMIT:
            oldest = min(self._resolved, key=lambda k: self._resolved[k][1])
            self._resolved.pop(oldest, None)


credential_prompts = CredentialPromptRegistry()
