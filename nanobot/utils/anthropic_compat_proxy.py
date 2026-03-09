from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

DEFAULT_MODEL_TARGET = "glm-5"
DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 8045
HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
ALIAS_MODELS = {
    "haiku",
    "opus",
    "opusplan",
    "sonnet",
}


def should_rewrite_model(model: str) -> bool:
    value = model.strip()
    if not value:
        return False
    if value == DEFAULT_MODEL_TARGET:
        return True
    if value in ALIAS_MODELS:
        return True
    if value.startswith("claude-"):
        return True
    return False


def rewrite_model_name(model: str, target_model: str) -> str:
    return target_model if should_rewrite_model(model) else model


def rewrite_json_payload(payload: dict[str, Any], target_model: str) -> tuple[dict[str, Any], bool]:
    original = payload.get("model")
    if not isinstance(original, str):
        return payload, False
    rewritten = rewrite_model_name(original, target_model)
    if rewritten == original:
        return payload, False
    updated = dict(payload)
    updated["model"] = rewritten
    return updated, True


def filtered_headers(items: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {k: v for k, v in items if k.lower() not in HOP_BY_HOP_HEADERS}


def join_upstream_url(base_url: str, tail: str, query_string: str) -> str:
    cleaned = base_url.rstrip("/")
    path = tail if tail.startswith("/") else f"/{tail}"
    if urlsplit(cleaned).path.endswith("/v1"):
        while path.startswith("/v1/"):
            path = path[3:]
    url = f"{cleaned}{path}"
    if query_string:
        return f"{url}?{query_string}"
    return url


async def handle_models(request: web.Request) -> web.Response:
    app = request.app
    upstream_base = app["upstream_base"]
    upstream_key = app["upstream_key"]
    target_model = app["target_model"]
    upstream_url = join_upstream_url(upstream_base, "/models", request.query_string)
    headers = filtered_headers(request.headers.items())
    headers["x-api-key"] = upstream_key

    async with app["session"].get(upstream_url, headers=headers) as upstream:
        body = await upstream.read()
        response_headers = filtered_headers(upstream.headers.items())
        if upstream.status != 200:
            return web.Response(status=upstream.status, headers=response_headers, body=body)

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return web.Response(status=200, headers=response_headers, body=body)

    data = payload.get("data")
    if isinstance(data, list):
        synthetic = [
            {"id": "claude-opus-4-1", "display_name": "Claude Opus 4.1", "type": "model"},
            {"id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6", "type": "model"},
            {"id": "claude-3-5-haiku-latest", "display_name": "Claude Haiku", "type": "model"},
            {"id": target_model, "display_name": target_model, "type": "model"},
        ]
        existing = {
            item.get("id")
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for item in synthetic:
            if item["id"] not in existing:
                data.insert(0, item)

    response_headers.pop("Content-Type", None)
    response_headers.pop("content-type", None)
    return web.json_response(payload, status=200, headers=response_headers)


async def handle_proxy(request: web.Request) -> web.StreamResponse:
    app = request.app
    upstream_base = app["upstream_base"]
    upstream_key = app["upstream_key"]
    target_model = app["target_model"]

    if request.path.rstrip("/").endswith("/models"):
        return await handle_models(request)

    upstream_url = join_upstream_url(upstream_base, request.path, request.query_string)
    headers = filtered_headers(request.headers.items())
    headers["x-api-key"] = upstream_key

    body = await request.read()
    content_type = request.headers.get("content-type", "")
    rewritten = False

    if body and "application/json" in content_type:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            payload, rewritten = rewrite_json_payload(payload, target_model)
            if rewritten:
                body = json.dumps(payload, ensure_ascii=True).encode("utf-8")

    if rewritten:
        print(f"[anthropic-compat-proxy] rewrote model for {request.method} {request.path}", flush=True)

    async with app["session"].request(
        request.method,
        upstream_url,
        headers=headers,
        data=body if body else None,
    ) as upstream:
        response_headers = filtered_headers(upstream.headers.items())
        if "text/event-stream" in upstream.headers.get("content-type", ""):
            print(
                f"[anthropic-compat-proxy] {request.method} {request.path} -> {upstream.status} {upstream_url}",
                flush=True,
            )
            response = web.StreamResponse(status=upstream.status, headers=response_headers)
            await response.prepare(request)
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
            await response.write_eof()
            return response

        response_body = await upstream.read()
        print(
            f"[anthropic-compat-proxy] {request.method} {request.path} -> {upstream.status} {upstream_url}",
            flush=True,
        )
        return web.Response(status=upstream.status, headers=response_headers, body=response_body)


def create_app(
    *,
    upstream_base: str,
    upstream_key: str,
    target_model: str = DEFAULT_MODEL_TARGET,
) -> web.Application:
    app = web.Application()
    app["upstream_base"] = upstream_base.rstrip("/")
    app["upstream_key"] = upstream_key
    app["target_model"] = target_model

    async def on_startup(app: web.Application) -> None:
        timeout = aiohttp.ClientTimeout(total=600)
        app["session"] = aiohttp.ClientSession(timeout=timeout)

    async def on_cleanup(app: web.Application) -> None:
        await app["session"].close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_route("*", "/{tail:.*}", handle_proxy)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Anthropic-compatible model rewrite proxy")
    parser.add_argument("--listen-host", default=os.getenv("LISTEN_HOST", DEFAULT_LISTEN_HOST))
    parser.add_argument(
        "--listen-port",
        type=int,
        default=int(os.getenv("LISTEN_PORT", str(DEFAULT_LISTEN_PORT))),
    )
    parser.add_argument(
        "--upstream-base",
        default=os.getenv("UPSTREAM_BASE_URL", "http://www.zettacore.cyou/v1"),
    )
    parser.add_argument("--upstream-key", default=os.getenv("UPSTREAM_API_KEY"))
    parser.add_argument(
        "--target-model",
        default=os.getenv("TARGET_MODEL", DEFAULT_MODEL_TARGET),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.upstream_key:
        raise SystemExit("UPSTREAM_API_KEY is required")
    app = create_app(
        upstream_base=args.upstream_base,
        upstream_key=args.upstream_key,
        target_model=args.target_model,
    )
    web.run_app(app, host=args.listen_host, port=args.listen_port)


if __name__ == "__main__":
    main()
