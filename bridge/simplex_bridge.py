#!/usr/bin/env python3
"""Bridge SimpleX messages into nanobot's WebSocket channel."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
import websockets

from nanobot.utils.simplex_bridge import default_simplex_state_path, extract_simplex_reply_text

_DEFAULT_CONFIG_PATH = Path.home() / ".nanobot" / "config.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bridge one SimpleX contact through nanobot's WebSocket channel."
    )
    parser.add_argument(
        "--config",
        default=str(_DEFAULT_CONFIG_PATH),
        help="Path to nanobot config.json (used to load channels.simplex settings)",
    )
    parser.add_argument(
        "--websocket-url",
        default="",
        help="nanobot WebSocket URL, including client_id query parameter",
    )
    parser.add_argument(
        "--chat-id",
        default="",
        help="Fixed nanobot chat_id to attach and publish into",
    )
    parser.add_argument(
        "--contact",
        default="",
        help="SimpleX contact/display name (must match the local display name exactly)",
    )
    parser.add_argument(
        "--simplex-cmd",
        default="",
        help="Path to simplex-chat binary (default: simplex-chat from PATH)",
    )
    parser.add_argument(
        "--simplex-timeout",
        type=int,
        default=None,
        help="Seconds passed to simplex-chat -t flag (default: 3)",
    )
    parser.add_argument(
        "--state-file",
        default="",
        help="Optional JSON state file; defaults to ~/.nanobot/simplex-bridge/<chat>.json",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="How often to poll the receiver script for new inbound SimpleX messages",
    )
    parser.add_argument(
        "--receive-limit",
        type=int,
        default=None,
        help="How many latest contact messages the receive command should return per poll",
    )
    parser.add_argument(
        "--bootstrap",
        choices=("latest", "all"),
        default=None,
        help="How to initialize the watermark when no state file exists",
    )
    parser.add_argument(
        "--reconnect-delay",
        type=float,
        default=None,
        help="Seconds to wait before reconnecting to nanobot",
    )
    return parser.parse_args()


def _state_file_path(raw_state_file: str, chat_id: str) -> Path:
    if raw_state_file.strip():
        return Path(raw_state_file).expanduser().resolve()
    return default_simplex_state_path(chat_id)


def _log(message: str) -> None:
    print(f"[simplex-bridge] {message}", file=sys.stderr, flush=True)


def _load_config(path: str) -> dict[str, Any]:
    cfg_path = Path(path).expanduser().resolve()
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _build_websocket_url(cfg: dict[str, Any]) -> str:
    channels = cfg.get("channels") if isinstance(cfg, dict) else {}
    simplex = channels.get("simplex") if isinstance(channels, dict) else {}
    websocket = channels.get("websocket") if isinstance(channels, dict) else {}

    if isinstance(simplex, dict):
        direct_url = str(simplex.get("websocketUrl") or "").strip()
        if direct_url:
            return direct_url

    host = str(websocket.get("host") or "127.0.0.1").strip()
    port = int(websocket.get("port") or 8765)
    path = str(websocket.get("path") or "/").strip() or "/"

    client_id = ""
    if isinstance(simplex, dict):
        client_id = str(simplex.get("clientId") or "").strip()
    if not client_id and isinstance(websocket, dict):
        allow_from = websocket.get("allowFrom")
        if isinstance(allow_from, list) and allow_from:
            first = allow_from[0]
            client_id = str(first).strip() if first is not None else ""

    if not client_id:
        return ""

    qs = urlencode({"client_id": client_id})
    return f"ws://{host}:{port}{path}?{qs}"


def _resolve_args(args: argparse.Namespace) -> argparse.Namespace:
    cfg = _load_config(args.config)
    channels = cfg.get("channels") if isinstance(cfg, dict) else {}
    simplex = channels.get("simplex") if isinstance(channels, dict) else {}
    simplex = simplex if isinstance(simplex, dict) else {}

    args.websocket_url = args.websocket_url.strip() or _build_websocket_url(cfg)
    args.chat_id = args.chat_id.strip() or str(simplex.get("chatId") or "").strip()
    args.contact = args.contact.strip() or str(simplex.get("contact") or "").strip()
    args.simplex_cmd = args.simplex_cmd.strip() or str(simplex.get("simplexCmd") or "simplex-chat").strip()
    args.state_file = args.state_file.strip() or str(simplex.get("stateFile") or "").strip()

    if args.poll_interval is None:
        args.poll_interval = float(simplex.get("pollInterval", 2.0))
    if args.receive_limit is None:
        args.receive_limit = int(simplex.get("receiveLimit", 20))
    if args.simplex_timeout is None:
        args.simplex_timeout = int(simplex.get("simplexTimeout", 3))
    if args.bootstrap is None:
        args.bootstrap = str(simplex.get("bootstrap") or "latest")
    if args.reconnect_delay is None:
        args.reconnect_delay = float(simplex.get("reconnectDelay", 5.0))

    missing: list[str] = []
    if not args.websocket_url:
        missing.append("websocket URL (channels.simplex.websocketUrl OR channels.simplex.clientId + channels.websocket host/port/path)")
    if not args.chat_id:
        missing.append("chat_id (channels.simplex.chatId)")
    if not args.contact:
        missing.append("contact (channels.simplex.contact)")

    if missing:
        raise SystemExit("Missing SimpleX bridge settings: " + "; ".join(missing))

    args.bootstrap = "all" if args.bootstrap == "all" else "latest"
    return args


def _load_last_seen_token(path: Path) -> str | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data.get("last_seen_token")
    return value if isinstance(value, str) and value.strip() else None


def _save_last_seen_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last_seen_token": token}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _message_token(raw_line: str, data: dict[str, Any] | None = None) -> str:
    return hashlib.sha1(raw_line.encode("utf-8")).hexdigest()


def _strip_leading_time_prefix(line: str) -> str:
    """Drop a leading time-like token (e.g. '14:04 ') if present."""
    return re.sub(r"^[0-9][0-9:.-]*\s+", "", line, count=1)


def _extract_contact_text(contact: str, line: str) -> str | None:
    # In simplex-chat /tail output, inbound messages from the contact are shown
    # as "<Contact> ...", while outbound echoes are typically "@<Contact> ...".
    # To avoid self-echo loops, accept only the inbound contact marker.
    prefix = f"{contact}> "
    if line.startswith(prefix):
        return line[len(prefix) :].strip()
    return None


def _parse_tail_output(contact: str, raw_stdout: str) -> list[tuple[str, str]]:
    """Extract `(token, text)` pairs from simplex-chat /tail output for *contact*."""
    rows: list[tuple[str, str]] = []
    for raw_line in raw_stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        text = _extract_contact_text(contact, line)
        if text is None:
            line_no_ts = _strip_leading_time_prefix(line)
            text = _extract_contact_text(contact, line_no_ts)
        if text:
            rows.append((_message_token(raw_line), text))
    return rows


async def _run_receiver_once(args: argparse.Namespace) -> list[tuple[str, str]]:
    proc = await asyncio.create_subprocess_exec(
        args.simplex_cmd,
        "-e", f"/tail @{args.contact} {args.receive_limit}",
        "-t", str(args.simplex_timeout),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return _parse_tail_output(args.contact, stdout.decode("utf-8", errors="replace"))


async def _send_to_simplex(simplex_cmd: str, text: str, contact: str, timeout: int) -> None:
    proc = await asyncio.create_subprocess_exec(
        simplex_cmd,
        "-e", f"@{contact} {text}",
        "-t", str(timeout),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"simplex-chat send failed: {detail}")


async def _forward_simplex_inbound(
    ws: Any,
    args: argparse.Namespace,
    state_file: Path,
    stop_event: asyncio.Event,
) -> None:
    last_seen_token = _load_last_seen_token(state_file)

    while not stop_event.is_set():
        messages = await _run_receiver_once(args)
        if not messages:
            await asyncio.sleep(max(args.poll_interval, 0.1))
            continue

        start_idx = 0
        if last_seen_token:
            for idx in range(len(messages) - 1, -1, -1):
                if messages[idx][0] == last_seen_token:
                    start_idx = idx + 1
                    break

        if last_seen_token is None and args.bootstrap == "latest":
            _save_last_seen_token(state_file, messages[-1][0])
            last_seen_token = messages[-1][0]
            await asyncio.sleep(max(args.poll_interval, 0.1))
            continue

        delivered_any = False
        for token, text in messages[start_idx:]:
            await ws.send(
                json.dumps(
                    {
                        "type": "message",
                        "chat_id": args.chat_id,
                        "content": text,
                    },
                    ensure_ascii=False,
                )
            )
            _log(f"forwarded inbound SimpleX message token={token} to chat_id={args.chat_id}")
            last_seen_token = token
            delivered_any = True

        if delivered_any and last_seen_token is not None:
            _save_last_seen_token(state_file, last_seen_token)

        await asyncio.sleep(max(args.poll_interval, 0.1))


async def _consume_nanobot_outbound(
    ws: Any,
    args: argparse.Namespace,
    stop_event: asyncio.Event,
) -> None:
    async for raw in ws:
        payload = json.loads(raw)
        reply = extract_simplex_reply_text(payload, chat_id=args.chat_id)
        if reply is None:
            continue
        await _send_to_simplex(args.simplex_cmd, reply, args.contact, args.simplex_timeout)
        _log(f"delivered outbound reply to simplex-chat (chars={len(reply)})")
    stop_event.set()


async def _run_connected(args: argparse.Namespace, state_file: Path) -> None:
    _log(f"connecting to {args.websocket_url}")
    async with websockets.connect(args.websocket_url) as ws:
        raw_ready = await ws.recv()
        ready = json.loads(raw_ready)
        if ready.get("event") != "ready":
            raise RuntimeError(f"expected ready event, got: {ready!r}")

        await ws.send(
            json.dumps({"type": "attach", "chat_id": args.chat_id}, ensure_ascii=False)
        )
        _log(f"attached WebSocket client to {args.chat_id}")

        stop_event = asyncio.Event()
        inbound_task = asyncio.create_task(_forward_simplex_inbound(ws, args, state_file, stop_event))
        outbound_task = asyncio.create_task(_consume_nanobot_outbound(ws, args, stop_event))
        done, pending = await asyncio.wait(
            {inbound_task, outbound_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except asyncio.CancelledError:
                pass

        for task in done:
            task.result()


async def _run_forever(args: argparse.Namespace) -> None:
    state_file = _state_file_path(args.state_file, args.chat_id)
    while True:
        try:
            await _run_connected(args, state_file)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log(f"{exc}; reconnecting in {args.reconnect_delay:.1f}s")
            await asyncio.sleep(max(args.reconnect_delay, 0.1))


def main() -> int:
    args = _resolve_args(_parse_args())
    try:
        asyncio.run(_run_forever(args))
    except KeyboardInterrupt:
        _log("stopped")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
