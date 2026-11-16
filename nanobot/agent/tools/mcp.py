from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import traceback
import urllib.parse
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import AsyncExitStack, nullcontext, suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar, cast, overload

import httpx
from anyio.abc import ObjectReceiveStream
from loguru import logger
from referencing import Registry
from referencing import Resource as SchemaResource
from referencing.exceptions import Unresolvable

from nanobot.agent.tools.base import Schema, Tool, ToolResult
from nanobot.agent.tools.context import tool_log_content_allowed
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.network import NetworkConfig
from nanobot.security.network import (
    PinnedDNSAsyncTransport,
    env_proxy_applies_to_url,
    httpx_env_proxy_mounts,
    resolve_url_target,
    validate_url_target,
)
from nanobot.utils.cancellation import shield_and_drain, task_is_cancelling

if TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream
    from mcp import ClientSession
    from mcp.shared.message import SessionMessage
    from mcp.types import ContentBlock, PaginatedRequestParams, PaginatedResult, Prompt, Resource
    from mcp.types import Tool as MCPToolDefinition

    from nanobot.agent.tools.mcp_oauth import MCPOAuthHandlers
    from nanobot.config.schema import Config, MCPServerConfig

# Transient stream failures. Retrying also requires an operation safe to replay
# or proof that the tool request has not started.
_TRANSIENT_EXC_NAMES: frozenset[str] = frozenset((
    "ClosedResourceError",
    "BrokenResourceError",
    "EndOfStream",
    "BrokenPipeError",
    "ConnectionResetError",
    "ConnectionRefusedError",
    "ConnectionAbortedError",
    "ConnectionError",
))

_WINDOWS_SHELL_LAUNCHERS: frozenset[str] = frozenset(("npx", "npm", "pnpm", "yarn", "bunx"))

# Mirror the MCP SDK's httpx defaults (MCP_DEFAULT_TIMEOUT / MCP_DEFAULT_SSE_READ_TIMEOUT).
_HTTP_TIMEOUT = 30.0
_HTTP_READ_TIMEOUT = 300.0
_RELOAD_WAIT_SECONDS = 10.0
_RETRY_DELAY_SECONDS = 15.0
_MAX_CONCURRENT_STDIO_LAUNCHES = 4

# Characters allowed in tool names by model providers (Anthropic, OpenAI, etc.).
# Replace anything outside [a-zA-Z0-9_-] with underscore and collapse runs.
_SANITIZE_RE = re.compile(r"_+")
_ReconnectCallback = Callable[[str, str, Tool], Awaitable[Tool | None]]
_MCPResultT = TypeVar("_MCPResultT")
_PageT = TypeVar("_PageT", bound="PaginatedResult", covariant=True)
_EntryT = TypeVar("_EntryT")
MCPServerLoader = Callable[[], tuple[Mapping[str, "MCPServerConfig"], NetworkConfig]]
MCPRuntimeStatus = Literal["connecting", "failed", "connected"]


@dataclass(frozen=True, slots=True)
class MCPServerConnection:
    aclose: Callable[[], Awaitable[None]]
    tools: tuple[Tool, ...] = ()


class _ListPage(Protocol[_PageT]):
    @overload
    async def __call__(self) -> _PageT: ...
    @overload
    async def __call__(self, *, params: PaginatedRequestParams) -> _PageT: ...


async def _list_all(
    list_page: _ListPage[_PageT], entries: Callable[[_PageT], Sequence[_EntryT]],
) -> list[_EntryT]:
    from mcp.types import PaginatedRequestParams

    page = await list_page()
    result = list(entries(page))
    seen: set[str] = set()
    while (cursor := page.nextCursor) is not None:
        if cursor in seen:
            raise ValueError("MCP server returned a repeated pagination cursor")
        seen.add(cursor)
        page = await list_page(params=PaginatedRequestParams(cursor=cursor))
        result.extend(entries(page))
    return result


async def _close_mcp_connection(name: str, connection: MCPServerConnection) -> None:
    try:
        await connection.aclose()
    except asyncio.CancelledError:
        if task_is_cancelling():
            raise
        logger.debug("MCP server '{}' cleanup error (can be ignored)", name)
    except (RuntimeError, BaseExceptionGroup):
        logger.debug("MCP server '{}' cleanup error (can be ignored)", name)


async def _close_mcp_connections(connections: Mapping[str, MCPServerConnection]) -> None:
    cancellation: asyncio.CancelledError | None = None
    for name, connection in connections.items():
        try:
            await _close_mcp_connection(name, connection)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
    if cancellation is not None:
        raise cancellation


class _MCPReceiveStream(ObjectReceiveStream["SessionMessage | Exception"]):
    """Drop malformed progress events before the SDK logs their raw payload."""

    def __init__(self, read_stream: ObjectReceiveStream[SessionMessage | Exception]) -> None:
        self._read_stream = read_stream

    async def receive(self) -> SessionMessage | Exception:
        from mcp.types import JSONRPCNotification

        while True:
            message = await self._read_stream.receive()
            if isinstance(message, Exception):
                return message
            payload = message.message.root
            if (
                isinstance(payload, JSONRPCNotification)
                and payload.method == "notifications/progress"
                and "progressToken" not in (payload.params or {})
            ):
                continue
            return message

    async def aclose(self) -> None:
        await self._read_stream.aclose()


def _sanitize_name(name: str) -> str:
    return _SANITIZE_RE.sub("_", re.sub(r"[^a-zA-Z0-9_-]", "_", name))


_MAX_TOOL_NAME_LENGTH = 64
_HASH_LENGTH = 8


def _limit_tool_name(name: str, max_length: int = _MAX_TOOL_NAME_LENGTH) -> str:
    if len(name) <= max_length:
        return name

    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
    prefix_length = max_length - _HASH_LENGTH - 1
    return f"{name[:prefix_length]}_{digest}"


def _sanitize_mcp_tool_name(name: str) -> str:
    return _limit_tool_name(_sanitize_name(name))


def _is_transient(exc: BaseException) -> bool:
    return type(exc).__name__ in _TRANSIENT_EXC_NAMES


def _is_transient_connection_failure(exc: BaseException) -> bool:
    if isinstance(exc, BaseExceptionGroup):
        group = cast(BaseExceptionGroup[BaseException], exc)
        return bool(group.exceptions) and all(
            _is_transient_connection_failure(nested) for nested in group.exceptions
        )
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)) or _is_transient(exc)


