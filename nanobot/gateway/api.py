"""HTTP/WebSocket API server for desktop and web clients.

Provides:
- WebSocket endpoint at /api/chat for real-time streaming chat
- REST endpoints for sessions, status, and config
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web
from loguru import logger
from nanobot.config.loader import get_config_path, save_config
from nanobot.config.schema import ModelProfile
from nanobot.providers.registry import PROVIDERS
from nanobot.runtime.modeling import (
    find_vision_model_profile,
    make_provider,
    model_supports_vision,
    resolve_active_model_runtime,
)

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.config.schema import Config
    from nanobot.session.manager import SessionManager


DESKTOP_SUPPORTED_PROVIDER_NAMES = {
    "custom",
    "openrouter",
    "anthropic",
    "openai",
    "openai_codex",
    "github_copilot",
    "deepseek",
    "gemini",
    "gemini_oauth",
    "zhipu",
    "minimax",
    "moonshot",
    "ollama",
}


class GatewayAPI:
    """HTTP/WebSocket API server that runs alongside the gateway."""

    def __init__(
        self,
        agent: AgentLoop,
        config: Config,
        session_manager: SessionManager,
    ):
        self.agent = agent
        self.config = config
        self.session_manager = session_manager
        self._runner: web.AppRunner | None = None

    def _build_app(self) -> web.Application:
        app = web.Application()
        # CORS middleware
        app.middlewares.append(self._cors_middleware)
        # Routes
        app.router.add_get("/api/chat", self._ws_chat)
        app.router.add_get("/api/sessions", self._list_sessions)
        app.router.add_get("/api/sessions/{key}", self._get_session)
        app.router.add_delete("/api/sessions/{key}", self._delete_session)
        app.router.add_put("/api/sessions/{key}/model", self._set_session_model)
        app.router.add_get("/api/status", self._get_status)
        app.router.add_get("/api/config", self._get_config)
        app.router.add_get("/api/models", self._list_models)
        app.router.add_post("/api/models", self._create_model)
        app.router.add_post("/api/models/test", self._test_model)
        app.router.add_get("/api/oauth/{provider}/status", self._get_oauth_status)
        app.router.add_post("/api/oauth/{provider}/import", self._import_oauth_config)
        app.router.add_delete("/api/oauth/{provider}", self._revoke_oauth)
        app.router.add_put("/api/models/{model_id}", self._update_model)
        app.router.add_delete("/api/models/{model_id}", self._delete_model)
        app.router.add_post("/api/models/{model_id}/select", self._select_model)
        app.router.add_get("/api/providers", self._list_providers)
        app.router.add_put("/api/providers/{provider_id}", self._update_provider)
        app.router.add_post("/api/providers/{provider_id}/test", self._test_provider)
        app.router.add_get("/api/cron", self._list_cron_jobs)
        app.router.add_post("/api/cron", self._create_cron_job)
        app.router.add_put("/api/cron/{job_id}", self._update_cron_job)
        app.router.add_delete("/api/cron/{job_id}", self._delete_cron_job)
        app.router.add_post("/api/cron/{job_id}/run", self._run_cron_job)
        app.router.add_post("/api/cron/{job_id}/enable", self._enable_cron_job)
        # OPTIONS for CORS preflight
        app.router.add_route("OPTIONS", "/{path:.*}", self._handle_options)
        return app

    @web.middleware
    async def _cors_middleware(self, request: web.Request, handler) -> web.StreamResponse:
        if request.method == "OPTIONS":
            return await self._handle_options(request)
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response

    async def _handle_options(self, request: web.Request) -> web.Response:
        return web.Response(
            status=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            },
        )

    # ------------------------------------------------------------------ #
    # WebSocket chat
    # ------------------------------------------------------------------ #

    async def _ws_chat(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket endpoint for real-time streaming chat.

        Client sends:
            { "type": "message", "content": "...", "session_key": "..." }

        Server sends:
            { "type": "progress", "content": "..." }       — streaming progress
            { "type": "tool_hint", "content": "..." }       — tool call hints
            { "type": "reply", "content": "...", "session_key": "..." }  — final reply
            { "type": "error", "content": "..." }           — errors
        """
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        logger.info("Desktop WebSocket client connected")

        try:
            async for raw_msg in ws:
                if raw_msg.type in (web.WSMsgType.TEXT,):
                    try:
                        data = json.loads(raw_msg.data)
                    except json.JSONDecodeError:
                        await ws.send_json({"type": "error", "content": "Invalid JSON"})
                        continue

                    msg_type = data.get("type", "")
                    if msg_type == "message":
                        await self._handle_chat_message(ws, data)
                    elif msg_type == "ping":
                        await ws.send_json({"type": "pong"})
                    else:
                        await ws.send_json({"type": "error", "content": f"Unknown type: {msg_type}"})

                elif raw_msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("WebSocket error: {}", e)
        finally:
            logger.info("Desktop WebSocket client disconnected")

        return ws

    async def _handle_chat_message(self, ws: web.WebSocketResponse, data: dict) -> None:
        """Process a chat message and stream the response via WebSocket."""
        content = data.get("content", "").strip()
        media = [
            str(path)
            for path in (data.get("media") or data.get("images") or [])
            if isinstance(path, str) and path.strip()
        ]
        if not content and not media:
            await ws.send_json({"type": "error", "content": "Empty message"})
            return

        session_key = data.get("session_key", "desktop:direct")
        channel = "desktop"
        chat_id = session_key.split(":", 1)[1] if ":" in session_key else "direct"

        async def on_progress(text: str, *, tool_hint: bool = False) -> None:
            """Stream progress updates to the client."""
            if ws.closed:
                return
            msg_type = "tool_hint" if tool_hint else "progress"
            try:
                await ws.send_json({
                    "type": msg_type,
                    "content": text,
                    "session_key": session_key,
                })
            except Exception:
                pass  # Client may have disconnected

        try:
            override_provider = None
            override_model = None
            override_context_window_tokens = None
            session = self.session_manager.get_or_create(session_key)
            requested_model_id = str(data.get("model_id") or session.metadata.get("model_id") or "").strip()
            model_id = requested_model_id
            has_image_media = any(Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif"} for path in media)
            if model_id:
                temp_config = self.config.model_copy(deep=True)
                selected = next((item for item in temp_config.get_model_profiles() if item.id == model_id and item.enabled), None)
                if selected is None:
                    await ws.send_json({"type": "error", "content": "Selected model is unavailable"})
                    return
                if has_image_media and not model_supports_vision(selected.model):
                    fallback = find_vision_model_profile(temp_config)
                    if fallback is None:
                        await ws.send_json({
                            "type": "error",
                            "content": "当前模型不支持图片识别，请先新增一个视觉模型，例如 Gemini、GPT-4o、Claude 3/4 或 GLM-4V。",
                            "session_key": session_key,
                        })
                        return
                    selected = fallback
                    model_id = selected.id
                elif requested_model_id:
                    session.metadata["model_id"] = selected.id
                    self.session_manager.save(session)
                temp_config.agents.defaults.model_id = selected.id
                override_provider, runtime = make_provider(temp_config)
                override_model = runtime.profile.model
                override_context_window_tokens = runtime.context_window_tokens
            elif has_image_media:
                runtime = resolve_active_model_runtime(self.config)
                if not model_supports_vision(runtime.profile.model):
                    fallback = find_vision_model_profile(self.config)
                    if fallback is None:
                        await ws.send_json({
                            "type": "error",
                            "content": "当前默认模型不支持图片识别，请先新增一个视觉模型，例如 Gemini、GPT-4o、Claude 3/4 或 GLM-4V。",
                            "session_key": session_key,
                        })
                        return
                    temp_config = self.config.model_copy(deep=True)
                    temp_config.agents.defaults.model_id = fallback.id
                    override_provider, runtime = make_provider(temp_config)
                    override_model = runtime.profile.model
                    override_context_window_tokens = runtime.context_window_tokens
                    model_id = fallback.id

            response = await self.agent.process_direct(
                content=content,
                session_key=session_key,
                channel=channel,
                chat_id=chat_id,
                media=media,
                metadata={
                    "model_id": model_id or None,
                    "provider_name": runtime.provider_name if model_id else None,
                    "effective_model": runtime.profile.model if model_id else None,
                } if model_id else {},
                on_progress=on_progress,
                override_provider=override_provider,
                override_model=override_model,
                override_context_window_tokens=override_context_window_tokens,
            )

            images: list[str] = []
            attachments: list[str] = []
            session = self.session_manager.get_or_create(session_key)
            for msg in reversed(session.messages):
                if msg.get("role") != "assistant":
                    continue
                parsed = self._serialize_session_content(msg.get("content"))
                images = parsed["images"]
                attachments = parsed["attachments"]
                break

            if not ws.closed:
                await ws.send_json({
                    "type": "reply",
                    "content": response or "",
                    "session_key": session_key,
                    "images": images,
                    "attachments": attachments,
                })
        except asyncio.CancelledError:
            if not ws.closed:
                await ws.send_json({
                    "type": "error",
                    "content": "Request cancelled",
                    "session_key": session_key,
                })
        except Exception as e:
            logger.error("Error processing desktop chat message: {}", e)
            if not ws.closed:
                await ws.send_json({
                    "type": "error",
                    "content": str(e),
                    "session_key": session_key,
                })

    # ------------------------------------------------------------------ #
    # REST: Sessions
    # ------------------------------------------------------------------ #

    async def _list_sessions(self, request: web.Request) -> web.Response:
        """List all conversation sessions."""
        sessions = self.session_manager.list_sessions()
        return web.json_response({"sessions": sessions})

    async def _get_session(self, request: web.Request) -> web.Response:
        """Get messages for a specific session."""
        key = request.match_info["key"].replace("__", ":")
        session = self.session_manager.get_or_create(key)
        messages = []
        for msg in session.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role not in ("user", "assistant"):
                continue

            parsed = self._serialize_session_content(content)
            if parsed["content"] or parsed["images"]:
                messages.append({
                    "role": role,
                    "content": parsed["content"],
                    "images": parsed["images"],
                    "attachments": parsed["attachments"],
                    "timestamp": msg.get("timestamp", ""),
                })
        return web.json_response({
            "key": key,
            "messages": messages,
            "metadata": session.metadata,
            "modelId": session.metadata.get("model_id"),
        })

    @staticmethod
    def _serialize_session_content(content: Any) -> dict[str, Any]:
        """Normalize stored session content for the desktop frontend."""
        image_paths: list[str] = []
        attachment_paths: list[str] = []
        text_parts: list[str] = []

        def consume_text(text: str) -> None:
            if not text:
                return
            cleaned = text
            for match in re.finditer(r"\[image:\s*([^\]]+)\]", text):
                image_paths.append(match.group(1).strip())
            for match in re.finditer(r"\[(?:file|attachment):\s*([^\]]+)\]", text):
                attachment_paths.append(match.group(1).strip())
            cleaned = re.sub(r"\[image:\s*[^\]]+\]", "", cleaned).strip()
            cleaned = re.sub(r"\[(?:file|attachment):\s*[^\]]+\]", "", cleaned).strip()
            if cleaned:
                text_parts.append(cleaned)

        if isinstance(content, str):
            consume_text(content)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    consume_text(block["text"])

        return {
            "content": "\n\n".join(text_parts).strip(),
            "images": image_paths,
            "attachments": attachment_paths,
        }

    async def _delete_session(self, request: web.Request) -> web.Response:
        """Delete a session entirely."""
        key = request.match_info["key"].replace("__", ":")
        removed = self.session_manager.delete(key)
        return web.json_response({"ok": True, "key": key, "deleted": removed})

    async def _set_session_model(self, request: web.Request) -> web.Response:
        """Bind a model to a specific session."""
        key = request.match_info["key"].replace("__", ":")
        session = self.session_manager.get_or_create(key)
        try:
            body = await request.json()
            model_id = str(body.get("modelId") or "").strip()
            if not model_id:
                session.metadata.pop("model_id", None)
                self.session_manager.save(session)
                return web.json_response({"ok": True, "key": key, "modelId": None})

            selected = next((item for item in self.config.get_model_profiles() if item.id == model_id and item.enabled), None)
            if selected is None:
                return web.json_response({"error": "Selected model is unavailable"}, status=400)

            session.metadata["model_id"] = selected.id
            self.session_manager.save(session)
            return web.json_response({"ok": True, "key": key, "modelId": selected.id})
        except Exception as e:
            logger.error("Failed to set session model for {}: {}", key, e)
            return web.json_response({"error": str(e)}, status=500)

    # ------------------------------------------------------------------ #
    # REST: Status / Config
    # ------------------------------------------------------------------ #

    async def _get_status(self, request: web.Request) -> web.Response:
        """Get nanobot status."""
        from nanobot import __version__

        return web.json_response({
            "version": __version__,
            "model": self.agent.model,
            "running": self.agent._running,
        })

    async def _get_config(self, request: web.Request) -> web.Response:
        """Get safe config info (no API keys)."""
        runtime = resolve_active_model_runtime(self.config)
        defaults = self.config.agents.defaults
        return web.json_response({
            "model": runtime.profile.model,
            "provider": runtime.provider_name or runtime.profile.provider,
            "workspace": str(self.config.workspace_path),
            "maxTokens": runtime.max_tokens,
            "contextWindowTokens": runtime.context_window_tokens,
            "temperature": runtime.temperature,
            "models": [self._serialize_model(item) for item in self.config.get_model_profiles()],
            "defaultModelId": defaults.model_id or runtime.profile.id,
            "activeModel": self._serialize_model(runtime.profile),
        })

    @staticmethod
    def _serialize_model(profile: ModelProfile) -> dict[str, Any]:
        return {
            "id": profile.id,
            "name": profile.name,
            "provider": profile.provider,
            "model": profile.model,
            "apiKey": profile.api_key,
            "apiBase": profile.api_base,
            "extraHeaders": profile.extra_headers or {},
            "maxTokens": profile.max_tokens,
            "contextWindowTokens": profile.context_window_tokens,
            "temperature": profile.temperature,
            "reasoningEffort": profile.reasoning_effort,
            "enabled": profile.enabled,
        }

    @staticmethod
    def _provider_options() -> list[dict[str, Any]]:
        return [
            {
                "id": spec.name,
                "label": "OpenAI (OAuth)" if spec.name == "openai_codex" else spec.label,
                "isOAuth": bool(spec.is_oauth),
            }
            for spec in PROVIDERS
            if spec.name in DESKTOP_SUPPORTED_PROVIDER_NAMES
        ]

    def _serialize_provider(self, provider_id: str) -> dict[str, Any]:
        cfg = getattr(self.config.providers, provider_id)
        spec = next((item for item in PROVIDERS if item.name == provider_id), None)
        return {
            "id": provider_id,
            "label": spec.label if spec else provider_id,
            "apiKey": cfg.api_key,
            "apiBase": cfg.api_base,
            "extraHeaders": cfg.extra_headers or {},
            "isOAuth": bool(spec.is_oauth) if spec else False,
            "isLocal": bool(spec.is_local) if spec else False,
            "isGateway": bool(spec.is_gateway) if spec else False,
        }

    @staticmethod
    def _parse_model_payload(data: dict[str, Any], existing_id: str | None = None) -> ModelProfile:
        provider = str(data.get("provider") or "auto").strip().replace("-", "_")
        valid_provider_names = {spec.name for spec in PROVIDERS} | {"auto"}
        if provider not in valid_provider_names:
            raise ValueError("provider is invalid")

        model = str(data.get("model") or "").strip()
        name = str(data.get("name") or "").strip()
        if not model:
            raise ValueError("model is required")
        if not name:
            raise ValueError("name is required")

        extra_headers = data.get("extraHeaders")
        if extra_headers is not None and not isinstance(extra_headers, dict):
            raise ValueError("extraHeaders must be an object")

        def _optional_int(key: str) -> int | None:
            value = data.get(key)
            if value in (None, ""):
                return None
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{key} must be a positive integer")
            return value

        def _optional_float(key: str) -> float | None:
            value = data.get(key)
            if value in (None, ""):
                return None
            if not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number")
            return float(value)

        reasoning_effort = data.get("reasoningEffort")
        if reasoning_effort in ("", None):
            reasoning_effort = None
        elif reasoning_effort not in {"low", "medium", "high"}:
            raise ValueError("reasoningEffort must be one of: low, medium, high")

        return ModelProfile(
            id=existing_id or str(uuid.uuid4())[:8],
            name=name,
            provider=provider,
            model=model,
            api_key=(str(data.get("apiKey")).strip() if data.get("apiKey") not in (None, "") else None),
            api_base=(str(data.get("apiBase")).strip() if data.get("apiBase") not in (None, "") else None),
            extra_headers={str(k): str(v) for k, v in (extra_headers or {}).items()} or None,
            max_tokens=_optional_int("maxTokens"),
            context_window_tokens=_optional_int("contextWindowTokens"),
            temperature=_optional_float("temperature"),
            reasoning_effort=reasoning_effort,
            enabled=bool(data.get("enabled", True)),
        )

    def _apply_runtime_model(self) -> None:
        provider, runtime = make_provider(self.config)
        self.agent.apply_runtime_model(
            provider=provider,
            model=runtime.profile.model,
            context_window_tokens=runtime.context_window_tokens,
        )

    def _persist_config(self) -> None:
        self._apply_runtime_model()
        save_config(self.config, get_config_path())

    async def _list_models(self, request: web.Request) -> web.Response:
        active = self.config.get_active_model_profile()
        return web.json_response({
            "items": [self._serialize_model(item) for item in self.config.get_model_profiles()],
            "defaultModelId": self.config.agents.defaults.model_id or active.id,
            "providers": self._provider_options(),
        })

    async def _get_oauth_status(self, request: web.Request) -> web.Response:
        provider = request.match_info["provider"].replace("-", "_")
        if provider == "openai_codex":
            try:
                from oauth_cli_kit import get_token

                token = await asyncio.to_thread(get_token)
                return web.json_response({
                    "provider": provider,
                    "authorized": True,
                    "accountId": getattr(token, "account_id", None),
                })
            except Exception as e:
                return web.json_response({
                    "provider": provider,
                    "authorized": False,
                    "error": str(e),
                })
        if provider == "gemini_oauth":
            from nanobot.providers.gemini_oauth_provider import get_adc_status

            status = await asyncio.to_thread(get_adc_status)
            return web.json_response({
                "provider": provider,
                **status,
            })
        return web.json_response({"error": "Unsupported OAuth provider"}, status=404)

    async def _revoke_oauth(self, request: web.Request) -> web.Response:
        provider = request.match_info["provider"].replace("-", "_")
        try:
            removed: list[str] = []
            if provider == "openai_codex":
                from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
                from oauth_cli_kit.storage import FileTokenStorage

                storage = FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename)
                token_path = storage.get_token_path()
                if token_path.exists():
                    token_path.unlink()
                    removed.append(str(token_path))
                lock_path = token_path.with_suffix(".lock")
                if lock_path.exists():
                    lock_path.unlink()
                    removed.append(str(lock_path))

                codex_cli_path = Path.home() / ".codex" / "auth.json"
                if codex_cli_path.exists():
                    codex_cli_path.unlink()
                    removed.append(str(codex_cli_path))
            elif provider == "gemini_oauth":
                from nanobot.providers.gemini_oauth_provider import revoke_adc

                removed = await asyncio.to_thread(revoke_adc)
            else:
                return web.json_response({"error": "Unsupported OAuth provider"}, status=404)

            return web.json_response({
                "ok": True,
                "provider": provider,
                "removed": removed,
            })
        except Exception as e:
            logger.error("Failed to revoke OAuth for {}: {}", provider, e)
            return web.json_response({"error": str(e)}, status=500)

    async def _import_oauth_config(self, request: web.Request) -> web.Response:
        provider = request.match_info["provider"].replace("-", "_")
        try:
            body = await request.json()
            source_path = str(body.get("path") or "").strip()
            if not source_path:
                return web.json_response({"error": "Missing path"}, status=400)
            if provider == "gemini_oauth":
                from nanobot.providers.gemini_oauth_provider import import_adc_config, get_adc_status

                saved_path = await asyncio.to_thread(import_adc_config, source_path)
                status = await asyncio.to_thread(get_adc_status)
                return web.json_response({
                    "ok": True,
                    "provider": provider,
                    "path": saved_path,
                    **status,
                })
            return web.json_response({"error": "Unsupported OAuth provider"}, status=404)
        except Exception as e:
            logger.error("Failed to import OAuth config for {}: {}", provider, e)
            return web.json_response({"error": str(e)}, status=500)

    async def _create_model(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            profile = self._parse_model_payload(body)
            profiles = self.config.get_model_profiles()
            profiles.append(profile)
            self.config.agents.models = profiles
            if not self.config.agents.defaults.model_id:
                self.config.agents.defaults.model_id = profile.id
            self._persist_config()
            return web.json_response({"item": self._serialize_model(profile)})
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.error("Failed to create model profile: {}", e)
            return web.json_response({"error": str(e)}, status=500)

    async def _test_model(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            profile = self._parse_model_payload(body, existing_id=str(body.get("id") or "probe"))
            temp_config = self.config.model_copy(deep=True)
            profiles = temp_config.get_model_profiles()
            index = next((idx for idx, item in enumerate(profiles) if item.id == profile.id), -1)
            if index >= 0:
                profiles[index] = profile
            else:
                profiles.append(profile)
            temp_config.agents.models = profiles
            temp_config.agents.defaults.model_id = profile.id

            provider, runtime = make_provider(temp_config)
            response = await provider.chat_with_retry(
                messages=[{"role": "user", "content": "Reply with OK only."}],
                tools=[],
                model=runtime.profile.model,
                max_tokens=min(runtime.max_tokens, 32),
                temperature=runtime.temperature,
                reasoning_effort=runtime.reasoning_effort,
            )
            if response.finish_reason == "error":
                raise ValueError(response.content or "模型调用失败")
            preview = (response.content or "").strip() or "OK"
            return web.json_response({
                "ok": True,
                "provider": runtime.provider_name or runtime.profile.provider,
                "model": runtime.profile.model,
                "message": preview[:120],
            })
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.error("Failed to test model profile: {}", e)
            return web.json_response({"error": str(e)}, status=500)

    async def _update_model(self, request: web.Request) -> web.Response:
        model_id = request.match_info["model_id"]
        try:
            body = await request.json()
            profiles = self.config.get_model_profiles()
            index = next((idx for idx, item in enumerate(profiles) if item.id == model_id), -1)
            if index < 0:
                return web.json_response({"error": "Model not found"}, status=404)
            updated = self._parse_model_payload(body, existing_id=model_id)
            profiles[index] = updated
            if not any(item.enabled for item in profiles):
                raise ValueError("At least one enabled model is required")
            self.config.agents.models = profiles
            if self.config.agents.defaults.model_id == model_id and not updated.enabled:
                fallback = next((item for item in profiles if item.id != model_id and item.enabled), None)
                if fallback:
                    self.config.agents.defaults.model_id = fallback.id
                else:
                    raise ValueError("At least one enabled model is required")
            self._persist_config()
            return web.json_response({"item": self._serialize_model(updated)})
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.error("Failed to update model profile {}: {}", model_id, e)
            return web.json_response({"error": str(e)}, status=500)

    async def _delete_model(self, request: web.Request) -> web.Response:
        model_id = request.match_info["model_id"]
        profiles = self.config.get_model_profiles()
        if len(profiles) <= 1:
            return web.json_response({"error": "At least one model profile is required"}, status=400)
        remaining = [item for item in profiles if item.id != model_id]
        if len(remaining) == len(profiles):
            return web.json_response({"error": "Model not found"}, status=404)
        if not any(item.enabled for item in remaining):
            return web.json_response({"error": "At least one enabled model is required"}, status=400)
        self.config.agents.models = remaining
        if self.config.agents.defaults.model_id == model_id:
            fallback = next((item for item in remaining if item.enabled), remaining[0])
            self.config.agents.defaults.model_id = fallback.id
        self._persist_config()
        return web.json_response({"ok": True, "modelId": model_id, "defaultModelId": self.config.agents.defaults.model_id})

    async def _select_model(self, request: web.Request) -> web.Response:
        model_id = request.match_info["model_id"]
        profiles = self.config.get_model_profiles()
        selected = next((item for item in profiles if item.id == model_id), None)
        if not selected:
            return web.json_response({"error": "Model not found"}, status=404)
        if not selected.enabled:
            return web.json_response({"error": "Cannot select a disabled model"}, status=400)
        self.config.agents.defaults.model_id = selected.id
        try:
            self._persist_config()
            return web.json_response({"ok": True, "defaultModelId": selected.id})
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.error("Failed to select model profile {}: {}", model_id, e)
            return web.json_response({"error": str(e)}, status=500)

    async def _list_providers(self, request: web.Request) -> web.Response:
        return web.json_response({
            "items": [
                self._serialize_provider(spec.name)
                for spec in PROVIDERS
                if spec.name in DESKTOP_SUPPORTED_PROVIDER_NAMES
            ],
        })

    async def _update_provider(self, request: web.Request) -> web.Response:
        provider_id = request.match_info["provider_id"].replace("-", "_")
        if not hasattr(self.config.providers, provider_id):
            return web.json_response({"error": "Provider not found"}, status=404)
        try:
            body = await request.json()
            extra_headers = body.get("extraHeaders")
            if extra_headers is not None and not isinstance(extra_headers, dict):
                raise ValueError("extraHeaders must be an object")

            provider_cfg = getattr(self.config.providers, provider_id)
            provider_cfg.api_key = str(body.get("apiKey") or "").strip()
            api_base = body.get("apiBase")
            provider_cfg.api_base = str(api_base).strip() if api_base not in (None, "") else None
            provider_cfg.extra_headers = (
                {str(k): str(v) for k, v in (extra_headers or {}).items()} or None
            )
            self._persist_config()
            return web.json_response({"item": self._serialize_provider(provider_id)})
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.error("Failed to update provider {}: {}", provider_id, e)
            return web.json_response({"error": str(e)}, status=500)

    async def _test_provider(self, request: web.Request) -> web.Response:
        provider_id = request.match_info["provider_id"].replace("-", "_")
        if not hasattr(self.config.providers, provider_id):
            return web.json_response({"error": "Provider not found"}, status=404)
        try:
            body = await request.json()
            extra_headers = body.get("extraHeaders")
            if extra_headers is not None and not isinstance(extra_headers, dict):
                raise ValueError("extraHeaders must be an object")

            temp_config = self.config.model_copy(deep=True)
            provider_cfg = getattr(temp_config.providers, provider_id)
            provider_cfg.api_key = str(body.get("apiKey") or "").strip()
            api_base = body.get("apiBase")
            provider_cfg.api_base = str(api_base).strip() if api_base not in (None, "") else None
            provider_cfg.extra_headers = {str(k): str(v) for k, v in (extra_headers or {}).items()} or None

            candidate = next(
                (item for item in temp_config.get_model_profiles() if item.provider == provider_id and item.enabled),
                None,
            )
            if candidate is None:
                return web.json_response(
                    {"error": "当前没有使用该 Provider 的启用模型，请先在模型配置里创建或启用一个对应模型。"},
                    status=400,
                )

            temp_config.agents.defaults.model_id = candidate.id
            provider, runtime = make_provider(temp_config)
            response = await provider.chat_with_retry(
                messages=[{"role": "user", "content": "Reply with OK only."}],
                tools=[],
                model=runtime.profile.model,
                max_tokens=min(runtime.max_tokens, 32),
                temperature=runtime.temperature,
                reasoning_effort=runtime.reasoning_effort,
            )
            if response.finish_reason == "error":
                raise ValueError(response.content or "Provider 调用失败")
            preview = (response.content or "").strip() or "OK"
            return web.json_response({
                "ok": True,
                "provider": provider_id,
                "model": runtime.profile.model,
                "message": preview[:120],
            })
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.error("Failed to test provider {}: {}", provider_id, e)
            return web.json_response({"error": str(e)}, status=500)

    # ------------------------------------------------------------------ #
    # REST: Cron
    # ------------------------------------------------------------------ #

    @staticmethod
    def _cron_service(agent: "AgentLoop"):
        return getattr(agent, "cron_service", None)

    @staticmethod
    def _serialize_cron_job(job) -> dict[str, Any]:
        return {
            "id": job.id,
            "name": job.name,
            "enabled": job.enabled,
            "deleteAfterRun": job.delete_after_run,
            "schedule": {
                "kind": job.schedule.kind,
                "atMs": job.schedule.at_ms,
                "everyMs": job.schedule.every_ms,
                "expr": job.schedule.expr,
                "tz": job.schedule.tz,
            },
            "payload": {
                "message": job.payload.message,
                "deliver": job.payload.deliver,
                "channel": job.payload.channel,
                "to": job.payload.to,
            },
            "state": {
                "nextRunAtMs": job.state.next_run_at_ms,
                "lastRunAtMs": job.state.last_run_at_ms,
                "lastStatus": job.state.last_status,
                "lastError": job.state.last_error,
            },
            "createdAtMs": job.created_at_ms,
            "updatedAtMs": job.updated_at_ms,
        }

    @staticmethod
    def _parse_cron_schedule(data: dict[str, Any]):
        from nanobot.cron.types import CronSchedule

        kind = data.get("kind")
        if kind not in {"at", "every", "cron"}:
            raise ValueError("schedule.kind must be one of: at, every, cron")

        if kind == "at":
            at_ms = data.get("atMs")
            if not isinstance(at_ms, int) or at_ms <= 0:
                raise ValueError("schedule.atMs is required for one-time jobs")
            return CronSchedule(kind="at", at_ms=at_ms)

        if kind == "every":
            every_ms = data.get("everyMs")
            if not isinstance(every_ms, int) or every_ms <= 0:
                raise ValueError("schedule.everyMs is required for interval jobs")
            return CronSchedule(kind="every", every_ms=every_ms)

        expr = data.get("expr")
        if not isinstance(expr, str) or not expr.strip():
            raise ValueError("schedule.expr is required for cron jobs")
        tz = data.get("tz")
        if tz is not None and not isinstance(tz, str):
            raise ValueError("schedule.tz must be a string")
        return CronSchedule(kind="cron", expr=expr.strip(), tz=(tz or None))

    async def _list_cron_jobs(self, request: web.Request) -> web.Response:
        cron = self._cron_service(self.agent)
        if not cron:
            return web.json_response({"error": "Cron service unavailable"}, status=503)

        jobs = cron.list_jobs(include_disabled=True)
        return web.json_response({
            "status": cron.status(),
            "jobs": [self._serialize_cron_job(job) for job in jobs],
        })

    async def _create_cron_job(self, request: web.Request) -> web.Response:
        cron = self._cron_service(self.agent)
        if not cron:
            return web.json_response({"error": "Cron service unavailable"}, status=503)

        try:
            body = await request.json()
            schedule = self._parse_cron_schedule(body.get("schedule") or {})
            name = str(body.get("name") or "").strip()
            message = str((body.get("payload") or {}).get("message") or "").strip()
            if not name:
                raise ValueError("name is required")
            if not message:
                raise ValueError("payload.message is required")

            payload = body.get("payload") or {}
            job = cron.add_job(
                name=name,
                schedule=schedule,
                message=message,
                deliver=bool(payload.get("deliver", False)),
                channel=payload.get("channel"),
                to=payload.get("to"),
                delete_after_run=bool(body.get("deleteAfterRun", False)),
            )
            enabled = bool(body.get("enabled", True))
            if not enabled:
                updated = cron.enable_job(job.id, False)
                if updated:
                    job = updated
            return web.json_response({"job": self._serialize_cron_job(job)})
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.error("Failed to create cron job: {}", e)
            return web.json_response({"error": str(e)}, status=500)

    async def _update_cron_job(self, request: web.Request) -> web.Response:
        cron = self._cron_service(self.agent)
        if not cron:
            return web.json_response({"error": "Cron service unavailable"}, status=503)

        job_id = request.match_info["job_id"]
        try:
            body = await request.json()
            schedule = self._parse_cron_schedule(body.get("schedule") or {})
            name = str(body.get("name") or "").strip()
            message = str((body.get("payload") or {}).get("message") or "").strip()
            if not name:
                raise ValueError("name is required")
            if not message:
                raise ValueError("payload.message is required")

            payload = body.get("payload") or {}
            job = cron.update_job(
                job_id,
                name=name,
                schedule=schedule,
                message=message,
                enabled=bool(body.get("enabled", True)),
                deliver=bool(payload.get("deliver", False)),
                channel=payload.get("channel"),
                to=payload.get("to"),
                delete_after_run=bool(body.get("deleteAfterRun", False)),
            )
            if not job:
                return web.json_response({"error": "Job not found"}, status=404)
            return web.json_response({"job": self._serialize_cron_job(job)})
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.error("Failed to update cron job {}: {}", job_id, e)
            return web.json_response({"error": str(e)}, status=500)

    async def _delete_cron_job(self, request: web.Request) -> web.Response:
        cron = self._cron_service(self.agent)
        if not cron:
            return web.json_response({"error": "Cron service unavailable"}, status=503)

        job_id = request.match_info["job_id"]
        if not cron.remove_job(job_id):
            return web.json_response({"error": "Job not found"}, status=404)
        return web.json_response({"ok": True, "jobId": job_id})

    async def _run_cron_job(self, request: web.Request) -> web.Response:
        cron = self._cron_service(self.agent)
        if not cron:
            return web.json_response({"error": "Cron service unavailable"}, status=503)

        job_id = request.match_info["job_id"]
        ran = await cron.run_job(job_id, force=True)
        if not ran:
            return web.json_response({"error": "Job not found"}, status=404)
        return web.json_response({"ok": True, "jobId": job_id})

    async def _enable_cron_job(self, request: web.Request) -> web.Response:
        cron = self._cron_service(self.agent)
        if not cron:
            return web.json_response({"error": "Cron service unavailable"}, status=503)

        job_id = request.match_info["job_id"]
        try:
            body = await request.json()
            enabled = bool(body.get("enabled", True))
            job = cron.enable_job(job_id, enabled)
            if not job:
                return web.json_response({"error": "Job not found"}, status=404)
            return web.json_response({"job": self._serialize_cron_job(job)})
        except Exception as e:
            logger.error("Failed to toggle cron job {}: {}", job_id, e)
            return web.json_response({"error": str(e)}, status=500)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def start(self, host: str = "0.0.0.0", port: int = 18790) -> None:
        """Start the API server."""
        app = self._build_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        logger.info("Gateway API server started on {}:{}", host, port)

    async def stop(self) -> None:
        """Stop the API server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            logger.info("Gateway API server stopped")
