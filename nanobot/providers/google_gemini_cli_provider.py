"""Google Gemini CLI Provider.

This provider makes direct HTTP calls to the Google Cloud Code Assist API
using OAuth tokens from the gemini CLI credentials.

Based on pi-mono implementation:
https://github.com/badlogic/pi-mono/tree/main/packages/ai/src/providers
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import httpx

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

# Code Assist API endpoint
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"


def _load_credentials() -> dict[str, str]:
    """Load OAuth credentials from token file.

    Returns:
        dict with 'access_token' and 'project_id' keys

    Raises:
        RuntimeError: If credentials not found or invalid
    """
    # First, try the nanobot token file
    token_file = os.path.expanduser("~/.nanobot/tokens/google_gemini_cli.json")

    # Second, try the gemini CLI's own credential file
    gemini_token_file = os.path.expanduser("~/.gemini/oauth_creds.json")

    # Gemini CLI projects file
    gemini_projects_file = os.path.expanduser("~/.gemini/projects.json")

    data = None
    source_file = None

    # Try nanobot token file first
    if os.path.exists(token_file):
        source_file = token_file
        try:
            with open(token_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Fall back to gemini CLI's own credential file
    if not data and os.path.exists(gemini_token_file):
        source_file = gemini_token_file
        try:
            with open(gemini_token_file) as f:
                gemini_data = json.load(f)
                # Convert gemini CLI format to nanobot format
                # gemini CLI uses 'expiry_date' (ms timestamp) and 'access_token'
                data = {
                    "access_token": gemini_data.get("access_token"),
                    "refresh_token": gemini_data.get("refresh_token", ""),
                    "expires_at": gemini_data.get("expiry_date", 0),
                    "email": gemini_data.get("id_token", ""),  # Store id_token for debugging
                }
        except (json.JSONDecodeError, IOError):
            pass

    if not data:
        raise RuntimeError(
            "Google Gemini CLI credentials not found. "
            "Please run: nanobot provider login google-gemini-cli"
        )

    # Check if token is expired (with 5 min buffer)
    expires_at = data.get("expires_at", 0)
    now_ms = int(time.time() * 1000)
    if expires_at < now_ms:
        # TODO: Implement token refresh using refresh_token
        raise RuntimeError(
            "Google Gemini CLI token has expired. "
            "Please log in to gemini CLI interactively, then run: nanobot provider login google-gemini-cli"
        )

    # For gemini CLI credentials, we need to discover the project_id
    project_id = data.get("project_id", "")
    if not project_id and source_file == gemini_token_file:
        # First, check environment variables (highest priority)
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT_ID") or ""

        # If not in env, try to get project_id from gemini CLI's projects file
        if not project_id:
            try:
                with open(gemini_projects_file) as f:
                    projects_data = json.load(f)
                    # Get the active project or use the first one
                    active = projects_data.get("active", "")
                    if active:
                        project_id = active
                    else:
                        # Use current directory's project if available
                        cwd = os.getcwd()
                        projects = projects_data.get("projects", {})
                        for path, proj_id in projects.items():
                            if cwd.startswith(path):
                                project_id = proj_id
                                break
                        # If still no project, use the first available
                        if not project_id and projects:
                            project_id = next(iter(projects.values()))
            except (json.JSONDecodeError, IOError, FileNotFoundError):
                pass

    # Validate that we have a project_id
    if not project_id:
        raise RuntimeError(
            "Google Cloud project ID not found. "
            "Please set the GOOGLE_CLOUD_PROJECT environment variable."
        )

    return {
        "access_token": data["access_token"],
        "project_id": project_id,
    }


def _strip_model_prefix(model: str) -> str:
    """Strip 'google-gemini-cli/' or 'google_gemini_cli/' prefix from model name."""
    for prefix in ("google-gemini-cli/", "google_gemini_cli/"):
        if model.startswith(prefix):
            return model.split("/", 1)[1]
    return model


def _convert_messages_to_gemini_format(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI format messages to Gemini format.

    Args:
        messages: List of OpenAI format messages

    Returns:
        List of Gemini format contents
    """
    gemini_messages = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            # System instructions are handled separately
            continue

        # Map roles
        if role == "user":
            gemini_role = "user"
        elif role == "assistant":
            gemini_role = "model"
        elif role == "tool":
            # Tool results are handled differently
            gemini_role = "user"
        else:
            continue

        # Build parts
        parts = []

        # Handle tool results first (don't add text content for tool messages)
        if role == "tool":
            tool_name = msg.get("name", "tool")
            response_content = json.dumps(content) if isinstance(content, dict) else str(content)
            parts.append({
                "functionResponse": {
                    "name": tool_name,
                    "response": {
                        "result": response_content,
                    }
                }
            })
        else:
            # Add text content for user/assistant messages
            if isinstance(content, str):
                parts.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            parts.append({"text": item.get("text", "")})

            # Handle tool calls in assistant messages
            if role == "assistant":
                for tool_call in msg.get("tool_calls", []) or []:
                    fn = tool_call.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)

                    parts.append({
                        "functionCall": {
                            "name": fn.get("name", ""),
                            "args": args,
                        }
                    })

        if parts:
            gemini_messages.append({
                "role": gemini_role,
                "parts": parts,
            })

    return gemini_messages