def _log_mcp_connection_failure(
    name: str, exc: BaseException, hint: str = "", *, proxy: str | None = None,
) -> None:
    exception: Exception | bool = False
    if tool_log_content_allowed():
        details = "".join(traceback.TracebackException.from_exception(
            exc, capture_locals=False,
        ).format())
        if proxy:
            for value in (proxy, urllib.parse.unquote(proxy)):
                details = details.replace(value, _redact_url(proxy))
            # Match userinfo only with its URL delimiter, never isolated short
            # credentials that could rewrite exception types or stack text.
            userinfo = urllib.parse.urlsplit(proxy).netloc.rpartition("@")[0]
            if userinfo:
                for value in (userinfo, urllib.parse.unquote(userinfo)):
                    details = details.replace(f"{value}@", "[redacted]@")
        # Keep exception-aware sinks, but never give Loguru live frames or a raw
        # exception chain: diagnose=True would render credential-bearing locals.
        exception = Exception("\n" + details.rstrip())
    if _is_transient_connection_failure(exc):
        logger.warning("MCP server '{}': transient connection failure", name)
        logger.opt(exception=exception).debug(
            "MCP server '{}' transient connection failure details", name
        )
        return
    logger.opt(exception=exception).error("MCP server '{}': failed to connect: {}", name, hint)


def _is_session_terminated(exc: BaseException) -> bool:
    if _is_transient(exc):
        return True
    messages = [str(exc)]
    error = getattr(exc, "error", None)
    if error is not None:
        messages.append(str(getattr(error, "message", "")))
    return any(
        marker in message.lower()
        for marker in ("session terminated", "connection closed")
        for message in messages
    )


async def _probe_http_url(url: str, timeout: float = 3.0, *, proxy: str | None = None) -> bool:
    """Quick TCP probe to check if an HTTP MCP server is reachable.

    Avoids entering ``streamable_http_client`` / ``sse_client`` when the port is
    closed — those transports use anyio task groups whose cleanup can raise
    ``RuntimeError`` / ``ExceptionGroup`` that escape the caller's try/except
    and crash the event loop.
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if not port:
        port = 443 if parsed.scheme == "https" else 80
    ok, _, resolved_ips = resolve_url_target(url)
    if not ok:
        return False
    if proxy or env_proxy_applies_to_url(url):
        return True
    for target_host in resolved_ips or (host,):
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(target_host, port),
                timeout=timeout,
            )
            writer.close()
            with suppress(OSError, asyncio.TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), timeout=0.2)
            return True
        except (OSError, asyncio.TimeoutError):
            continue
    return False


def _redact_url(url: str) -> str:
    """Strip credentials and query/fragment before logging an MCP URL.

    Server URLs may embed secrets (``https://user:token@host/sse`` or a
    ``?token=`` query). Some deployments also put opaque tokens in the path, so
    log only the origin and a path placeholder.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        hostname = parts.hostname or ""
        netloc = f"[{hostname}]" if ":" in hostname else hostname
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        path = "/..." if parts.path and parts.path != "/" else parts.path
        return urllib.parse.urlunsplit((parts.scheme, netloc, path, "", ""))
    except Exception:
        return "<redacted-url>"


def _pinned_transport_kwargs(proxy: str | None = None) -> dict[str, Any]:
    if proxy:
        return {"transport": httpx.AsyncHTTPTransport(proxy=proxy), "trust_env": False}
    kwargs: dict[str, Any] = {"transport": PinnedDNSAsyncTransport()}
    mounts = httpx_env_proxy_mounts()
    if mounts:
        kwargs["mounts"] = mounts
    return kwargs


async def _validate_mcp_request_url(request: httpx.Request) -> None:
    ok, error = validate_url_target(str(request.url))
    if not ok:
        raise httpx.RequestError(
            f"Blocked unsafe MCP URL {_redact_url(str(request.url))} ({error})",
            request=request,
        )


def _mcp_http_client(
    proxy: str | None, headers: Mapping[str, str] | None,
    timeout: httpx.Timeout | None, auth: httpx.Auth | None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers, timeout=timeout, auth=auth, follow_redirects=True,
        event_hooks={"request": [_validate_mcp_request_url]}, **_pinned_transport_kwargs(proxy),
    )


def _windows_command_basename(command: str) -> str:
    return command.replace("\\", "/").rsplit("/", maxsplit=1)[-1].lower()


