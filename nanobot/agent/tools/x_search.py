"""xAI X Search tool."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import ArraySchema, BooleanSchema, StringSchema, tool_parameters_schema
from nanobot.config.schema import Base
from nanobot.providers.openai_responses import parse_response_output
from nanobot.providers.xai_oauth_auth import (
    DEFAULT_XAI_API_BASE,
    load_xai_oauth_credential,
    resolve_xai_oauth_credential,
)


class XSearchConfig(Base):
    """xAI X Search configuration."""

    enable: bool = True
    model: str = "grok-4.3"
    api_key: str = ""
    api_base: str = DEFAULT_XAI_API_BASE
    timeout_seconds: int = 180
    retries: int = 2


@dataclass(frozen=True)
class _Bearer:
    token: str
    api_base: str
    source: str


@tool_parameters(
    tool_parameters_schema(
        query=StringSchema("What to search for on X."),
        allowed_x_handles=ArraySchema(
            StringSchema("X handle without @"),
            description="Only consider posts from these X handles, max 10.",
            max_items=10,
            nullable=True,
        ),
        excluded_x_handles=ArraySchema(
            StringSchema("X handle without @"),
            description="Exclude posts from these X handles, max 10.",
            max_items=10,
            nullable=True,
        ),
        from_date=StringSchema("Optional YYYY-MM-DD start date.", nullable=True),
        to_date=StringSchema("Optional YYYY-MM-DD end date.", nullable=True),
        enable_image_understanding=BooleanSchema(
            description="Analyze images attached to matching X posts.",
            default=False,
        ),
        enable_video_understanding=BooleanSchema(
            description="Analyze videos attached to matching X posts.",
            default=False,
        ),
        required=["query"],
    )
)
class XSearchTool(Tool):
    """Search X posts and threads through xAI's server-side x_search tool."""

    name = "x_search"
    description = (
        "Search X posts, profiles, and threads using xAI Grok. "
        "Use this for current X discussion, reactions, claims, or posts."
    )
    config_key = "x_search"

    @classmethod
    def config_cls(cls):
        return XSearchConfig

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        config = getattr(ctx.config, "x_search", None)
        if not (config and config.enable):
            return False
        if config.api_key or os.environ.get("XAI_API_KEY"):
            return True
        return load_xai_oauth_credential() is not None

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(config=ctx.config.x_search)

    def __init__(self, config: XSearchConfig | None = None):
        self.config = config if config is not None else XSearchConfig()

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        query: str,
        allowed_x_handles: list[str] | None = None,
        excluded_x_handles: list[str] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        enable_image_understanding: bool = False,
        enable_video_understanding: bool = False,
        **kwargs: Any,
    ) -> str:
        _ = kwargs
        if allowed_x_handles and excluded_x_handles:
            return "Error: allowed_x_handles and excluded_x_handles are mutually exclusive"

        bearer = await asyncio.to_thread(_resolve_bearer, self.config)
        body = _build_x_search_body(
            model=self.config.model,
            query=query,
            allowed_x_handles=allowed_x_handles,
            excluded_x_handles=excluded_x_handles,
            from_date=from_date,
            to_date=to_date,
            enable_image_understanding=enable_image_understanding,
            enable_video_understanding=enable_video_understanding,
        )
        response = await _post_x_search(bearer, body, self.config)
        answer = parse_response_output(response).content or ""
        result = {
            "success": True,
            "provider": "xai",
            "tool": "x_search",
            "credential_source": bearer.source,
            "model": self.config.model,
            "query": query,
            "answer": answer,
            "citations": response.get("citations") or [],
            "inline_citations": _extract_inline_citations(response),
        }
        return json.dumps(result, ensure_ascii=False)


def _clean_handles(handles: list[str] | None) -> list[str] | None:
    if not handles:
        return None
    cleaned = [str(h).strip().lstrip("@") for h in handles if str(h).strip()]
    return cleaned[:10] or None


def _build_x_search_body(
    *,
    model: str,
    query: str,
    allowed_x_handles: list[str] | None = None,
    excluded_x_handles: list[str] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    enable_image_understanding: bool = False,
    enable_video_understanding: bool = False,
) -> dict[str, Any]:
    tool: dict[str, Any] = {"type": "x_search"}
    allowed = _clean_handles(allowed_x_handles)
    excluded = _clean_handles(excluded_x_handles)
    if allowed:
        tool["allowed_x_handles"] = allowed
    if excluded:
        tool["excluded_x_handles"] = excluded
    if from_date:
        tool["from_date"] = from_date
    if to_date:
        tool["to_date"] = to_date
    if enable_image_understanding:
        tool["enable_image_understanding"] = True
    if enable_video_understanding:
        tool["enable_video_understanding"] = True

    return {
        "model": model,
        "input": [{"role": "user", "content": query}],
        "tools": [tool],
        "store": False,
    }


def _resolve_bearer(config: XSearchConfig) -> _Bearer:
    try:
        credential = resolve_xai_oauth_credential()
        return _Bearer(
            token=credential.access_token,
            api_base=credential.api_base or config.api_base,
            source="xai-oauth",
        )
    except Exception:
        api_key = config.api_key or os.environ.get("XAI_API_KEY", "")
        if api_key:
            return _Bearer(token=api_key, api_base=config.api_base or DEFAULT_XAI_API_BASE, source="xai")
        raise RuntimeError("No xAI credentials available. Run: nanobot provider login xai-oauth")


async def _post_x_search(bearer: _Bearer, body: dict[str, Any], config: XSearchConfig) -> dict[str, Any]:
    url = bearer.api_base.rstrip("/") + "/responses"
    headers = {
        "Authorization": f"Bearer {bearer.token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "nanobot (python)",
    }
    timeout = httpx.Timeout(max(config.timeout_seconds, 30), connect=20.0)
    last_error: Exception | None = None
    for attempt in range(max(config.retries, 0) + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=True) as client:
                response = await client.post(url, headers=headers, json=body)
            if response.status_code < 500:
                break
            last_error = RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
        if attempt < max(config.retries, 0):
            await asyncio.sleep(min(5.0, 1.5 * (attempt + 1)))
    else:
        raise RuntimeError(f"xAI X Search request failed: {last_error}")

    if response.status_code >= 400:
        raise RuntimeError(f"xAI X Search request failed: HTTP {response.status_code}: {response.text[:500]}")
    payload = response.json()
    return payload if isinstance(payload, dict) else {"output": []}


def _extract_inline_citations(response: dict[str, Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if not isinstance(block, dict):
                continue
            for annotation in block.get("annotations") or []:
                if isinstance(annotation, dict) and annotation.get("type") == "url_citation":
                    citations.append({
                        "url": annotation.get("url"),
                        "title": annotation.get("title"),
                        "start_index": annotation.get("start_index"),
                        "end_index": annotation.get("end_index"),
                    })
    return citations
