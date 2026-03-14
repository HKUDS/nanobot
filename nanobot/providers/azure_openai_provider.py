"""Azure OpenAI provider implementation with API version 2024-10-21."""

from __future__ import annotations

import time
import uuid
from typing import Any
from urllib.parse import urljoin

import httpx
import json_repair

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_AZURE_MSG_KEYS = frozenset({"role", "content", "tool_calls", "tool_call_id", "name"})


class AzureOpenAIProvider(LLMProvider):
    """
    Azure OpenAI provider with API version 2024-10-21 compliance.
    
    Features:
    - Hardcoded API version 2024-10-21
    - Uses model field as Azure deployment name in URL path
    - Supports both api-key and Entra ID OAuth authentication
    - Uses max_completion_tokens instead of max_tokens
    - Direct HTTP calls, bypasses LiteLLM
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        default_model: str = "gpt-5.2-chat",
        use_entra_auth: bool = False,
        client_id: str = "",
        client_secret: str = "",
        tenant_id: str = "",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.api_version = "2024-10-21"
        
        # Determine authentication method
        # If api_key is empty, fall back to OAuth
        self.use_entra_auth = use_entra_auth or (not api_key)
        
        if self.use_entra_auth:
            # OAuth authentication
            if not client_id or not client_secret or not tenant_id:
                raise ValueError(
                    "Entra ID OAuth requires client_id, client_secret, and tenant_id"
                )
            self.client_id = client_id
            self.client_secret = client_secret
            self.tenant_id = tenant_id
            
            # Token cache
            self._access_token: str | None = None
            self._token_expires_at: float = 0
        else:
            # API key authentication
            if not api_key:
                raise ValueError("Azure OpenAI api_key is required")
        
        # Validate required parameters
        if not api_base:
            raise ValueError("Azure OpenAI api_base is required")
        
        # Ensure api_base ends with /
        if not api_base.endswith('/'):
            api_base += '/'
        self.api_base = api_base

    def _build_chat_url(self, deployment_name: str) -> str:
        """Build the Azure OpenAI chat completions URL."""
        # Azure OpenAI URL format:
        # https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version={version}
        base_url = self.api_base
        if not base_url.endswith('/'):
            base_url += '/'
        
        url = urljoin(
            base_url, 
            f"openai/deployments/{deployment_name}/chat/completions"
        )
        return f"{url}?api-version={self.api_version}"

    async def _get_access_token(self) -> str:
        """Get or refresh Entra ID OAuth access token."""
        # Return cached token if still valid (with 5 min buffer)
        if self._access_token and time.time() < (self._token_expires_at - 300):
            return self._access_token
        
        # Request new token
        token_endpoint = (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        )
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://cognitiveservices.azure.com/.default",
            "grant_type": "client_credentials",
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                token_endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            token_data = response.json()
            
            self._access_token = token_data["access_token"]
            # expires_in is in seconds
            self._token_expires_at = time.time() + token_data.get("expires_in", 3600)
            
            return self._access_token

    async def _build_headers(self) -> dict[str, str]:
        """Build headers for Azure OpenAI API with api-key or OAuth Bearer token."""
        headers = {
            "Content-Type": "application/json",
            "x-session-affinity": uuid.uuid4().hex,  # For cache locality
        }
        
        if self.use_entra_auth:
            # Use OAuth Bearer token
            access_token = await self._get_access_token()
            headers["Authorization"] = f"Bearer {access_token}"
        else:
            # Use api-key header
            headers["api-key"] = self.api_key
        
        return headers

    @staticmethod
    def _supports_temperature(
        deployment_name: str,
        reasoning_effort: str | None = None,
    ) -> bool:
        """Return True when temperature is likely supported for this deployment."""
        if reasoning_effort:
            return False
        name = deployment_name.lower()
        return not any(token in name for token in ("gpt-5", "o1", "o3", "o4"))

    def _prepare_request_payload(
        self,
        deployment_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Prepare the request payload with Azure OpenAI 2024-10-21 compliance."""
        payload: dict[str, Any] = {
            "messages": self._sanitize_request_messages(
                self._sanitize_empty_content(messages),
                _AZURE_MSG_KEYS,
            ),
            "max_completion_tokens": max(1, max_tokens),  # Azure API 2024-10-21 uses max_completion_tokens
        }

        if self._supports_temperature(deployment_name, reasoning_effort):
            payload["temperature"] = temperature

        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        return payload

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
        """
        Send a chat completion request to Azure OpenAI.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (used as deployment name).
            max_tokens: Maximum tokens in response (mapped to max_completion_tokens).
            temperature: Sampling temperature.
            reasoning_effort: Optional reasoning effort parameter.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        deployment_name = model or self.default_model
        url = self._build_chat_url(deployment_name)
        headers = await self._build_headers()
        payload = self._prepare_request_payload(
            deployment_name, messages, tools, max_tokens, temperature, reasoning_effort,
            tool_choice=tool_choice,
        )

        try:
            async with httpx.AsyncClient(timeout=60.0, verify=True) as client:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code != 200:
                    return LLMResponse(
                        content=f"Azure OpenAI API Error {response.status_code}: {response.text}",
                        finish_reason="error",
                    )
                
                response_data = response.json()
                return self._parse_response(response_data)

        except Exception as e:
            return LLMResponse(
                content=f"Error calling Azure OpenAI: {repr(e)}",
                finish_reason="error",
            )

    def _parse_response(self, response: dict[str, Any]) -> LLMResponse:
        """Parse Azure OpenAI response into our standard format."""
        try:
            choice = response["choices"][0]
            message = choice["message"]

            tool_calls = []
            if message.get("tool_calls"):
                for tc in message["tool_calls"]:
                    # Parse arguments from JSON string if needed
                    args = tc["function"]["arguments"]
                    if isinstance(args, str):
                        args = json_repair.loads(args)

                    tool_calls.append(
                        ToolCallRequest(
                            id=tc["id"],
                            name=tc["function"]["name"],
                            arguments=args,
                        )
                    )

            usage = {}
            if response.get("usage"):
                usage_data = response["usage"]
                usage = {
                    "prompt_tokens": usage_data.get("prompt_tokens", 0),
                    "completion_tokens": usage_data.get("completion_tokens", 0),
                    "total_tokens": usage_data.get("total_tokens", 0),
                }

            reasoning_content = message.get("reasoning_content") or None

            return LLMResponse(
                content=message.get("content"),
                tool_calls=tool_calls,
                finish_reason=choice.get("finish_reason", "stop"),
                usage=usage,
                reasoning_content=reasoning_content,
            )

        except (KeyError, IndexError) as e:
            return LLMResponse(
                content=f"Error parsing Azure OpenAI response: {str(e)}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        """Get the default model (also used as default deployment name)."""
        return self.default_model