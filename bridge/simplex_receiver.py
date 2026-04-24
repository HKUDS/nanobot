#!/usr/bin/env python3
"""Read received SimpleX messages from the local SQLite database."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from nanobot.utils.simplex_bridge import (
    default_simplex_db_path,
    fetch_received_text_messages,
    get_latest_received_item_id,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit received SimpleX text messages as JSON lines."
    )
    parser.add_argument("--contact", required=True, help="SimpleX local display name to follow")
    parser.add_argument(
        "--db-path",
        default=str(default_simplex_db_path()),
        help="Path to simplex_v1_chat.db",
    )
    parser.add_argument(
        "--after-id",
        type=int,
        default=0,
        help="Only emit messages with chat_item_id greater than this value",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum messages to emit per poll",
    )
    parser.add_argument(
        "--latest-id",
        action="store_true",
        help="Print the latest received text-message id for the contact and exit",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Keep polling and emitting JSON lines",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds for --follow mode",
    )
    return parser.parse_args()


def _emit_messages(db_path: Path, contact: str, after_id: int, limit: int) -> int:
    last_seen = after_id
    for msg in fetch_received_text_messages(db_path, contact, after_id=after_id, limit=limit):
        print(
            json.dumps(
                {
                    "id": msg.chat_item_id,
                    "contact": msg.contact_name,
                    "text": msg.text,
                    "timestamp": msg.item_ts,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        last_seen = msg.chat_item_id
    return last_seen


def main() -> int:
    args = _parse_args()
    db_path = Path(args.db_path).expanduser().resolve()

    if args.latest_id:
        print(get_latest_received_item_id(db_path, args.contact))
        return 0

    after_id = max(args.after_id, 0)
    if not args.follow:
        _emit_messages(db_path, args.contact, after_id, args.limit)
        return 0

    while True:
        after_id = _emit_messages(db_path, args.contact, after_id, args.limit)
        time.sleep(max(args.poll_interval, 0.1))


if __name__ == "__main__":
    raise SystemExit(main())
