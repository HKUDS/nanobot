"""Initialize a local Docker instance without replacing existing settings."""

import os
import secrets
import sys
from pathlib import Path

from filelock import FileLock

from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.config.errors import ConfigLoadError
from nanobot.config.loader import save_config, validate_config


def initialize_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(path.parent / ".docker-bootstrap.lock"):
        if path.exists():
            print(f"[entrypoint] existing {path} found — leaving it in place")
            print(f"[entrypoint] WebUI password: {path} (channels.websocket.tokenIssueSecret)")
            return

        web_token = os.environ.get("NANOBOT_WEB_TOKEN") or secrets.token_hex(16)
        api_key = os.environ.get("NANOBOT_API_KEY") or secrets.token_hex(16)
        websocket = WebSocketConfig(
            enabled=True, host="0.0.0.0", token_issue_secret=web_token,
            websocket_requires_token=True,
        )
        config = validate_config({
            "gateway": {"host": "0.0.0.0"},
            "channels": {"websocket": websocket.model_dump(by_alias=True)},
            "api": {"host": "0.0.0.0", "api_key": api_key},
        }, path)
        save_config(config, path)
        print(f"[entrypoint] initialized {path}")
        print(f"[entrypoint] WebUI: http://localhost:8765 — password: {web_token}")
        print(f"[entrypoint] OpenAI-compatible API key: {api_key}")


if __name__ == "__main__":
    try:
        initialize_config(Path(sys.argv[1]))
    except ConfigLoadError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
