from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from nanobot.observe.trace import get_trace_dir
from nanobot.utils.helpers import safe_filename


def _read_trace(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _truncate_title(text: str) -> str:
    if len(text) <= 20:
        return text
    return f"{text[:20]}..."


def _stringify_title(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _extract_title(records: list[dict[str, Any]]) -> str:
    for record in records:
        if record.get("type") == "input":
            content = record.get("content")
            return _truncate_title(_stringify_title(content))
    return ""


def _list_traces(trace_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(trace_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        payload = _read_trace(path)
        if not payload:
            continue
        records = payload.get("records") or []
        items.append(
            {
                "trace_id": payload.get("trace_id"),
                "parent_trace_id": payload.get("parent_trace_id"),
                "trace_type": payload.get("trace_type"),
                "session_key": payload.get("session_key"),
                "channel": payload.get("channel"),
                "chat_id": payload.get("chat_id"),
                "message_id": payload.get("message_id"),
                "workspace": payload.get("workspace"),
                "created_at": payload.get("created_at"),
                "completed_at": payload.get("completed_at"),
                "records_count": len(records),
                "file_mtime": path.stat().st_mtime,
                "title": _extract_title(records),
            }
        )
    return items


def _send_json(handler: SimpleHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(data)


def _send_text(handler: SimpleHTTPRequestHandler, text: str, status: int = 200) -> None:
    data = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class ObserveHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, trace_dir: Path, static_dir: Path | None, **kwargs: Any):
        self.trace_dir = trace_dir
        self.static_dir = static_dir
        directory = str(static_dir) if static_dir else None
        super().__init__(*args, directory=directory, **kwargs)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/traces"):
            if parsed.path == "/api/traces":
                _send_json(self, {"traces": _list_traces(self.trace_dir)})
                return
            if parsed.path.startswith("/api/traces/"):
                trace_id = unquote(parsed.path.split("/", 3)[3])
                filename = safe_filename(trace_id)
                path = self.trace_dir / f"{filename}.json"
                if not path.exists():
                    _send_json(self, {"error": "trace not found"}, status=404)
                    return
                payload = _read_trace(path)
                if not payload:
                    _send_json(self, {"error": "invalid trace file"}, status=400)
                    return
                _send_json(self, payload)
                return
        if self.static_dir and self.static_dir.exists():
            return super().do_GET()
        _send_text(
            self,
            "<html><body><h3>Trace UI not built</h3><p>Run: cd nanobot/observe/web && npm install && npm run build</p></body></html>",
            status=200,
        )

    def send_head(self):
        if not self.static_dir or not self.static_dir.exists():
            return super().send_head()
        path = Path(self.translate_path(self.path))
        if path.is_file():
            return super().send_head()
        index = Path(self.translate_path("/index.html"))
        if index.exists():
            self.path = "/index.html"
            return super().send_head()
        return super().send_head()


def serve_observe(host: str = "127.0.0.1", port: int = 8787) -> None:
    trace_dir = get_trace_dir()
    static_dir = Path(__file__).resolve().parent / "dist"
    def handler(*args, **kwargs):
        return ObserveHandler(*args, trace_dir=trace_dir, static_dir=static_dir, **kwargs)
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
