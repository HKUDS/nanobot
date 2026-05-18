#!/usr/bin/env python3
"""
Squad Bridge v6.0 - 军团专线同步协同脚本
===========================================
v6.0: retry+backoff, dead-letter queue, correlation_id, error event handling
v5.0: accumulate streaming deltas, exit on turn_end, safety guards (idle/LB/total)

架构位置：squad overlay（我们自维护），依赖官方 nanobot WS 协议
"""

import sys
import json
import time
import os
import uuid
import traceback
from datetime import datetime, timezone
from pathlib import Path

import websocket

from squad_config_sync import get_roster

# ── Constants ──────────────────────────────────────────────
TOTAL_TIMEOUT   = 120       # 总超时 (s)
IDLE_TIMEOUT    = 30        # 空闲超时 (s) — 覆盖 LLM 卡顿/rate limit
MAX_BUFFER_BYTES = 204800   # 200KB 硬上限 — 防垃圾/DoS
MAX_RETRIES     = 3         # 最大重试次数
RETRY_BACKOFF   = [1, 2, 4] # 指数退避 (s)
DLQ_PATH        = Path("/data/squad_dlq.jsonl")

# ── Error classification ───────────────────────────────────

# Errors that are permanent — no retry, go straight to DLQ.
PERMANENT_ERROR_PREFIXES = (
    "roster_miss:",
    "permission_denied:",
    "no_ready:",
)


def _is_transient(error: str | None) -> bool:
    """Return True if the error is worth retrying."""
    if not error:
        return True  # unknown = retryable
    for prefix in PERMANENT_ERROR_PREFIXES:
        if error.startswith(prefix):
            return False
    return True


# ── Permission check ───────────────────────────────────────

def _get_allowed_peers(sender_id: str) -> list[str] | str:
    """
    Returns:
        "*"       → Commander (in COMMANDER_WHITELIST) — can message any agent.
        ["neo", …] → Business user (in USER_AGENT_MAP) — only mapped agents.
        []        → Guest — blocked.

    sender_id can be either an HF username (DreamShepherd2006) or an agent alias
    (neo). If it's an agent alias, we reverse-lookup USER_AGENT_MAP to find the
    owning HF username, then apply permission rules.
    """
    commander_whitelist = os.environ.get("COMMANDER_WHITELIST", "")
    user_agent_map_str = os.environ.get("USER_AGENT_MAP", "")

    whitelist = [w.strip().lower() for w in commander_whitelist.split(",") if w.strip()]

    # Parse USER_AGENT_MAP and build reverse lookup (agent alias → username)
    # Format: {"username": "NANOBOT_PEER_NEO", ...}  (flat, values are strings)
    try:
        user_map = json.loads(user_agent_map_str) if user_agent_map_str else {}
    except json.JSONDecodeError:
        user_map = {}
    agent_to_user: dict[str, str] = {}
    for uname, peer_key in user_map.items():
        if isinstance(peer_key, str) and peer_key.upper().startswith("NANOBOT_PEER_"):
            agent_name = peer_key[len("NANOBOT_PEER_"):].lower()
            agent_to_user[agent_name] = uname.lower()

    # Resolve effective user
    effective = sender_id.lower()
    if effective in agent_to_user:
        effective = agent_to_user[effective]

    # Commander check
    if effective in whitelist:
        return "*"

    # Business user check
    if effective in user_map:
        peer_key = user_map[effective]
        if isinstance(peer_key, str) and peer_key.upper().startswith("NANOBOT_PEER_"):
            allowed: list[str] = [peer_key[len("NANOBOT_PEER_"):].lower()]
            return allowed

    return []


# ── Helpers ────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _make_correlation_id() -> str:
    """sq-{timestamp}-{short_uuid}"""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:4]
    return f"sq-{ts}-{short}"

def _write_dlq(entry: dict) -> None:
    """Append a dead-letter entry to the persistent DLQ file."""
    try:
        DLQ_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DLQ_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"📮 [死信队列] 已归档 → {DLQ_PATH}")
    except Exception as e:
        print(f"❌ [死信队列写入失败]: {e}", file=sys.stderr)


# ── Core: single delivery attempt ──────────────────────────

