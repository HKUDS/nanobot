"""Wire parsing and error classification for the WhatsApp Agent Platform.

Everything in this module is a pure function over untrusted response data. The
runtime calls it at the boundary so the rest of the channel works with concrete
types, matching nanobot's "type dynamic boundaries at the edge" constraint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast

from nanobot.security.network import validate_url_target

API_BASE = "https://api.whatsapp.com/agent/v1"
# Bump only alongside a deliberate protocol change; sent as a header on polls.
USER_AGENT = "nanobot-whatsapp-agent"

TEXT_MAX_CHARS = 4096
CAPTION_MAX_CHARS = 1024

# Per-method rolling-window limits from the Developer Manual, section 6.
RATE_LIMITS = {
    "messages": 12,
    "statuses": 12,
    "updates": 15,
    "media": 12,
}
_RATE_WINDOW_SECONDS = 60.0

# error.code values that carry a specific recovery contract.
CODE_INVALID_TOKEN = 100
CODE_MISSING_AUTH = 190
CODE_RATE_LIMITED = 130429
CODE_NOT_CREATOR = 131005
CODE_BAD_REQUEST = 131009
CODE_NOT_ACCEPTED = 131016
CODE_MEDIA_REJECTED = 131053
CODE_POLL_REPLACED = 1752041

MEDIA_LIMITS = {
    "image": 5 * 1024 * 1024,
    "sticker": 500 * 1024,
    "video": 16 * 1024 * 1024,
    "audio": 16 * 1024 * 1024,
    "document": 16 * 1024 * 1024,
    "application/octet-stream": 16 * 1024 * 1024,
}

ACCEPTED_UPLOAD_MIME = {
    # image
    "image/jpeg",
    "image/png",
    # video
    "video/mp4",
    "video/3gpp",
    # audio
    "audio/aac",
    "audio/mp4",
    "audio/mpeg",
    "audio/amr",
    "audio/ogg",
    "audio/opus",
    # document
    "application/pdf",
    "text/plain",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    # sticker
    "image/webp",
    # generic
    "application/octet-stream",
}

# MIME aliases the platform normalizes to a canonical accepted type.
_MIME_ALIASES = {
    "audio/x-m4a": "audio/mp4",
    "audio/x-hx-aac-adts": "audio/aac",
    "image/jpg": "image/jpeg",
}

MessageKind = Literal[
    "text",
    "image",
    "audio",
    "video",
    "document",
    "sticker",
    "reaction",
    "unknown",
]


@dataclass(frozen=True)
class InboundMedia:
    """Media handle attached to an inbound message."""

    media_id: str
    mime_type: str
    sha256_base64: str = ""
    caption: str = ""
    filename: str = ""
    voice: bool = False
    animated: bool = False


@dataclass(frozen=True)
class InboundMessage:
    """One inbound WhatsApp message, normalized for the agent pipeline."""

    wamid: str
    sender: str
    timestamp: int | None
    kind: MessageKind
    text: str = ""
    media: InboundMedia | None = None
    # Reply context: the quoted wamid and its author (``user:`` or ``agent:``).
    context_id: str = ""
    context_from: str = ""
    # Reaction payload (receive-only).
    reaction_to: str = ""
    reaction_emoji: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_user_authored(self) -> bool:
        """Whether the creator, rather than the agent, sent this message."""
        return self.sender.startswith("user:")


@dataclass(frozen=True)
class InboundStatus:
    """A delivery or read receipt for a previously sent message."""

    wamid: str
    status: str
    recipient: str
    timestamp: int | None


@dataclass(frozen=True)
class PollBatch:
    """One parsed ``GET /updates`` response."""

    messages: list[InboundMessage]
    statuses: list[InboundStatus]
    next_offset: int | None


@dataclass(frozen=True)
class APIError:
    """Classified failure from any Agent Platform endpoint."""

    status_code: int
    code: int
    message: str
    details: str
    fbtrace_id: str

    @property
    def invalid_token(self) -> bool:
        """Whether the response means the token was rotated or revoked.

        A malformed or missing ``Authorization`` header yields 401/190. A token
        that is present but not valid yields 400/100 — the API deliberately does
        not use 401 for that case.
        """
        return self.status_code == 401 or (
            self.status_code == 400
            and self.code == CODE_INVALID_TOKEN
            and not self._is_length_rejection
        )

    @property
    def _is_length_rejection(self) -> bool:
        """400/100 is also used for over-length text, captions, and bad media ids."""
        if self.status_code not in (400, 404):
            return False
        # The manual sets ``message`` to the bare field name for a length cap.
        return self.message.strip() in {"text.body", "text", "caption", "body"}

    @property
    def poll_replaced(self) -> bool:
        """Another process opened a newer poll for this agent."""
        return self.status_code == 409 or self.code == CODE_POLL_REPLACED

    @property
    def rate_limited(self) -> bool:
        return self.status_code == 429 or self.code == CODE_RATE_LIMITED

    @property
    def retryable(self) -> bool:
        """Whether an unchanged retry can succeed.

        ``503``/``131016`` means the message was not accepted for delivery, so
        resending is safe. A plain ``500`` may or may not have been delivered,
        so it is deliberately excluded from automatic retries.
        """
        return self.rate_limited or self.code == CODE_NOT_ACCEPTED

    @property
    def ambiguous(self) -> bool:
        """Whether the outcome cannot be determined and a retry may duplicate."""
        return self.status_code >= 500 and not self.retryable

    def __str__(self) -> str:
        parts = [f"HTTP {self.status_code}", f"code={self.code}"]
        if self.fbtrace_id:
            parts.append(f"fbtrace_id={self.fbtrace_id}")
        if self.message:
            parts.append(self.message)
        return " ".join(parts)


class WhatsAppAgentError(Exception):
    """Base class for channel-owned failures."""


class WhatsAppAgentAuthError(WhatsAppAgentError):
    """The API token was rejected; retrying cannot succeed."""


class WhatsAppAgentAPIError(WhatsAppAgentError):
    """A classified non-auth API failure."""

    def __init__(self, error: APIError) -> None:
        super().__init__(str(error))
        self.error = error


def classify_error(status_code: int, payload: Any) -> APIError:
    """Extract the structured error from a non-2xx response body."""
    body = _as_dict(payload) or {}
    error = _as_dict(body.get("error")) or {}
    raw_code = error.get("code")
    try:
        code = int(raw_code)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        code = 0
    details = ""
    error_data = _as_dict(error.get("error_data"))
    if error_data is not None:
        details = _text(error_data.get("details"))
    return APIError(
        status_code=status_code,
        code=code,
        message=_text(error.get("message")),
        details=details,
        fbtrace_id=_text(error.get("fbtrace_id")),
    )


def parse_poll_batch(payload: Any) -> PollBatch:
    """Parse a 200 ``GET /updates`` body.

    The API guarantees exactly one entry and one change, but the parser still
    reads defensively: a shape change must degrade to "no messages" rather than
    crash the poll loop.
    """
    if not isinstance(payload, dict):
        return PollBatch([], [], None)

    messages: list[InboundMessage] = []
    statuses: list[InboundStatus] = []

    for value in _change_values(cast(dict[str, Any], payload)):
        for raw in _as_list(value.get("messages")):
            message = parse_message(raw)
            if message is not None:
                messages.append(message)
        for raw in _as_list(value.get("statuses")):
            status = parse_status(raw)
            if status is not None:
                statuses.append(status)

    return PollBatch(
        messages, statuses, _optional_int(cast(dict[str, Any], payload).get("next_offset"))
    )


def _change_values(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for entry in _as_list(payload["entry"] if "entry" in payload else None):
        entry_map = _as_dict(entry)
        if entry_map is None:
            continue
        for change in _as_list(entry_map.get("changes")):
            change_map = _as_dict(change)
            if change_map is None:
                continue
            value = _as_dict(change_map.get("value"))
            if value is not None:
                values.append(value)
    return values


def parse_message(raw: Any) -> InboundMessage | None:
    """Parse one inbound message object."""
    message = _as_dict(raw)
    if message is None:
        return None
    wamid = _text(message.get("id"))
    sender = _text(message.get("from"))
    if not wamid or not sender:
        return None

    kind = _normalize_kind(raw.get("type"))
    text = ""
    media: InboundMedia | None = None
    reaction_to = ""
    reaction_emoji = ""

    if kind == "text":
        body = _as_dict(message.get("text"))
        text = _text(body.get("body")) if body is not None else ""
    elif kind == "reaction":
        reaction = _as_dict(message.get("reaction"))
        if reaction is not None:
            reaction_to = _text(reaction.get("message_id"))
            # An empty emoji means the reaction was removed.
            reaction_emoji = _text(reaction.get("emoji"))
    elif kind in {"image", "audio", "video", "document", "sticker"}:
        media = _parse_media(kind, message.get(kind))

    context_id = ""
    context_from = ""
    context = _as_dict(message.get("context"))
    if context is not None:
        # Inbound uses ``id``; outbound quoting uses ``message_id``.
        context_id = _text(context.get("id"))
        context_from = _text(context.get("from"))

    return InboundMessage(
        wamid=wamid,
        sender=sender,
        timestamp=_optional_int(message.get("timestamp")),
        kind=kind,
        text=text,
        media=media,
        context_id=context_id,
        context_from=context_from,
        reaction_to=reaction_to,
        reaction_emoji=reaction_emoji,
        raw=message,
    )


def _parse_media(kind: str, payload: Any) -> InboundMedia | None:
    media = _as_dict(payload)
    if media is None:
        return None
    media_id = _text(media.get("id"))
    if not media_id:
        return None
    return InboundMedia(
        media_id=media_id,
        mime_type=normalize_mime(_text(media.get("mime_type"))),
        sha256_base64=_text(media.get("sha256")),
        caption=_text(media.get("caption")),
        filename=_text(media.get("filename")),
        # ``voice`` and ``animated`` appear only for the matching variant.
        voice=kind == "audio" and bool(media.get("voice")),
        animated=bool(media.get("animated")),
    )


def parse_status(raw: Any) -> InboundStatus | None:
    """Parse one delivery or read receipt."""
    receipt = _as_dict(raw)
    if receipt is None:
        return None
    wamid = _text(receipt.get("id"))
    status = _text(receipt.get("status"))
    if not wamid or status not in {"delivered", "read"}:
        return None
    return InboundStatus(
        wamid=wamid,
        status=status,
        recipient=_text(receipt.get("recipient_id")),
        timestamp=_optional_int(receipt.get("timestamp")),
    )


def normalize_mime(mime_type: str) -> str:
    """Strip parameters and apply platform aliases."""
    base = mime_type.partition(";")[0].strip().lower()
    return _MIME_ALIASES.get(base, base)


def media_limit_for(mime_type: str, kind: str) -> int:
    """Return the upload size cap for a kind/MIME pair."""
    if kind == "sticker":
        return MEDIA_LIMITS["sticker"]
    if kind == "image":
        return MEDIA_LIMITS["image"]
    return MEDIA_LIMITS.get(kind, MEDIA_LIMITS["application/octet-stream"])


def outbound_kind_for_mime(mime_type: str) -> MessageKind:
    """Map a detected MIME type to the sendable message kind."""
    mime = normalize_mime(mime_type)
    if mime == "image/webp":
        return "sticker"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "document"


def quote_safe_url(url: str) -> tuple[bool, str]:
    """Validate an API-returned media URL before fetching it.

    The URL arrives from the platform, but it is still an untrusted redirect
    target, so it passes through the shared SSRF guard before any request.
    """
    if not url:
        return False, "empty URL"
    return validate_url_target(url)


def _normalize_kind(value: Any) -> MessageKind:
    kind = _text(value).lower()
    if kind in {"text", "image", "audio", "video", "document", "sticker", "reaction"}:
        return kind  # type: ignore[return-value]
    return "unknown"


def _as_dict(value: Any) -> dict[str, Any] | None:
    """Narrow an untrusted JSON value to an object at the boundary."""
    if not isinstance(value, dict):
        return None
    return cast(dict[str, Any], value)


def _as_list(value: Any) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


__all__ = [
    "ACCEPTED_UPLOAD_MIME",
    "API_BASE",
    "APIError",
    "CAPTION_MAX_CHARS",
    "CODE_BAD_REQUEST",
    "CODE_MEDIA_REJECTED",
    "CODE_NOT_ACCEPTED",
    "CODE_NOT_CREATOR",
    "CODE_POLL_REPLACED",
    "InboundMedia",
    "InboundMessage",
    "InboundStatus",
    "MEDIA_LIMITS",
    "MessageKind",
    "PollBatch",
    "RATE_LIMITS",
    "TEXT_MAX_CHARS",
    "USER_AGENT",
    "WhatsAppAgentAPIError",
    "WhatsAppAgentAuthError",
    "WhatsAppAgentError",
    "classify_error",
    "media_limit_for",
    "normalize_mime",
    "outbound_kind_for_mime",
    "parse_message",
    "parse_poll_batch",
    "parse_status",
    "quote_safe_url",
]