def _normalize_windows_stdio_command(
    command: str,
    args: list[str] | None,
    env: dict[str, str] | None,
) -> tuple[str, list[str], dict[str, str] | None]:
    normalized_args = list(args or [])
    if os.name != "nt":
        return command, normalized_args, env

    basename = _windows_command_basename(command)
    if basename in {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return command, normalized_args, env

    if basename.endswith((".exe", ".com")):
        return command, normalized_args, env

    resolved = shutil.which(command, path=(env or {}).get("PATH")) or command
    resolved_basename = _windows_command_basename(resolved)
    should_wrap = (
        basename in _WINDOWS_SHELL_LAUNCHERS
        or basename.endswith((".cmd", ".bat"))
        or resolved_basename.endswith((".cmd", ".bat"))
    )
    if not should_wrap:
        return command, normalized_args, env

    comspec = (env or {}).get("COMSPEC") or os.environ.get("COMSPEC") or "cmd.exe"
    return comspec, ["/d", "/c", command, *normalized_args], env


def _extract_nullable_branch(options: Any) -> tuple[dict[str, Any], bool] | None:
    if not isinstance(options, list):
        return None

    non_null: list[dict[str, Any]] = []
    saw_null = False
    for option in cast(list[object], options):
        if not isinstance(option, dict):
            return None
        option_schema = cast(dict[str, Any], option)
        if option_schema.get("type") == "null":
            saw_null = True
            continue
        non_null.append(option_schema)

    if saw_null and len(non_null) == 1:
        return non_null[0], True
    return None


def _rewrite_local_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Hoist arbitrary local JSON-Pointer refs into provider-compatible ``$defs``."""
    rewritten_refs: dict[str, str] = {}
    generated_defs: dict[str, Any] = {}

    def rewrite(value: Any) -> Any:
        if isinstance(value, list):
            return [rewrite(item) for item in cast(list[Any], value)]
        if not isinstance(value, dict):
            return value

        rewritten = dict(cast(dict[str, Any], value))
        raw_ref = rewritten.get("$ref")
        ref = raw_ref if isinstance(raw_ref, str) else None
        is_rewritable_ref = False
        if ref is not None and not ref.startswith("#/$defs/"):
            try:
                pointer = urllib.parse.unquote(ref[1:], errors="strict")
            except (UnicodeDecodeError, ValueError):
                pass
            else:
                is_rewritable_ref = ref.startswith("#") and (
                    not pointer or pointer.startswith("/")
                )
        if is_rewritable_ref:
            assert ref is not None
            name = rewritten_refs.get(ref)
            if name is None:
                try:
                    # Resolve only against this document, without URI scope changes or retrieval.
                    target = schema if ref == "#" else SchemaResource.opaque(schema).pointer(
                        ref[1:], Registry[Any]().resolver()
                    ).contents
                except (Unresolvable, TypeError, ValueError):
                    logger.warning("MCP tool schema contains an unresolved local $ref: {}", ref)
                else:
                    name = f"ref_{hashlib.sha256(ref.encode()).hexdigest()[:12]}"
                    existing_defs = schema.get("$defs")
                    while isinstance(existing_defs, dict) and name in existing_defs:
                        name += "_"
                    rewritten_refs[ref] = name
                    # Reserve the name before descending so recursive refs terminate.
                    generated_defs[name] = {}
                    generated_defs[name] = rewrite(target)
            if name is not None:
                rewritten["$ref"] = f"#/$defs/{name}"

        return {key: rewrite(item) for key, item in rewritten.items()}

    result = cast(dict[str, Any], rewrite(schema))
    if generated_defs:
        existing_defs = result.get("$defs")
        result["$defs"] = {
            **(existing_defs if isinstance(existing_defs, dict) else {}),
            **generated_defs,
        }
    return result


def _normalize_nullable_schema(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(schema)
    raw_type = normalized.get("type")
    if isinstance(raw_type, list):
        type_values = cast(list[Any], raw_type)
        non_null = [item for item in type_values if item != "null"]
        if "null" in type_values and len(non_null) == 1:
            normalized["type"] = non_null[0]
            normalized["nullable"] = True

    for key in ("oneOf", "anyOf"):
        nullable_branch = _extract_nullable_branch(normalized.get(key))
        if nullable_branch is not None:
            branch, _ = nullable_branch
            merged = {k: v for k, v in normalized.items() if k != key}
            merged.update(branch)
            normalized = merged
            normalized["nullable"] = True
            break

    properties = normalized.get("properties")
    if isinstance(properties, dict):
        property_schemas = cast(dict[str, Any], properties)
        normalized["properties"] = {
            name: (
                _normalize_nullable_schema(cast(dict[str, Any], prop))
                if isinstance(prop, dict)
                else prop
            )
            for name, prop in property_schemas.items()
        }
    items = normalized.get("items")
    if isinstance(items, dict):
        normalized["items"] = _normalize_nullable_schema(cast(dict[str, Any], items))
    definitions = normalized.get("$defs")
    if isinstance(definitions, dict):
        definition_schemas = cast(dict[str, Any], definitions)
        normalized["$defs"] = {
            name: _normalize_nullable_schema(cast(dict[str, Any], definition))
            if isinstance(definition, dict)
            else definition
            for name, definition in definition_schemas.items()
        }

    if normalized.get("type") == "object":
        normalized.setdefault("properties", {})
        normalized.setdefault("required", [])
    return normalized


def _normalize_schema_for_openai(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    schema_mapping = cast(dict[str, Any], schema)
    return _normalize_nullable_schema(_rewrite_local_schema_refs(schema_mapping))


class _MCPWrapperBase(Tool):
    """Common reconnect handling for wrappers bound to one MCP server session."""

    _plugin_discoverable = False
    _session: ClientSession
    _server_name: str
    _name: str
    _replay_safe: bool

    def _set_mcp_connection(
        self, session: ClientSession, server_name: str, *, replay_safe: bool,
    ) -> None:
        self._session = session
        self._server_name = server_name
        self._replay_safe = replay_safe
        self._reconnect: _ReconnectCallback | None = None

    def set_reconnect_handler(self, reconnect: _ReconnectCallback) -> None:
        self._reconnect = reconnect

    async def _refresh_session_after_termination(
        self,
        exc: BaseException,
        already_refreshed: bool,
        capability_kind: str,
    ) -> bool:
        if already_refreshed or not _is_session_terminated(exc) or self._reconnect is None:
            return False
        logger.warning(
            "MCP {} '{}' session terminated; reconnecting server '{}'",
            capability_kind,
            self._name,
            self._server_name,
        )
        refreshed_tool = await self._reconnect(self._server_name, self._name, self)
        if not isinstance(refreshed_tool, _MCPWrapperBase):
            logger.warning(
                "MCP {} '{}' could not refresh session for server '{}'",
                capability_kind,
                self._name,
                self._server_name,
            )
            return False
        self._session = refreshed_tool._session
        self._replay_safe = refreshed_tool._replay_safe
        return True

    def _unknown_tool_outcome(self, reason: str) -> ToolResult:
        logger.warning(
            "MCP tool '{}' {}; outcome unknown, not replaying", self._name, reason,
        )
        return ToolResult.error(
            f"(MCP tool call outcome is unknown; {reason}. The operation "
            "may have completed and was not replayed after this failure. Check its outcome before "
            "retrying to avoid duplicate side effects.)"
        )

    async def _request_with_recovery(
        self,
        request: Callable[[ClientSession], Awaitable[_MCPResultT]],
        timeout: float,
        capability_kind: Literal["tool", "resource", "prompt"],
    ) -> _MCPResultT | ToolResult:
        from mcp.shared.exceptions import McpError

        operation = f"{capability_kind} {'read' if capability_kind == 'resource' else 'call'}"
        refreshed_session = False
        retried = False
        request_started = False

        async def attempt(session: ClientSession, replay_safe: bool) -> _MCPResultT:
            nonlocal request_started
            if not replay_safe and self._reconnect is not None:
                # Repair stale sessions before submitting a non-replayable call.
                # A failed ping proves that this attempt never called the tool;
                # an exception from call_tool itself cannot provide that proof.
                await session.send_ping()
            request_started = True
            return await request(session)

        while True:
            # Keep the declaration bound to the actual session used by this
            # attempt, even if another call reconnects this wrapper meanwhile.
            session, replay_safe = self._session, self._replay_safe
            if request_started and not replay_safe:
                return self._unknown_tool_outcome("no longer permits safe replay after reconnect")
            try:
                # Preflight and submission share the existing per-attempt timeout.
                return await asyncio.wait_for(attempt(session, replay_safe), timeout=timeout)
            except asyncio.TimeoutError:
                if request_started and not replay_safe:
                    return self._unknown_tool_outcome(f"timed out after {timeout}s")
                logger.warning(
                    "MCP {} '{}' timed out after {}s", capability_kind, self._name, timeout
                )
                return ToolResult.error(f"(MCP {operation} timed out after {timeout}s)")
            except asyncio.CancelledError:
                # MCP SDK cancel scopes can leak cancellation without cancelling our task.
                if task_is_cancelling():
                    raise
                logger.warning("MCP {} '{}' was cancelled by server/SDK", capability_kind, self._name)
                return ToolResult.error(f"(MCP {operation} was cancelled)")
            except Exception as exc:
                if request_started and not replay_safe and (
                    _is_session_terminated(exc) or isinstance(exc, httpx.TransportError)
                ):
                    return self._unknown_tool_outcome(f"lost its response ({type(exc).__name__})")
                if await self._refresh_session_after_termination(
                    exc, refreshed_session, capability_kind
                ):
                    refreshed_session = True
                    continue
                if capability_kind == "prompt" and isinstance(exc, McpError):
                    logger.opt(exception=exc if tool_log_content_allowed() else False).error(
                        "MCP prompt '{}' failed: code={} message={}",
                        self._name,
                        exc.error.code,
                        exc.error.message if tool_log_content_allowed() else "[content hidden]",
                    )
                    return ToolResult.error(
                        f"(MCP prompt call failed: {exc.error.message} [code {exc.error.code}])"
                    )
                if _is_transient(exc):
                    if not retried:
                        logger.warning(
                            "MCP {} '{}' hit transient error ({}), retrying once...",
                            capability_kind,
                            self._name,
                            type(exc).__name__,
                        )
                        retried = True
                        await asyncio.sleep(1)
                        continue
                    logger.opt(exception=exc if tool_log_content_allowed() else False).error(
                        "MCP {} '{}' failed after retry: {}",
                        capability_kind,
                        self._name,
                        type(exc).__name__,
                    )
                    return ToolResult.error(f"(MCP {operation} failed after retry: {type(exc).__name__})")
                logger.opt(exception=exc if tool_log_content_allowed() else False).error(
                    "MCP {} '{}' failed: {}: {}",
                    capability_kind,
                    self._name,
                    type(exc).__name__,
                    exc if tool_log_content_allowed() else "[content hidden]",
                )
                return ToolResult.error(f"(MCP {operation} failed: {type(exc).__name__})")


def _mcp_image_tool_result(text_parts: list[str], artifacts: list[dict[str, Any]]) -> str:
    payload: dict[str, Any] = {
        "artifacts": artifacts,
        "next_step": (
            "These images were returned by an MCP tool and saved as local artifacts. "
            "Call the message tool with the artifact 'path' values in the media "
            "parameter to deliver the images to the user. Do not paste base64 or raw "
            "paths into your reply unless the user asks for debug details."
        ),
    }
    text = "\n".join(part for part in text_parts if part)
    if text:
        payload["text"] = text
    return json.dumps(payload, ensure_ascii=False)


class MCPToolWrapper(_MCPWrapperBase):
    """Wraps a single MCP server tool as a nanobot Tool."""

    _plugin_discoverable = False

    def __init__(
        self,
        session: ClientSession,
        server_name: str,
        tool_def: MCPToolDefinition,
        tool_timeout: int = 30,
    ):
        self._original_name = tool_def.name
        self._name = _sanitize_mcp_tool_name(f"mcp_{server_name}_{tool_def.name}")
        self._description = tool_def.description or tool_def.name
        raw_schema = tool_def.inputSchema or {"type": "object", "properties": {}}
        self._input_schema = raw_schema
        self._parameters = _normalize_schema_for_openai(raw_schema)
        self._tool_timeout = tool_timeout
        # Replay is opt-in through explicit server declarations, not inferred
        # from names or destructiveHint=False (additive writes can duplicate).
        # This trusts the server's contract; it is not client-side deduplication
        # and does not change tool permissions or concurrency classification.
        annotations = getattr(tool_def, "annotations", None)
        self._set_mcp_connection(
            session, server_name,
            replay_safe=annotations is not None and (
                annotations.readOnlyHint is True or annotations.idempotentHint is True
            ),
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        # Provider adaptations are not the server's validation contract.
        return Schema.validate_json_schema_value(params, self._input_schema)

    async def execute(self, **kwargs: Any) -> str:
        result = await self._request_with_recovery(
            lambda session: session.call_tool(self._original_name, arguments=kwargs),
            self._tool_timeout,
            "tool",
        )
        if isinstance(result, ToolResult):
            return result
        try:
            rendered = self._render_call_result(result.content, kwargs)
            if getattr(result, "isError", False):
                return ToolResult.error(rendered)
            return rendered
        except Exception as exc:
            logger.opt(exception=tool_log_content_allowed()).error(
                "MCP tool '{}' failed while rendering result: {}: {}",
                self._name,
                type(exc).__name__,
                exc if tool_log_content_allowed() else "[content hidden]",
            )
            return ToolResult.error(
                f"(MCP tool returned malformed content: {type(exc).__name__})"
            )

    def _render_call_result(
        self, content: Sequence[ContentBlock], arguments: Mapping[str, Any],
    ) -> str:
        """Turn MCP content blocks into a tool result string.

        Text is concatenated as before. Image blocks are decoded and saved as
        local artifacts (mirroring the built-in image generation tool) so the
        model can deliver them via the message tool instead of trying to forward
        base64 — which would be truncated and bloat the context window.
        """
        from mcp import types

        text_parts: list[str] = []
        artifacts: list[dict[str, Any]] = []
        for block in content:
            if isinstance(block, types.TextContent):
                text_parts.append(block.text)
                continue
            if isinstance(block, types.ImageContent):
                data_url = f"data:{block.mimeType or 'image/png'};base64,{block.data}"
            elif (
                isinstance(block, types.EmbeddedResource)
                and isinstance(resource := block.resource, types.BlobResourceContents)
                and resource.mimeType
                and resource.mimeType.startswith("image/")
            ):
                data_url = f"data:{resource.mimeType};base64,{resource.blob}"
            else:
                text_parts.append(str(block))
                continue
            stored = self._store_image_block(data_url, arguments)
            if stored is not None:
                artifacts.append(stored)
            else:
                text_parts.append("(MCP tool returned an image that could not be stored)")

        if artifacts:
            return _mcp_image_tool_result(text_parts, artifacts)
        return "\n".join(text_parts) or "(no output)"

    def _store_image_block(
        self, data_url: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        from nanobot.utils.artifacts import ArtifactError, store_generated_image_artifact

        try:
            return store_generated_image_artifact(
                data_url,
                prompt=str(arguments.get("prompt") or ""),
                model=str(arguments.get("model") or ""),
                save_dir="generated",
                provider=f"mcp:{self._server_name}",
            )
        except (ArtifactError, OSError) as exc:
            logger.warning(
                "MCP tool '{}' returned an image that could not be stored: {}",
                self._name,
                exc if tool_log_content_allowed() else type(exc).__name__,
            )
            return None


class MCPResourceWrapper(_MCPWrapperBase):
    """Wraps an MCP resource URI as a read-only nanobot Tool."""

    _plugin_discoverable = False

    def __init__(
        self,
        session: ClientSession,
        server_name: str,
        resource_def: Resource,
        resource_timeout: int = 30,
    ):
        self._set_mcp_connection(session, server_name, replay_safe=True)
        self._uri = resource_def.uri
        self._name = _sanitize_mcp_tool_name(f"mcp_{server_name}_resource_{resource_def.name}")
        desc = resource_def.description or resource_def.name
        self._description = f"[MCP Resource] {desc}\nURI: {self._uri}"
        self._parameters: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        self._resource_timeout = resource_timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        from mcp import types

        result = await self._request_with_recovery(
            lambda session: session.read_resource(self._uri),
            self._resource_timeout,
            "resource",
        )
        if isinstance(result, ToolResult):
            return result
        parts: list[str] = []
        for block in result.contents:
            if isinstance(block, types.TextResourceContents):
                parts.append(block.text)
            elif isinstance(cast(object, block), types.BlobResourceContents):
                parts.append(f"[Binary resource: {len(block.blob)} bytes]")
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"


class MCPPromptWrapper(_MCPWrapperBase):
    """Wraps an MCP prompt as a read-only nanobot Tool."""

    _plugin_discoverable = False

    def __init__(
        self,
        session: ClientSession,
        server_name: str,
        prompt_def: Prompt,
        prompt_timeout: int = 30,
    ):
        self._set_mcp_connection(session, server_name, replay_safe=True)
        self._prompt_name = prompt_def.name
        self._name = _sanitize_mcp_tool_name(f"mcp_{server_name}_prompt_{prompt_def.name}")
        desc = prompt_def.description or prompt_def.name
        self._description = (
            f"[MCP Prompt] {desc}\n"
            "Returns a filled prompt template that can be used as a workflow guide."
        )
        self._prompt_timeout = prompt_timeout

        properties: dict[str, Any] = {}
        required: list[str] = []
        for arg in prompt_def.arguments or []:
            prop: dict[str, Any] = {"type": "string"}
            if getattr(arg, "description", None):
                prop["description"] = arg.description
            properties[arg.name] = prop
            if arg.required:
                required.append(arg.name)
        self._parameters: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        from mcp import types

        result = await self._request_with_recovery(
            lambda session: session.get_prompt(self._prompt_name, arguments=kwargs),
            self._prompt_timeout,
            "prompt",
        )
        if isinstance(result, ToolResult):
            return result
        parts: list[str] = []
        for message in result.messages:
            content = message.content
            if isinstance(content, types.TextContent):
                parts.append(content.text)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, types.TextContent):
                        parts.append(block.text)
                    else:
                        parts.append(str(block))
            else:
                parts.append(str(content))
        return "\n".join(parts) or "(no output)"


async def connect_mcp_server(
    name: str,
    cfg: MCPServerConfig,
    *,
    oauth_handler: MCPOAuthHandlers | None = None,
    network: NetworkConfig | None = None,
    stdio_slots: asyncio.Semaphore | None = None,
) -> MCPServerConnection | None:
    """Discover a server's capabilities without publishing them."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    # Stack-exit failures are logged outside discovery; retain the exact
    # selected value there too, including credentials resolved from environment refs.
    proxy: str | None = None

    async def discover(server_stack: AsyncExitStack) -> tuple[Tool, ...] | None:
        nonlocal proxy
        try:
            transport_type = cfg.type
            if not transport_type:
                if cfg.command:
                    transport_type = "stdio"
                elif cfg.url:
                    transport_type = (
                        "sse" if cfg.url.rstrip("/").endswith("/sse") else "streamableHttp"
                    )
                else:
                    logger.warning("MCP server '{}': no command or url configured, skipping", name)
                    return None

            is_http = transport_type in {"sse", "streamableHttp"}
            if is_http:
                ok, error = validate_url_target(cfg.url)
                if not ok:
                    logger.warning(
                        "MCP server '{}': blocked unsafe URL {} ({})",
                        name,
                        _redact_url(cfg.url),
                        error,
                    )
                    return None

            if cfg.use_proxy and transport_type == "stdio":
                raise ValueError("The shared proxy is available for HTTP and SSE MCP connections")
            proxy = (network or NetworkConfig()).resolve_proxy(cfg.use_proxy)
            oauth_auth: httpx.Auth | None = None
            if cfg.auth == "oauth":
                if not is_http:
                    logger.warning(
                        "MCP server '{}': OAuth requires an SSE or Streamable HTTP transport",
                        name,
                    )
                    return None
                from nanobot.agent.tools.mcp_oauth import (
                    MCPAuthorizationRequiredError,
                    create_mcp_oauth_auth,
                )

                try:
                    oauth_auth = await create_mcp_oauth_auth(
                        name,
                        cfg.url,
                        oauth_handler,
                    )
                except MCPAuthorizationRequiredError:
                    logger.info("MCP server '{}': waiting for browser authorization", name)
                    return None

            if is_http and not await _probe_http_url(cfg.url, proxy=proxy):
                logger.warning("MCP server '{}': {} unreachable, skipping", name, _redact_url(cfg.url))
                return None

            if transport_type == "stdio":
                command, args, env = _normalize_windows_stdio_command(
                    cfg.command,
                    cfg.args,
                    cfg.env or None,
                )
                params = StdioServerParameters(
                    command=command,
                    args=args,
                    env=env,
                    cwd=cfg.cwd or None,
                )
                # Bound process creation, not how long the child takes to speak MCP.
                async with stdio_slots if stdio_slots is not None else nullcontext():
                    read, write = await server_stack.enter_async_context(stdio_client(params))
            elif transport_type == "sse":
                def httpx_client_factory(
                    headers: dict[str, str] | None = None,
                    timeout: httpx.Timeout | None = None,
                    auth: httpx.Auth | None = None,
                ) -> httpx.AsyncClient:
                    merged_headers = {
                        "Accept": "application/json, text/event-stream",
                        **(cfg.headers or {}),
                        **(headers or {}),
                    }
                    return _mcp_http_client(proxy, merged_headers, timeout, auth)

                sse_kwargs: dict[str, Any] = {"httpx_client_factory": httpx_client_factory}
                if oauth_auth is not None:
                    sse_kwargs["auth"] = oauth_auth
                read, write = await server_stack.enter_async_context(
                    sse_client(cfg.url, **sse_kwargs)
                )
            elif transport_type == "streamableHttp":
                # Read must outlast the tool call itself.
                timeout = httpx.Timeout(
                    _HTTP_TIMEOUT, connect=10.0, read=max(_HTTP_READ_TIMEOUT, cfg.tool_timeout),
                )
                http_client = await server_stack.enter_async_context(
                    _mcp_http_client(proxy, cfg.headers or None, timeout, oauth_auth)
                )
                read, write, _ = await server_stack.enter_async_context(
                    streamable_http_client(cfg.url, http_client=http_client)
                )
            else:
                logger.warning("MCP server '{}': unknown transport type '{}'", name, transport_type)
                return None

            # The SDK annotates the concrete memory stream, but consumes the AnyIO receive interface.
            filtered = cast("MemoryObjectReceiveStream[SessionMessage | Exception]", _MCPReceiveStream(read))
            session = await server_stack.enter_async_context(ClientSession(filtered, write))
            initialization = await session.initialize()

            # Finish discovery before registering tools so a failed page leaves no partial set.
            tool_defs: list[MCPToolDefinition] = []
            if initialization.capabilities.tools is not None:
                tool_defs = await _list_all(session.list_tools, lambda page: page.tools)

            enabled_tools = set(cfg.enabled_tools)
            allow_all_tools = "*" in enabled_tools
            tools: list[Tool] = []
            matched_enabled_tools: set[str] = set()
            available_raw_names = [tool_def.name for tool_def in tool_defs]
            available_wrapped_names = [_sanitize_mcp_tool_name(f"mcp_{name}_{tool_def.name}") for tool_def in tool_defs]
            for tool_def in tool_defs:
                wrapped_name = _sanitize_mcp_tool_name(f"mcp_{name}_{tool_def.name}")
                if (
                    not allow_all_tools
                    and tool_def.name not in enabled_tools
                    and wrapped_name not in enabled_tools
                ):
                    logger.debug(
                        "MCP: skipping tool '{}' from server '{}' (not in enabledTools)",
                        wrapped_name,
                        name,
                    )
                    continue
                tools.append(MCPToolWrapper(session, name, tool_def, tool_timeout=cfg.tool_timeout))
                matched_enabled_tools.update((tool_def.name, wrapped_name))

            if enabled_tools and not allow_all_tools:
                unmatched_enabled_tools = sorted(enabled_tools - matched_enabled_tools)
                if unmatched_enabled_tools:
                    logger.warning(
                        "MCP server '{}': enabledTools entries not found: {}. Available raw names: {}. "
                        "Available wrapped names: {}",
                        name,
                        ", ".join(unmatched_enabled_tools),
                        ", ".join(available_raw_names) or "(none)",
                        ", ".join(available_wrapped_names) or "(none)",
                    )

            # Only register resources and prompts when no tool restriction is
            # active.  enabledTools is a per-*tool* allowlist; resources and
            # prompts have no equivalent name filter, so they must be skipped
            # whenever the operator specified a tool subset.  An empty list
            # (deny-all) or a list of specific tool names both indicate that
            # the operator intended to restrict capabilities — registering
            # unrestricted resource/prompt wrappers would violate that intent.
            # The default ["*"] (allow-all) means no restriction was intended.
            if allow_all_tools:
                try:
                    for resource in await _list_all(session.list_resources, lambda page: page.resources):
                        tools.append(MCPResourceWrapper(
                            session, name, resource, resource_timeout=cfg.tool_timeout
                        ))
                except Exception as e:
                    logger.debug(
                        "MCP server '{}': resources not supported or failed: {}", name, type(e).__name__
                    )

                try:
                    for prompt in await _list_all(session.list_prompts, lambda page: page.prompts):
                        tools.append(MCPPromptWrapper(
                            session, name, prompt, prompt_timeout=cfg.tool_timeout
                        ))
                except Exception as e:
                    logger.debug(
                        "MCP server '{}': prompts not supported or failed: {}", name, type(e).__name__
                    )
            else:
                logger.info(
                    "MCP server '{}': skipping resource/prompt registration "
                    "(enabledTools does not include '*' — only tools allowed)",
                    name,
                )

            logger.info(
                "MCP server '{}': connected, {} capabilities discovered", name, len(tools)
            )
            return tuple(tools)

        except Exception as e:
            hint = ""
            text = str(e).lower()
            if any(
                marker in text
                for marker in (
                    "parse error",
                    "invalid json",
                    "unexpected token",
                    "jsonrpc",
                    "content-length",
                )
            ):
                hint = (
                    " Hint: this looks like stdio protocol pollution. Make sure the MCP server writes "
                    "only JSON-RPC to stdout and sends logs/debug output to stderr instead."
                )
            _log_mcp_connection_failure(name, e, hint, proxy=proxy)
            return None

    ready: asyncio.Future[tuple[Tool, ...] | None] = asyncio.get_running_loop().create_future()
    close_requested = asyncio.Event()

    async def own_connection() -> None:
        try:
            async with AsyncExitStack() as stack:
                tools = await discover(stack)
                if not ready.done():
                    ready.set_result(tools)
                if tools is not None:
                    await close_requested.wait()
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            raise

    owner = asyncio.create_task(own_connection(), name=f"mcp:{name}")

    async def close() -> None:
        # The SDK contexts must exit in the same task that opened them.
        close_requested.set()
        try:
            await asyncio.shield(owner)
        except asyncio.CancelledError:
            if not owner.cancelled():
                raise

    try:
        # Transport limits still apply; callers decide how long to wait for discovery.
        tools = await ready
        if tools is None:
            await asyncio.shield(owner)
            return None
        return MCPServerConnection(close, tools)
    except BaseException as exc:
        owner.cancel()
        with suppress(BaseException):
            await asyncio.shield(owner)
        if isinstance(exc, asyncio.CancelledError):
            if task_is_cancelling():
                raise
            logger.warning("MCP server '{}': connection cancelled by server/SDK", name)
        elif isinstance(exc, Exception):
            _log_mcp_connection_failure(name, exc, proxy=proxy)
        else:
            raise
        return None


def session_extra(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return persisted session kwargs for MCP preset attachments."""
    mcp_presets = metadata.get("mcp_presets") if isinstance(metadata, Mapping) else None
    return {"mcp_presets": mcp_presets} if isinstance(mcp_presets, list) and mcp_presets else {}


def _configured_servers(config: Config) -> dict[str, MCPServerConfig]:
    from nanobot.agent.plugins import agent_plugin_mcp_servers

    return agent_plugin_mcp_servers(
        config.workspace_path,
        config.tools.mcp_servers,
    )


def _load_current_servers() -> tuple[dict[str, MCPServerConfig], NetworkConfig]:
    from nanobot.config.loader import load_config, resolve_config_env_vars

    config = resolve_config_env_vars(load_config())
    return _configured_servers(config), config.network


def _pending_mcp_authorization(servers: Mapping[str, MCPServerConfig]) -> set[str]:
    oauth = {name: cfg for name, cfg in servers.items() if cfg.auth == "oauth"}
    if not oauth:
        return set()
    from nanobot.agent.tools.mcp_oauth import mcp_oauth_has_credentials

    return {name for name, cfg in oauth.items() if not mcp_oauth_has_credentials(name, cfg.url)}


class MCPProvider:
    """Own configured MCP connections and their dynamic tool registrations."""

    def __init__(
        self,
        servers: Mapping[str, MCPServerConfig],
        registry: ToolRegistry,
        *,
        server_loader: MCPServerLoader | None = None,
        network: NetworkConfig | None = None,
    ) -> None:
        self._servers = dict(servers)
        self._network = (network or NetworkConfig()).model_copy(deep=True)
        self._registry = registry
        self._server_loader = server_loader or _load_current_servers
        self._connections: dict[str, MCPServerConnection] = {}
        self._tool_owners: dict[str, str | None] = {}
        self._connecting: dict[str, asyncio.Task[None]] = {}
        self._failed: set[str] = set()
        self._stdio_slots = asyncio.Semaphore(_MAX_CONCURRENT_STDIO_LAUNCHES)
        self._lock = asyncio.Lock()
        self._attempt_finished = asyncio.Event()
        self._closing = False

    @classmethod
    def from_config(
        cls,
        config: Config,
        registry: ToolRegistry,
        *,
        server_loader: MCPServerLoader | None = None,
    ) -> MCPProvider:
        return cls(
            _configured_servers(config),
            registry,
            server_loader=server_loader,
            network=config.network,
        )

    @property
    def configured_server_names(self) -> set[str]:
        return set(self._servers)

    @property
    def connected_server_names(self) -> set[str]:
        return set(self._connections)

    def runtime_status(self) -> dict[str, MCPRuntimeStatus]:
        """Return the latest connection-attempt result for configured servers."""
        return {
            **dict.fromkeys(self._failed, "failed"),
            **dict.fromkeys(self._connecting, "connecting"),
            **dict.fromkeys(self._connections, "connected"),
        }

    async def maintain(self, initial: asyncio.Event) -> None:
        """Run the gateway's connection attempts independently of its turns."""
        first: set[asyncio.Task[None]] = set()
        async with self._lock:
            if not self._closing:
                first.update(self._start_missing().values())
        try:
            while not self._closing:
                self._attempt_finished.clear()
                if not initial.is_set():
                    first = {task for task in first if not task.done()}
                    if not first:
                        initial.set()
                if not self._failed:
                    await self._attempt_finished.wait()
                    continue
                await asyncio.sleep(_RETRY_DELAY_SECONDS)
                async with self._lock:
                    if not self._closing:
                        self._start_missing()
        finally:
            initial.set()

    def _start_missing(self) -> dict[str, asyncio.Task[None]]:
        missing = {name: cfg for name, cfg in self._servers.items() if name not in self._connections}
        pending_auth = _pending_mcp_authorization(missing)
        self._failed.difference_update(pending_auth)
        return {name: self._start_attempt(name, cfg) for name, cfg in missing.items() if name not in pending_auth}

    def _start_attempt(self, name: str, config: MCPServerConfig) -> asyncio.Task[None]:
        attempt = self._connecting.get(name)
        if attempt is None:
            self._failed.discard(name)
            attempt = asyncio.create_task(self._connect_one(name, config, self._network), name=f"mcp-start:{name}")
            self._connecting[name] = attempt
        return attempt

    async def _connect_one(self, name: str, config: MCPServerConfig, network: NetworkConfig) -> None:
        task = asyncio.current_task()
        try:
            try:
                connection = await connect_mcp_server(name, config, network=network, stdio_slots=self._stdio_slots)
            except Exception as exc:
                logger.warning("MCP server '{}' connection failed: {}", name, type(exc).__name__)
                connection = None

            if self._closing or self._connecting.get(name) is not task:
                if connection is not None:
                    await _close_mcp_connection(name, connection)
            elif connection is None:
                self._failed.add(name)
            else:
                self._connections[name] = connection
                self._publish_tools(name, connection)
        finally:
            if self._connecting.get(name) is task:
                del self._connecting[name]
            self._attempt_finished.set()

    async def _cancel_attempts(self, names: Iterable[str]) -> None:
        tasks = [self._connecting.pop(name) for name in names if name in self._connecting]
        for task in tasks:
            task.cancel()
        if tasks:
            await shield_and_drain(asyncio.gather(*tasks, return_exceptions=True))
            self._attempt_finished.set()

    def _publish_tools(self, server_name: str, connection: MCPServerConnection) -> None:
        for tool in connection.tools:
            name = tool.name
            owner = self._tool_owners.setdefault(name, server_name)
            if owner is None:
                continue
            current = self._registry.get(name)
            if current is not None or owner != server_name:
                # Existing model requests may hold this name. Never reassign an
                # ambiguous name to another server during this gateway lifetime.
                self._tool_owners[name] = None
                previous = self._connections.get(owner)
                if previous is not None and any(current is registered for registered in previous.tools):
                    self._registry.unregister(name)
                logger.warning(
                    "MCP tool '{}' conflicts with an existing name. "
                    "Rename the conflicting MCP server or tool, then reload MCP settings.",
                    name,
                )
                continue
            if isinstance(tool, _MCPWrapperBase):
                tool.set_reconnect_handler(self._refresh_terminated_server)
            self._registry.register(tool)

    async def connect(self) -> None:
        """Wait for configured servers for direct CLI/SDK callers."""
        async with self._lock:
            if self._closing:
                return
            existing = set(self._connecting)
            attempts = self._start_missing()
        if not attempts:
            return
        try:
            await asyncio.wait(attempts.values())
        except asyncio.CancelledError:
            async with self._lock:
                owned = {
                    name for name in attempts.keys() - existing
                    if self._connecting.get(name) is attempts[name]
                }
                await self._cancel_attempts(owned)
                if not self._closing:
                    self._failed.update(owned)
            raise

    async def reload(self) -> dict[str, Any]:
        """Reconcile live MCP connections with the current configuration."""
        async with self._lock:
            if self._closing:
                return self._closing_result()
            try:
                loaded_servers, next_network = self._server_loader()
                next_servers = dict(loaded_servers)
            except Exception as exc:
                logger.warning("MCP hot reload could not read config: {}", exc)
                return {
                    "ok": False,
                    "message": "Could not reload MCP config. Restart nanobot to pick up changes.",
                    "requires_restart": True,
                    "error": str(exc),
                }

            current_servers = dict(self._servers)
            current_names = set(current_servers)
            next_names = set(next_servers)
            authorization_pending = _pending_mcp_authorization(next_servers)
            removed = sorted(current_names - next_names)
            added = sorted(next_names - current_names)
            changed = sorted(
                name
                for name in current_names & next_names
                if _server_signature(current_servers[name])
                != _server_signature(next_servers[name])
                or (next_servers[name].use_proxy and self._network.proxy != next_network.proxy)
            )

            await self._cancel_attempts(set(removed) | set(changed) | authorization_pending)
            tools_removed = 0
            for name in [*removed, *changed]:
                tools_removed += await self._close_server(name)

            self._failed.difference_update(removed, authorization_pending)
            self._servers = next_servers
            self._network = next_network.model_copy(deep=True)
            to_connect_names = next_names - self._connections.keys() - authorization_pending
            retry_missing = sorted(to_connect_names.difference(added, changed))
            new_attempts = [
                self._start_attempt(name, next_servers[name])
                for name in sorted(to_connect_names - self._connecting.keys())
                if not self._closing
            ]

        if new_attempts:
            # Bound the settings request, not the server's discovery lifetime.
            await asyncio.wait(new_attempts, timeout=_RELOAD_WAIT_SECONDS)

        async with self._lock:
            if self._closing:
                return self._closing_result()
            if self._servers != next_servers or self._network != next_network:
                return {
                    "ok": False,
                    "message": "MCP configuration changed again. Check the current connection status.",
                    "requires_restart": False,
                }

            failed = sorted(to_connect_names & self._failed)
            connecting = sorted(to_connect_names & self._connecting.keys())
            unchanged = not removed and not added and not changed and not retry_missing
            ok = not failed and not connecting
            if failed:
                message = (
                    "MCP config reloaded, but some servers did not connect: "
                    + ", ".join(failed)
                )
            elif connecting:
                message = "MCP config reloaded; still connecting: " + ", ".join(connecting)
            elif unchanged:
                message = "MCP config is already live."
            elif retry_missing and not added and not changed and not removed:
                message = "MCP connections refreshed without restarting nanobot."
            else:
                message = "MCP config reloaded without restarting nanobot."

            logger.info(
                "MCP hot reload: added={} changed={} removed={} retried={} "
                "connected={} failed={} tools_removed={}",
                added,
                changed,
                removed,
                retry_missing,
                sorted(to_connect_names & self._connections.keys()),
                failed,
                tools_removed,
            )
            return {
                "ok": ok,
                "message": message,
                "added": added,
                "changed": changed,
                "removed": removed,
                "retried": retry_missing,
                "connected": sorted(self._connections),
                "configured": sorted(self._servers),
                "failed": failed,
                "connecting": connecting,
                "tools_removed": tools_removed,
                "requires_restart": False,
            }

    @staticmethod
    def _closing_result() -> dict[str, Any]:
        return {
            "ok": False,
            "message": "MCP connections are shutting down.",
            "requires_restart": True,
        }

    async def _refresh_terminated_server(
        self,
        server_name: str,
        tool_name: str,
        stale_tool: Tool,
    ) -> Tool | None:
        async with self._lock:
            if self._closing or self._tool_owners.get(tool_name) != server_name:
                return None
            cfg = self._servers.get(server_name)
            if cfg is None:
                logger.warning(
                    "MCP server '{}' session terminated but is no longer configured",
                    server_name,
                )
                return None

            current_tool = self._registered_tool(server_name, tool_name)
            if current_tool is not None and current_tool is not stale_tool:
                return current_tool

            attempt = self._connecting.get(server_name)
            if attempt is None:
                logger.warning("MCP server '{}' session terminated; refreshing connection", server_name)
                await self._close_server(server_name)
                if self._closing:
                    return None
                attempt = self._start_attempt(server_name, cfg)

        # Only this tool call is bounded by toolTimeout. Do not cancel a shared reconnect.
        await asyncio.wait((attempt,))
        return self._registered_tool(server_name, tool_name)

    def _registered_tool(self, server_name: str, tool_name: str) -> Tool | None:
        current = self._registry.get(tool_name)
        connection = self._connections.get(server_name)
        if connection is not None and any(current is tool for tool in connection.tools):
            return current
        return None

    def _remove_tools(self, connection: MCPServerConnection) -> int:
        removed = 0
        for tool in connection.tools:
            if self._registry.get(tool.name) is tool:
                self._registry.unregister(tool.name)
                removed += 1
        return removed

    async def _close_server(self, server_name: str) -> int:
        connection = self._connections.pop(server_name, None)
        if connection is None:
            return 0
        removed = self._remove_tools(connection)
        await _close_mcp_connection(server_name, connection)
        return removed

    async def aclose(self) -> None:
        """Close every connection while excluding reconnect and hot reload."""
        self._closing = True
        async with self._lock:
            connections = dict(self._connections)
            self._connections.clear()
            self._failed.clear()
            for connection in connections.values():
                self._remove_tools(connection)
            try:
                await self._cancel_attempts(tuple(self._connecting))
            finally:
                self._attempt_finished.set()
                await _close_mcp_connections(connections)


def _server_signature(cfg: Any) -> Any:
    if hasattr(cfg, "model_dump"):
        return cfg.model_dump(mode="json")
    return cfg
