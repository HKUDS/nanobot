"""Gemini provider backed by Google ADC OAuth credentials."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

DEFAULT_GEMINI_API_BASE = "https://generativelanguage.googleapis.com"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
ADC_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def get_adc_status() -> dict[str, Any]:
    data = _load_adc_file()
    if not data:
        return {"authorized": False}
    try:
        token = _refresh_access_token(data)
        return {
            "authorized": True,
            "accountId": data.get("client_id"),
            "expiresAt": token.get("expires_at"),
            "quotaProjectId": data.get("quota_project_id"),
        }
    except Exception as exc:
        return {
            "authorized": False,
            "error": str(exc),
        }


def revoke_adc() -> list[str]:
    removed: list[str] = []
    if ADC_PATH.exists():
        ADC_PATH.unlink()
        removed.append(str(ADC_PATH))
    legacy = Path(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")).expanduser()
    if legacy and str(legacy) and legacy.exists() and legacy != ADC_PATH:
        legacy.unlink()
        removed.append(str(legacy))
    return removed


def import_adc_config(source_path: str) -> str:
    source = Path(source_path).expanduser()
    if not source.exists() or not source.is_file():
        raise RuntimeError("凭据文件不存在")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"凭据文件不是有效 JSON: {exc}") from exc

    cred_type = str(data.get("type") or "")
    if cred_type == "authorized_user":
        required = ("client_id", "client_secret", "refresh_token")
    elif cred_type == "service_account":
        required = ("client_email", "private_key", "project_id")
    else:
        raise RuntimeError("暂不支持该凭据类型，请导入 Google ADC/authorized_user 或 service_account JSON")

    missing = [key for key in required if not data.get(key)]
    if missing:
        raise RuntimeError(f"凭据文件缺少字段: {', '.join(missing)}")

    ADC_PATH.parent.mkdir(parents=True, exist_ok=True)
    ADC_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(ADC_PATH, 0o600)
    except Exception:
        pass
    return str(ADC_PATH)


class GeminiOAuthProvider(LLMProvider):
    """Call Gemini REST API using Google ADC OAuth credentials."""

    def __init__(self, default_model: str = DEFAULT_GEMINI_MODEL, api_base: str | None = None):
        super().__init__(api_key=None, api_base=api_base or DEFAULT_GEMINI_API_BASE)
        self.default_model = default_model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        resolved_model = _strip_model_prefix(model or self.default_model)
        adc = await asyncio.to_thread(_load_adc_file)
        if not adc:
            raise RuntimeError("Gemini OAuth 未授权，请先执行 gcloud auth application-default login")
        token = await asyncio.to_thread(_refresh_access_token, adc)

        headers = {
            "Authorization": f"Bearer {token['access_token']}",
            "Content-Type": "application/json",
        }
        quota_project_id = adc.get("quota_project_id")
        if quota_project_id:
            headers["x-goog-user-project"] = str(quota_project_id)

        body = _build_generate_content_request(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            tool_choice=tool_choice,
        )
        url = f"{(self.api_base or DEFAULT_GEMINI_API_BASE).rstrip('/')}/v1beta/models/{resolved_model}:generateContent"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=body)
        if response.status_code != 200:
            raise RuntimeError(f"Gemini OAuth request failed: {response.status_code} {response.text}")
        return _parse_generate_content_response(response.json())


def _strip_model_prefix(model: str) -> str:
    if model.startswith("gemini_oauth/") or model.startswith("gemini-oauth/"):
        return model.split("/", 1)[1]
    return model


def _load_adc_file() -> dict[str, Any] | None:
    path = Path(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")).expanduser()
    if path and str(path) and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    if not ADC_PATH.exists():
        return None
    try:
        return json.loads(ADC_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _refresh_access_token(adc: dict[str, Any]) -> dict[str, Any]:
    refresh_token = adc.get("refresh_token")
    client_id = adc.get("client_id")
    client_secret = adc.get("client_secret")
    if not (refresh_token and client_id and client_secret):
        raise RuntimeError("Gemini OAuth 凭据不完整，请重新执行 gcloud auth application-default login")

    response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30.0,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Gemini OAuth token refresh failed: {response.status_code} {response.text}")
    payload = response.json()
    access_token = payload.get("access_token")
    expires_in = int(payload.get("expires_in") or 0)
    if not access_token:
        raise RuntimeError("Gemini OAuth token response missing access_token")
    return {
        "access_token": access_token,
        "expires_at": int(time.time()) + expires_in,
    }


def _build_generate_content_request(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    temperature: float,
    max_tokens: int,
    tool_choice: str | dict[str, Any] | None,
) -> dict[str, Any]:
    system_instruction = ""
    contents: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            if isinstance(content, str):
                system_instruction = content
            continue
        if role == "user":
            contents.append({"role": "user", "parts": _convert_content_parts(content)})
            continue
        if role == "assistant":
            parts = _convert_content_parts(content)
            for tool_call in msg.get("tool_calls") or []:
                fn = tool_call.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                parts.append({
                    "functionCall": {
                        "name": fn.get("name") or "",
                        "args": args or {},
                    }
                })
            if parts:
                contents.append({"role": "model", "parts": parts})
            continue
        if role == "tool":
            output = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "name": msg.get("name") or "tool",
                        "response": {"content": output},
                    }
                }],
            })

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    if tools:
        payload["tools"] = [{"functionDeclarations": _convert_tools(tools)}]
        if tool_choice == "required":
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}
    return payload


def _convert_content_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}]
    parts: list[dict[str, Any]] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append({"text": str(item.get("text") or "")})
            elif item.get("type") == "image_url":
                url = ((item.get("image_url") or {}).get("url")) or ""
                inline = _data_url_to_inline_data(url)
                if inline:
                    parts.append({"inlineData": inline})
    return parts or [{"text": ""}]


def _data_url_to_inline_data(url: str) -> dict[str, str] | None:
    if not url.startswith("data:"):
        return None
    try:
        header, data = url.split(",", 1)
        mime = header.split(":", 1)[1].split(";", 1)[0]
        if ";base64" not in header:
            data = base64.b64encode(data.encode("utf-8")).decode("ascii")
        return {"mimeType": mime, "data": data}
    except Exception:
        return None


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for tool in tools:
        fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
        name = fn.get("name")
        if not name:
            continue
        declarations.append({
            "name": name,
            "description": fn.get("description") or "",
            "parameters": fn.get("parameters") or {"type": "OBJECT", "properties": {}},
        })
    return declarations


def _parse_generate_content_response(payload: dict[str, Any]) -> LLMResponse:
    candidates = payload.get("candidates") or []
    if not candidates:
        return LLMResponse(content="", finish_reason="stop")
    candidate = candidates[0]
    content = candidate.get("content") or {}
    parts = content.get("parts") or []
    text_parts: list[str] = []
    tool_calls: list[ToolCallRequest] = []
    for part in parts:
        if "text" in part:
            text_parts.append(str(part.get("text") or ""))
        if "functionCall" in part:
            call = part["functionCall"] or {}
            tool_calls.append(ToolCallRequest(
                id=str(uuid.uuid4()),
                name=str(call.get("name") or ""),
                arguments=call.get("args") if isinstance(call.get("args"), dict) else {},
            ))
    finish_reason = str(candidate.get("finishReason") or "stop").lower()
    return LLMResponse(
        content="\n".join([p for p in text_parts if p]).strip() or None,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
    )
