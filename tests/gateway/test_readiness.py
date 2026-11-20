import json
import threading
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nanobot.gateway.runtime import (
    GatewayHealthIdentity,
    GatewayRuntime,
    GatewayRuntimePaths,
    GatewayStartOptions,
    _gateway_health_ready,
)


@pytest.fixture
def health_server():
    reply = {"status": 200, "body": b'{"status":"ok"}'}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/health"
            self.send_response(reply["status"])
            self.end_headers()
            self.wfile.write(reply["body"])

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], reply
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_restart_requires_identity_while_legacy_health_still_works(tmp_path, health_server):
    port, reply = health_server
    runtime = GatewayRuntime(paths=GatewayRuntimePaths.for_instance(data_dir=tmp_path))
    identity = GatewayHealthIdentity("a" * 64, "b" * 32, "0.3.6")
    with runtime.foreground_instance(GatewayStartOptions(port=port)):
        runtime.publish_health_host("127.0.0.1")
        assert _gateway_health_ready("127.0.0.1", port)
        assert not runtime.verify_ready(identity)
        reply["body"] = json.dumps({
            "status": "ok", "ready": True,
            "runtime": {**asdict(identity), "future_optional_field": "ignored"},
        }).encode()
        assert runtime.verify_ready(identity)
        for wrong in (
            replace(identity, instance_id="c" * 64),
            replace(identity, run_id="d" * 32),
            replace(identity, version="0.3.5"),
        ):
            assert not runtime.verify_ready(wrong)
    assert not runtime.verify_ready(identity)


@pytest.mark.parametrize("status,body", [
    (503, b'{"status":"ok","ready":true}'),
    (200, b'{"status":"ok","ready":false}'),
    (200, b'{"status":"ok"}' + b' ' * 4096),
    (200, b'[]'),
])
def test_unready_or_invalid_response_cannot_confirm_restart(health_server, status, body):
    port, reply = health_server
    reply.update(status=status, body=body)
    assert not _gateway_health_ready("127.0.0.1", port, expected=GatewayHealthIdentity("a" * 64, "b" * 32, "0.3.6"))
