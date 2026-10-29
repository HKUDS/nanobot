"""Real SDK coverage, isolated from pytest's process-global OpenAI instrumentation."""

import asyncio
import base64
import json
import subprocess
import sys
from textwrap import dedent

import pytest
from aiohttp import web


@pytest.mark.parametrize(("api", "stream", "mode"), [
    ("chat_completions", False, "enabled"),
    ("chat_completions", True, "enabled"),
    ("responses", False, "enabled"),
    ("responses", True, "enabled"),
    ("chat_completions", False, "disabled"),
    ("responses", True, "disabled"),
])
async def test_real_openai_wrapper_uses_startup_client(api, stream, mode):
    pytest.importorskip("langfuse")
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    exports = []

    async def collect(request):
        payload = ExportTraceServiceRequest.FromString(await request.read())
        spans = [
            span
            for resource in payload.resource_spans
            for scope in resource.scope_spans
            for span in scope.spans
        ]
        exports.append((request.path, request.headers.get("authorization"), spans))
        return web.Response(body=b"", content_type="application/x-protobuf")

    app = web.Application()
    app.router.add_post("/{path:.*}", collect)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        endpoint = f"http://127.0.0.1:{runner.addresses[0][1]}"
        script = dedent('''
            import asyncio
            import json
            import os
            import sys

            import httpx
            from openai import AsyncOpenAI

            from nanobot.config.schema import Config
            from nanobot.observability.langfuse import initialize_langfuse
            from nanobot.providers.factory import make_provider

            endpoint, api, stream_arg, mode = sys.argv[1:]
            stream = stream_arg == "True"
            for name in ("OTEL_EXPORTER_OTLP_HEADERS", "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
                         "LANGFUSE_TRACING_ENABLED", "OTEL_SDK_DISABLED"):
                os.environ.pop(name, None)
            os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-legacy"
            os.environ["LANGFUSE_SECRET_KEY"] = "sk-legacy"
            os.environ["LANGFUSE_TRACING_ENABLED"] = "true" if mode == "disabled" else "false"
            config = Config.model_validate({
                "agents": {"defaults": {
                    "provider": "custom", "model": "fixture-model",
                    "api": {"supportedApis": [api]},
                }},
                "providers": {"custom": {"apiBase": "https://model.example/v1", "apiKey": "model-key"}},
                "observability": {"langfuse": {
                    "enabled": mode != "disabled", "baseUrl": endpoint,
                    "publicKey": "pk-explicit", "secretKey": "sk-explicit",
                }},
            })
            runtime = initialize_langfuse(config)
            # A settings save and first model creation happen after startup.
            config.observability.langfuse.enabled = not config.observability.langfuse.enabled
            config.observability.langfuse.secret_key = "saved-but-not-running"
            calls = []

            def answer(request):
                calls.append(request)
                body = json.loads(request.content)
                if api == "responses":
                    response = {
                        "id": "resp_fixture", "object": "response", "status": "completed",
                        "model": "fixture-model", "created_at": 1,
                        "output": [{
                            "id": "msg_fixture", "type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": "answer", "annotations": []}],
                        }],
                        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                    }
                    events = [
                        {"type": "response.output_text.delta", "delta": "answer"},
                        {"type": "response.completed", "response": response},
                    ]
                else:
                    usage = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
                    response = {
                        "id": "chat_fixture", "object": "chat.completion", "created": 1,
                        "model": "fixture-model", "usage": usage,
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "answer"},
                                     "finish_reason": "stop"}],
                    }
                    events = [{
                        "id": "chat_fixture", "object": "chat.completion.chunk", "created": 1,
                        "model": "fixture-model", "usage": usage,
                        "choices": [{"index": 0, "delta": {"role": "assistant", "content": "answer"},
                                     "finish_reason": "stop"}],
                    }]
                if not body.get("stream"):
                    return httpx.Response(200, json=response)
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream"},
                    content="".join("data: " + json.dumps(event) + "\\n\\n" for event in events),
                )

            async def run():
                provider = make_provider(config)
                provider._client = AsyncOpenAI(
                    api_key="model-key", base_url="https://model.example/v1",
                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(answer)),
                )
                try:
                    invoke = provider.chat_stream if stream else provider.chat
                    result = await invoke([{"role": "user", "content": "hello"}])
                    assert result.content == "answer", result
                    assert len(calls) == 1
                    assert "langfuse_public_key" not in json.loads(calls[0].content)
                finally:
                    await provider.aclose()

            try:
                asyncio.run(run())
            finally:
                runtime.shutdown()
        ''')
        completed = await asyncio.to_thread(
            subprocess.run, [sys.executable, "-c", script, endpoint, api, str(stream), mode],
            capture_output=True, text=True, timeout=40,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
    finally:
        await runner.cleanup()

    if mode != "enabled":
        assert exports == []
        return
    assert len(exports) == 1
    path, authorization, spans = exports[0]
    assert path == "/api/public/otel/v1/traces"
    assert authorization == "Basic " + base64.b64encode(b"pk-explicit:sk-explicit").decode()
    assert len(spans) == 1
    attributes = {item.key: item.value.string_value for item in spans[0].attributes}
    assert attributes["langfuse.observation.type"] == "generation"
    assert "answer" in attributes["langfuse.observation.output"]
    assert json.loads(attributes["langfuse.observation.usage_details"])["total_tokens"] == 5