def _attempt_delivery(
    sender_alias: str,
    target_alias: str,
    message_content: str,
    correlation_id: str,
    attempt: int,
) -> tuple[bool, str | None, str | None]:
    """
    Returns (success, output_text, error_reason).
    success=True  → output_text is the response.
    success=False → error_reason is the failure classification.
    """
    roster, _ = get_roster()
    target_data = roster.get(target_alias.lower())
    if not target_data:
        return False, None, f"roster_miss:{target_alias}"

    target_chat_id = target_data["id"]
    target_port = target_data["ws_port"]

    token = os.environ.get("NANOBOT_TOKEN", "").strip()
    uri = f"ws://127.0.0.1:{target_port}/"
    if token:
        uri += f"?token={token}"

    payload = {
        "type": "message",
        "chat_id": target_chat_id,
        "content": f"[{sender_alias}]: {message_content}",
        "correlation_id": correlation_id,
    }

    try:
        ws = websocket.create_connection(uri, timeout=10)
    except Exception as e:
        return False, None, f"connection:{e}"

    try:
        greeting_raw = ws.recv()
        greeting = json.loads(greeting_raw)

        if greeting.get("event") != "ready":
            ws.close()
            return False, None, f"no_ready:{greeting.get('event','')}"

        ws.send(json.dumps(payload, ensure_ascii=False))
        print(f"  [{attempt}/3] 🚀 {sender_alias} → {target_alias} (cid={correlation_id})")

        content_buffer: list[str] = []
        buffer_size = 0
        last_content_ts = 0.0
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time

            # Guard 1: total timeout
            if elapsed > TOTAL_TIMEOUT:
                if content_buffer:
                    output = "".join(content_buffer)
                    print(f"  ⏰ 总超时 ({TOTAL_TIMEOUT}s)")
                    return True, output, None
                return False, None, "timeout:total"

            # Guard 2: idle timeout (only after content started)
            if last_content_ts and (time.time() - last_content_ts > IDLE_TIMEOUT):
                output = "".join(content_buffer)
                print(f"  ⏰ 空闲超时 ({IDLE_TIMEOUT}s)")
                return True, output, None

            try:
                raw_data = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue

            if not raw_data:
                continue

            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                continue

            event = data.get("event", "")

            # ── v6: error event handling ──
            if event == "error":
                detail = data.get("detail", "unknown")
                ws.close()
                return False, None, f"framework:{detail}"

            if event == "heartbeat":
                continue

            if event == "turn_end":
                output = "".join(content_buffer) if content_buffer else "(空响应)"
                print(f"  ✅ turn_end ({len(output)} chars)")
                ws.close()
                return True, output, None

            if event == "stream_end":
                continue

            if event == "delta":
                text = data.get("text", "")
                if text:
                    if buffer_size + len(text.encode("utf-8")) > MAX_BUFFER_BYTES:
                        remaining = MAX_BUFFER_BYTES - buffer_size
                        if remaining > 0:
                            content_buffer.append(text[:remaining])
                        content_buffer.append("\n\n[⚠️ buffer 200KB 上限截断]")
                        output = "".join(content_buffer)
                        ws.close()
                        return True, output, None
                    content_buffer.append(text)
                    buffer_size += len(text.encode("utf-8"))
                    last_content_ts = time.time()
                continue

            # content field (non-streaming fallback)
            content = data.get("content")
            if content and content.strip():
                if buffer_size + len(content.encode("utf-8")) > MAX_BUFFER_BYTES:
                    remaining = MAX_BUFFER_BYTES - buffer_size
                    if remaining > 0:
                        content_buffer.append(content[:remaining])
                    content_buffer.append("\n\n[⚠️ buffer 200KB 上限截断]")
                    output = "".join(content_buffer)
                    ws.close()
                    return True, output, None
                content_buffer.append(content)
                buffer_size += len(content.encode("utf-8"))
                last_content_ts = time.time()

        ws.close()
    except Exception as e:
        try:
            ws.close()
        except Exception:
            pass
        return False, None, f"exception:{e}"


# ── Main: retry loop + DLQ ─────────────────────────────────

def main() -> None:
    if len(sys.argv) < 4:
        print("⚠️ Usage: python3 squad_bridge.py <sender_alias> <target_alias> <message>")
        sys.exit(1)

    sender_alias = sys.argv[1].upper()
    target_alias = sys.argv[2].upper()
    message_content = " ".join(sys.argv[3:])
    correlation_id = _make_correlation_id()

    print(f"═══ Squad Bridge v6.1 ═══")
    print(f"  cid:     {correlation_id}")
    print(f"  sender:  {sender_alias}")
    print(f"  target:  {target_alias}")
    print(f"  message: {message_content[:80]}{'…' if len(message_content) > 80 else ''}")

    # ── Step 1: Permission check (v6.1) ──────────────────────
    allowed = _get_allowed_peers(sender_alias)
    if allowed == []:
        print(f"  🚫 [权限拒绝] {sender_alias} 无权发送消息（不在白名单或路由表中）")
        dlq_entry = {
            "correlation_id": correlation_id,
            "timestamp": _now_iso(),
            "sender": sender_alias,
            "target": target_alias,
            "message": message_content,
            "error": f"permission_denied:{sender_alias}",
            "retries": 0,
        }
        _write_dlq(dlq_entry)
        sys.exit(3)  # exit code 3 = permission_denied
    elif allowed != "*" and target_alias.lower() not in [a.lower() for a in allowed]:
        print(f"  🚫 [权限拒绝] {sender_alias} → {target_alias} 不在路由表中（允许: {allowed}）")
        dlq_entry = {
            "correlation_id": correlation_id,
            "timestamp": _now_iso(),
            "sender": sender_alias,
            "target": target_alias,
            "message": message_content,
            "error": f"permission_denied:{sender_alias}→{target_alias}",
            "retries": 0,
        }
        _write_dlq(dlq_entry)
        sys.exit(3)

    # ── Step 2: Delivery with retry ──────────────────────────
    last_error: str | None = None
    attempts_made = 0

    for attempt in range(1, MAX_RETRIES + 1):
        success, output, error = _attempt_delivery(
            sender_alias, target_alias, message_content, correlation_id, attempt
        )
        attempts_made = attempt

        if success:
            print(f"\n✅ [收到同步回执] ({target_alias}):\n{output}")
            sys.exit(0)

        last_error = error or "unknown"
        print(f"  ❌ 第 {attempt} 次失败: {last_error}")

        # Check if error is permanent → no retry
        if not _is_transient(last_error):
            print(f"  ⛔ 永久性错误，停止重试。")
            break

        if attempt < MAX_RETRIES:
            delay = RETRY_BACKOFF[attempt - 1]
            print(f"  🔄 {delay}s 后重试…")
            time.sleep(delay)

    # Delivery failed → dead-letter queue
    dlq_entry = {
        "correlation_id": correlation_id,
        "timestamp": _now_iso(),
        "sender": sender_alias,
        "target": target_alias,
        "message": message_content,
        "error": last_error,
        "retries": attempts_made,
    }
    _write_dlq(dlq_entry)
    print(f"\n💀 [死信] 消息已归档到 DLQ，等待 gatekeeper 重放。")
    sys.exit(2)  # exit code 2 = dead-letter


if __name__ == "__main__":
    main()
