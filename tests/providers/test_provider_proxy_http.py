from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.fixture
def recording_proxy():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            if self.path.endswith("/messages"):
                payload = {
                    "id": "msg_test", "type": "message", "role": "assistant",
                    "model": "test-model", "content": [{"type": "text", "text": "proxied"}],
                    "stop_reason": "end_turn", "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            elif self.path.endswith("/responses"):
                payload = {
                    "id": "resp_test", "object": "response", "created_at": 0,
                    "status": "completed", "model": "test-model",
                    "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                                "status": "completed", "content": [{"type": "output_text",
                                "text": "proxied", "annotations": []}]}],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                }
            elif self.path.endswith("/converse"):
                payload = {
                    "output": {"message": {"role": "assistant", "content": [{"text": "proxied"}]}},
                    "stopReason": "end_turn", "usage": {"inputTokens": 1, "outputTokens": 1,
                                                           "totalTokens": 2},
                    "metrics": {"latencyMs": 1},
                }
            else:
                payload = {
                    "id": "chat_test", "object": "chat.completion", "created": 0,
                    "model": "test-model", "choices": [{"index": 0, "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "proxied"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("backend", ["anthropic", "azure", "bedrock", "copilot", "openai_compat"])
async def test_public_chat_reaches_explicit_proxy_despite_environment(monkeypatch, recording_proxy, backend):
    proxy, requests = recording_proxy
    # An invalid origin proves the network request cannot bypass the recording proxy.
    origin = "http://provider.invalid"
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "*")
    if backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(api_key="test-key", api_base=origin, proxy=proxy,
                                     default_model="test-model")
    elif backend == "azure":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
        provider = AzureOpenAIProvider(api_key="test-key", api_base=origin, proxy=proxy,
                                       default_model="test-model")
    elif backend == "bedrock":
        pytest.importorskip("boto3")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
        monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
        from nanobot.providers.bedrock_provider import BedrockProvider
        provider = BedrockProvider(api_base=origin, region="us-east-1", proxy=proxy,
                                  default_model="test-model")
    elif backend == "copilot":
        from nanobot.providers.github_copilot_provider import GitHubCopilotProvider
        monkeypatch.setenv("NANOBOT_COPILOT_BASE_URL", f"{origin}/v1")
        provider = GitHubCopilotProvider(proxy=proxy, default_model="test-model")
        # No user credentials or external login; only the network transport is under test.
        provider._copilot_access_token = "test-token"
        provider._copilot_expires_at = time.time() + 3600
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        provider = OpenAICompatProvider(api_key="test-key", api_base=f"{origin}/v1",
                                        proxy=proxy, default_model="test-model")
    try:
        response = await asyncio.wait_for(
            provider.chat([{"role": "user", "content": "hello"}]), timeout=10,
        )
        assert response.content == "proxied"
        assert len(requests) == 1
        assert requests[0][0].startswith(origin)
    finally:
        if backend == "bedrock":
            provider._client.close()
        else:
            await provider._client.close()
