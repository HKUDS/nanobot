"""SimpleX channel using CLI-only polling and delivery."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.utils.simplex_bridge import default_simplex_state_path

_MAX_RECENT_CONTENT_TOKENS = 50
_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})
_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".opus", ".amr"})
_FILE_REF_RE = re.compile(r"\buse\s+/fr\s+(\d+)\b", flags=re.IGNORECASE)
_SENDS_FILE_RE = re.compile(r"\bsends\s+file\s+([^\s]+)", flags=re.IGNORECASE)
_VOICE_PLACEHOLDER_RE = re.compile(r"^voice\s+message\s*\([0-9:]+\)$", flags=re.IGNORECASE)
_FR_HINT_RE = re.compile(r"\s*\n?\s*use\s+/fr\s+\d+[^\n]*", flags=re.IGNORECASE)
_FSTATUS_PATH_RE = re.compile(r"\bpath:\s*(.+)\s*$", flags=re.IGNORECASE)
_MEDIA_SETTLE_ATTEMPTS = 20
_MEDIA_SETTLE_DELAY_S = 0.25


class SimplexConfig(Base):
    """SimpleX CLI channel configuration."""

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
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
    outbound_image_command: str = "/img"
    outbound_file_command: str = "/f"


def _state_file_path(raw_state_file: str, chat_id: str) -> Path:
    if raw_state_file.strip():
        return Path(raw_state_file).expanduser().resolve()
    return default_simplex_state_path(chat_id)


def _load_bridge_state(path: Path) -> tuple[str | None, list[str]]:
    if not path.exists():
        return None, []
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data.get("last_seen_token")
    token = value if isinstance(value, str) and value.strip() else None
    raw_recent = data.get("recent_content_tokens")
    if not isinstance(raw_recent, list):
        return token, []
    recent = [item for item in raw_recent if isinstance(item, str) and item.strip()]
    return token, recent[-_MAX_RECENT_CONTENT_TOKENS:]


def _save_bridge_state(path: Path, last_seen_token: str | None, recent_content_tokens: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "last_seen_token": last_seen_token,
                "recent_content_tokens": recent_content_tokens[-_MAX_RECENT_CONTENT_TOKENS:],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _message_token(raw_line: str) -> str:
    return hashlib.sha1(raw_line.encode("utf-8")).hexdigest()


def _content_dedup_token(chat_id: str, text: str) -> str:
    payload = f"{chat_id}\0{text}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _append_recent_content_token(tokens: list[str], token: str) -> None:
    if token in tokens:
        return
    tokens.append(token)
    if len(tokens) > _MAX_RECENT_CONTENT_TOKENS:
        del tokens[:-_MAX_RECENT_CONTENT_TOKENS]


def _strip_leading_time_prefix(line: str) -> str:
    return re.sub(r"^[0-9][0-9:.-]*\s+", "", line, count=1)


def _extract_contact_text(contact: str, line: str) -> str | None:
    prefix = f"{contact}> "
    if line.startswith(prefix):
        return line[len(prefix) :]
    return None


def _parse_tail_output(contact: str, raw_stdout: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    current_token: str | None = None
    current_lines: list[str] | None = None

    def flush_current() -> None:
        nonlocal current_token, current_lines
        if current_token is None or current_lines is None:
            return
        text = "\n".join(current_lines).strip()
        if text:
            rows.append((current_token, text))
        current_token = None
        current_lines = None

    for raw_line in raw_stdout.splitlines():
        line = raw_line.rstrip("\r")
        stripped_line = line.strip()
        if not stripped_line:
            if current_lines is not None:
                current_lines.append("")
            continue

        line_no_ts = _strip_leading_time_prefix(stripped_line)
        text = _extract_contact_text(contact, stripped_line)
        if text is None:
            text = _extract_contact_text(contact, line_no_ts)

        if text is not None:
            flush_current()
            current_token = _message_token(raw_line)
            current_lines = [text]
            continue

        outbound_prefix = f"@{contact}> "
        if stripped_line.startswith(outbound_prefix) or line_no_ts.startswith(outbound_prefix):
            flush_current()
            continue

        if current_lines is not None:
            current_lines.append(line_no_ts)

    flush_current()
    return rows


def _quote_simplex_arg(raw: str) -> str:
    escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class SimplexChannel(BaseChannel):
    """SimpleX channel implementation that talks to simplex-chat CLI directly."""

    name = "simplex"
    display_name = "SimpleX"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return SimplexConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = SimplexConfig.model_validate(config)
        super().__init__(config, bus)
        self._last_seen_token: str | None = None
        self._recent_content_tokens: list[str] = []
        self._inbound_media_dir = get_media_dir("simplex")

    async def _run_simplex_command(self, command_text: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            self.config.simplex_cmd,
            "-e",
            command_text,
            "-t",
            str(self.config.simplex_timeout),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            int(proc.returncode or 0),
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def _run_receiver_once(self) -> list[tuple[str, str]]:
        command = f"/tail @{self.config.contact} {self.config.receive_limit}"
        rc, stdout, stderr = await self._run_simplex_command(command)
        if rc != 0:
            raise RuntimeError(f"simplex-chat tail failed: {stderr.strip()}")
        return _parse_tail_output(self.config.contact, stdout)

    async def _send_text(self, text: str) -> None:
        rc, _, stderr = await self._run_simplex_command(f"@{self.config.contact} {text}")
        if rc != 0:
            raise RuntimeError(f"simplex-chat send failed: {stderr.strip()}")

    async def _send_media_file(self, raw_path: str) -> None:
        path = Path(raw_path).expanduser().resolve(strict=False)
        if not path.exists():
            raise RuntimeError(f"SimpleX attachment not found: {path}")

        command_prefix = (
            self.config.outbound_image_command
            if path.suffix.lower() in _IMAGE_EXTENSIONS
            else self.config.outbound_file_command
        )
        command = f"{command_prefix} @{self.config.contact} {_quote_simplex_arg(str(path))}"
        rc, _, stderr = await self._run_simplex_command(command)
        if rc != 0:
            raise RuntimeError(f"simplex-chat media send failed: {stderr.strip()}")

    @staticmethod
    def _extract_file_reference(text: str) -> tuple[int | None, str | None]:
        ref_match = _FILE_REF_RE.search(text)
        file_match = _SENDS_FILE_RE.search(text)
        file_ref = int(ref_match.group(1)) if ref_match else None
        filename = file_match.group(1) if file_match else None
        return file_ref, filename

    async def _resolve_non_empty_media(self, candidate: Path) -> str | None:
        path = candidate.expanduser().resolve(strict=False)
        for _ in range(_MEDIA_SETTLE_ATTEMPTS):
            if path.exists() and path.is_file():
                size = path.stat().st_size
                if size > 0:
                    return str(path)
            await asyncio.sleep(_MEDIA_SETTLE_DELAY_S)
        if path.exists() and path.is_file() and path.stat().st_size == 0:
            logger.warning("SimpleX retrieved zero-byte file: {}", path)
        return None

    @staticmethod
    def _sanitize_file_hint(text: str) -> str:
        sanitized = _FR_HINT_RE.sub("", text).strip()
        return sanitized or text

    def _inbound_target_path(self, file_ref: int, filename_hint: str | None) -> Path:
        name = filename_hint.strip() if filename_hint else ""
        if not name:
            name = f"simplex_{file_ref}.bin"
        return (self._inbound_media_dir / Path(name).name).resolve(strict=False)

    async def _query_fstatus_path(self, file_ref: int) -> str | None:
        rc, stdout, _ = await self._run_simplex_command(f"/fstatus {file_ref}")
        if rc != 0:
            return None
        for raw_line in stdout.splitlines():
            match = _FSTATUS_PATH_RE.search(raw_line.strip())
            if match:
                resolved = await self._resolve_non_empty_media(Path(match.group(1).strip()))
                if resolved:
                    return resolved
        return None

    async def _retrieve_inbound_file(self, file_ref: int, filename_hint: str | None) -> str | None:
        self._inbound_media_dir.mkdir(parents=True, exist_ok=True)
        target_path = self._inbound_target_path(file_ref, filename_hint)
        commands = [
            f"/freceive {file_ref} {_quote_simplex_arg(str(target_path))}",
            f"/fr {file_ref} {_quote_simplex_arg(str(target_path))}",
        ]

        last_stdout = ""
        last_stderr = ""
        saw_already_receiving = False

        for command in commands:
            rc, stdout, stderr = await self._run_simplex_command(command)
            last_stdout = stdout
            last_stderr = stderr
            logger.debug("SimpleX inbound retrieve cmd='{}' rc={}", command, rc)
            if rc != 0:
                continue

            if "already being received" in stdout.lower():
                saw_already_receiving = True

            resolved = await self._resolve_non_empty_media(target_path)
            if resolved:
                return resolved

            status_path = await self._query_fstatus_path(file_ref)
            if status_path:
                return status_path

        if saw_already_receiving:
            cancel_cmd = f"/fcancel {file_ref}"
            cancel_rc, cancel_stdout, cancel_stderr = await self._run_simplex_command(cancel_cmd)
            logger.debug("SimpleX inbound retrieve cmd='{}' rc={}", cancel_cmd, cancel_rc)
            if cancel_rc == 0:
                retry_cmd = f"/freceive {file_ref} {_quote_simplex_arg(str(target_path))}"
                retry_rc, retry_stdout, retry_stderr = await self._run_simplex_command(retry_cmd)
                logger.debug("SimpleX inbound retrieve cmd='{}' rc={}", retry_cmd, retry_rc)
                last_stdout = retry_stdout or cancel_stdout
                last_stderr = retry_stderr or cancel_stderr
                if retry_rc == 0:
                    resolved = await self._resolve_non_empty_media(target_path)
                    if resolved:
                        return resolved
                    status_path = await self._query_fstatus_path(file_ref)
                    if status_path:
                        return status_path

        logger.warning(
            "SimpleX inbound file retrieval produced no local file for /fr {}. stdout='{}' stderr='{}'",
            file_ref,
            last_stdout.strip(),
            last_stderr.strip(),
        )
        return None

    async def _prepare_inbound_message(self, text: str) -> tuple[str, list[str]]:
        file_ref, filename_hint = self._extract_file_reference(text)
        if file_ref is None:
            return text, []

        sanitized_text = self._sanitize_file_hint(text)

        media_path = await self._retrieve_inbound_file(file_ref, filename_hint)
        if not media_path:
            return sanitized_text, []

        content = sanitized_text
        if Path(media_path).suffix.lower() in _AUDIO_EXTENSIONS:
            transcription = await self.transcribe_audio(media_path)
            if transcription:
                content = f"{sanitized_text}\n[transcription: {transcription}]"
            else:
                content = f"{sanitized_text}\n[Voice Message: Transcription failed]"

        return content, [media_path]

    async def _forward_messages(self, messages: list[tuple[str, str]], state_file: Path) -> None:
        start_idx = 0
        watermark_found = False
        if self._last_seen_token:
            for idx in range(len(messages) - 1, -1, -1):
                if messages[idx][0] == self._last_seen_token:
                    start_idx = idx + 1
                    watermark_found = True
                    break

        if self._last_seen_token is None and self.config.bootstrap == "latest":
            self._last_seen_token = messages[-1][0]
            _save_bridge_state(state_file, self._last_seen_token, self._recent_content_tokens)
            return

        uncertain_replay = bool(self._last_seen_token) and not watermark_found
        recent_content_set = set(self._recent_content_tokens)
        advanced_any = False

        window = messages[start_idx:]
        prepared_cache: dict[str, tuple[str, list[str]]] = {}

        for idx, (token, text) in enumerate(window):
            content_token = _content_dedup_token(self.config.chat_id, text)
            if uncertain_replay and content_token in recent_content_set:
                logger.debug("SimpleX skipped probable replay token={} chat_id={}", token, self.config.chat_id)
                self._last_seen_token = token
                advanced_any = True
                continue

            # Suppress voice placeholder only if the next file-hint message actually resolves media.
            if _VOICE_PLACEHOLDER_RE.match(text.strip()) and idx + 1 < len(window):
                next_token, next_text = window[idx + 1]
                if self._extract_file_reference(next_text)[0] is not None:
                    prepared = prepared_cache.get(next_token)
                    if prepared is None:
                        prepared = await self._prepare_inbound_message(next_text)
                        prepared_cache[next_token] = prepared
                    if prepared[1]:
                        logger.debug("SimpleX suppressed placeholder voice line token={}", token)
                        self._last_seen_token = token
                        _append_recent_content_token(self._recent_content_tokens, content_token)
                        recent_content_set.add(content_token)
                        advanced_any = True
                        continue

            content, media = prepared_cache.pop(token, None) or await self._prepare_inbound_message(text)

            await self._handle_message(
                sender_id=self.config.contact,
                chat_id=self.config.chat_id,
                content=content,
                media=media,
            )
            self._last_seen_token = token
            _append_recent_content_token(self._recent_content_tokens, content_token)
            recent_content_set.add(content_token)
            advanced_any = True

        if advanced_any:
            _save_bridge_state(state_file, self._last_seen_token, self._recent_content_tokens)

    async def login(self, force: bool = False) -> bool:
        """SimpleX does not provide an interactive login flow."""
        if force:
            logger.info("SimpleX login does not support --force")
        logger.error("SimpleX has no login flow. Enable channels.simplex and run `nanobot gateway`.")
        return False

    async def start(self) -> None:
        """Poll simplex-chat and forward inbound messages into nanobot."""
        if not self.config.chat_id:
            raise RuntimeError("SimpleX requires channels.simplex.chatId")
        if not self.config.contact:
            raise RuntimeError("SimpleX requires channels.simplex.contact")

        state_file = _state_file_path(self.config.state_file, self.config.chat_id)
        self._last_seen_token, self._recent_content_tokens = _load_bridge_state(state_file)
        self._running = True

        while self._running:
            try:
                messages = await self._run_receiver_once()
                if messages:
                    await self._forward_messages(messages, state_file)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("SimpleX poll failed: {}", exc)

            await asyncio.sleep(max(self.config.poll_interval, 0.1))

    async def stop(self) -> None:
        """Stop polling loop."""
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """Send outbound text and attachments via simplex-chat CLI."""
        if msg.chat_id and msg.chat_id != self.config.chat_id:
            logger.warning(
                "SimpleX is configured for chat_id={}, but got outbound chat_id={}; using configured contact",
                self.config.chat_id,
                msg.chat_id,
            )

        text = msg.content.strip()
        if text:
            await self._send_text(text)

        for media_path in msg.media:
            await self._send_media_file(media_path)