def _convert_tools_to_gemini_format(tools: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Convert OpenAI format tools to Gemini format.

    Args:
        tools: List of OpenAI format tools

    Returns:
        Gemini format function declarations
    """
    if not tools:
        return None

    function_declarations = []

    for tool in tools:
        function = tool.get("function", {})
        name = function.get("name", "")
        description = function.get("description", "")
        parameters = function.get("parameters", {})

        if not name:
            continue

        # Build Gemini function declaration
        declaration = {
            "name": name,
            "description": description,
            "parameters": parameters,
        }

        function_declarations.append(declaration)

    if not function_declarations:
        return None

    return {
        "functionDeclarations": function_declarations,
    }


class GoogleGeminiCliProvider(LLMProvider):
    """Use Google Cloud Code Assist API with OAuth authentication.

    This provider:
    - Uses OAuth tokens from gemini CLI credentials
    - Makes direct HTTP calls to Code Assist API
    - Supports streaming responses
    - Supports function calling
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "google-gemini-cli/gemini-3-pro-preview",
    ):
        super().__init__(api_key=api_key, api_base=api_base)
        self.default_model = default_model
        self.endpoint = api_base or CODE_ASSIST_ENDPOINT

        # Load credentials
        self.credentials = _load_credentials()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 1048576,
        temperature: float = 1.0,
    ) -> LLMResponse:
        """Make a chat completion request to Code Assist API.

        Args:
            messages: List of messages in OpenAI format
            tools: Optional list of tools
            model: Model name (with or without prefix)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            LLMResponse with content and optional tool calls
        """
        model = model or self.default_model
        model = _strip_model_prefix(model)

        # Extract system prompt
        system_instruction = None
        user_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_instruction = msg.get("content")
            else:
                user_messages.append(msg)

        # Convert messages to Gemini format
        contents = _convert_messages_to_gemini_format(user_messages)

        # Convert tools to Gemini format
        gemini_tools = _convert_tools_to_gemini_format(tools)

        # Build request body
        request_body: dict[str, Any] = {
            "project": self.credentials["project_id"],
            "model": model,
            "request": {
                "contents": contents,
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": temperature,
                },
            },
            "userAgent": "nanobot",
            "requestId": f"nanobot-{uuid.uuid4()}",
        }

        if system_instruction:
            request_body["request"]["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        if gemini_tools:
            request_body["request"]["tools"] = [gemini_tools]

        # Make streaming request
        url = f"{self.endpoint}/v1internal:streamGenerateContent?alt=sse"

        headers = {
            "Authorization": f"Bearer {self.credentials['access_token']}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "google-cloud-sdk vscode_cloudshelleditor/0.1",
            "X-Goog-Api-Client": "gl-node/22.17.0",
            "Client-Metadata": json.dumps({
                "ideType": "IDE_UNSPECIFIED",
                "platform": "PLATFORM_UNSPECIFIED",
                "pluginType": "GEMINI",
            }),
        }

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    url,
                    json=request_body,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        try:
                            error_json = json.loads(error_text)
                            logger.error(f"Code Assist API error {response.status_code}: {json.dumps(error_json, indent=2)}")
                        except Exception:
                            logger.error(f"Code Assist API error {response.status_code}: {error_text}")
                        return LLMResponse(
                            content=f"API error: {response.status_code}",
                            finish_reason="error",
                        )

                    # Parse SSE stream
                    content_parts = []
                    tool_calls = []
                    finish_reason = "stop"

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue

                        try:
                            data_str = line[6:]  # Strip "data: " prefix
                            chunk = json.loads(data_str)

                            # Extract response
                            response_data = chunk.get("response", {})
                            candidates = response_data.get("candidates", [])

                            if candidates:
                                candidate = candidates[0]
                                parts = candidate.get("content", {}).get("parts", [])

                                for part in parts:
                                    # Text content
                                    if "text" in part:
                                        content_parts.append(part["text"])

                                    # Function call
                                    if "functionCall" in part:
                                        fc = part["functionCall"]
                                        tool_calls.append(
                                            ToolCallRequest(
                                                id=str(uuid.uuid4()),
                                                name=fc.get("name", ""),
                                                arguments=fc.get("args", {}),
                                            )
                                        )

                                # Check finish reason
                                if "finishReason" in candidate:
                                    finish_reason = candidate["finishReason"]

                        except json.JSONDecodeError:
                            continue

                    return LLMResponse(
                        content="".join(content_parts),
                        tool_calls=tool_calls,
                        finish_reason=finish_reason,
                    )

        except httpx.TimeoutException:
            return LLMResponse(
                content="Request timed out",
                finish_reason="error",
            )
        except Exception as e:
            logger.error(f"Error calling Code Assist API: {e}")
            return LLMResponse(
                content=f"Error: {str(e)}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        return self.default_model
