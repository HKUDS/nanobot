"""Anthropic OAuth provider for nanobot.

Uses Claude CLI credentials (~/.claude/.credentials.json) to make API calls
using the subscription's OAuth token instead of a traditional API key.

This enables using Claude Pro/Max subscription without needing a separate API key.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

# Anthropic OAuth constants (from OpenClaw/pi-ai)
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Buffer time before token expiry (5 minutes in ms)
EXPIRY_BUFFER_MS = 5 * 60 * 1000


class AnthropicOAuthCredentials:
    """Manages Anthropic OAuth credentials from Claude CLI."""
    
    def __init__(self, credentials_path: Path | None = None):
        """Initialize credentials manager.
        
        Args:
            credentials_path: Path to Claude CLI credentials file.
                            Defaults to ~/.claude/.credentials.json
        """
        self.credentials_path = credentials_path or Path.home() / ".claude" / ".credentials.json"
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: int = 0
        self._load_credentials()
    
    def _load_credentials(self) -> None:
        """Load credentials from Claude CLI file."""
        if not self.credentials_path.exists():
            logger.warning(f"Claude CLI credentials not found: {self.credentials_path}")
            return
        
        try:
            with open(self.credentials_path) as f:
                data = json.load(f)
            
            oauth = data.get("claudeAiOauth", {})
            self._access_token = oauth.get("accessToken")
            self._refresh_token = oauth.get("refreshToken")
            self._expires_at = oauth.get("expiresAt", 0)
            
            if self._access_token:
                logger.info(f"Loaded Anthropic OAuth credentials (expires in {self._time_until_expiry_hours():.1f}h)")
            else:
                logger.warning("No access token found in Claude CLI credentials")
                
        except Exception as e:
            logger.error(f"Failed to load Claude CLI credentials: {e}")
    
    def _time_until_expiry_hours(self) -> float:
        """Get time until token expiry in hours."""
        now = int(time.time() * 1000)
        diff_ms = self._expires_at - now
        return diff_ms / (1000 * 60 * 60)
    
    def _is_expired(self) -> bool:
        """Check if token is expired or about to expire."""
        now = int(time.time() * 1000)
        return now >= (self._expires_at - EXPIRY_BUFFER_MS)
    
    async def _refresh(self) -> bool:
        """Refresh the OAuth token.
        
        Returns:
            True if refresh was successful.
        """
        if not self._refresh_token:
            logger.error("No refresh token available")
            return False
        
        logger.info("Refreshing Anthropic OAuth token...")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    TOKEN_URL,
                    headers={"Content-Type": "application/json"},
                    json={
                        "grant_type": "refresh_token",
                        "client_id": CLIENT_ID,
                        "refresh_token": self._refresh_token,
                    },
                    timeout=30.0,
                )
                
                if response.status_code != 200:
                    logger.error(f"Token refresh failed: {response.status_code} {response.text}")
                    return False
                
                data = response.json()
                
                # Update tokens
                self._access_token = data.get("access_token")
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                expires_in = data.get("expires_in", 3600)
                self._expires_at = int(time.time() * 1000) + (expires_in * 1000) - EXPIRY_BUFFER_MS
                
                # Save back to credentials file
                self._save_credentials()
                
                logger.info(f"Token refreshed successfully (expires in {self._time_until_expiry_hours():.1f}h)")
                return True
                
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return False
    
    def _save_credentials(self) -> None:
        """Save updated credentials back to file."""
        try:
            # Read existing file
            if self.credentials_path.exists():
                with open(self.credentials_path) as f:
                    data = json.load(f)
            else:
                data = {}
            
            # Update OAuth section
            data["claudeAiOauth"] = {
                **data.get("claudeAiOauth", {}),
                "accessToken": self._access_token,
                "refreshToken": self._refresh_token,
                "expiresAt": self._expires_at,
            }
            
            # Write back
            with open(self.credentials_path, "w") as f:
                json.dump(data, f)
            
            logger.debug("Saved refreshed credentials to Claude CLI file")
            
        except Exception as e:
            logger.warning(f"Failed to save credentials: {e}")
    
    async def get_access_token(self) -> str | None:
        """Get a valid access token, refreshing if necessary.
        
        Returns:
            Valid access token or None if unavailable.
        """
        if not self._access_token:
            return None
        
        if self._is_expired():
            success = await self._refresh()
            if not success:
                return None
        
        return self._access_token
    
    @property
    def available(self) -> bool:
        """Check if credentials are available."""
        return bool(self._access_token)


class AnthropicOAuthProvider:
    """LLM provider using Anthropic OAuth (Claude Pro/Max subscription)."""
    
    def __init__(
        self,
        credentials: AnthropicOAuthCredentials | None = None,
        default_model: str = "claude-opus-4-5",
        max_tokens: int = 8192,
    ):
        """Initialize the provider.
        
        Args:
            credentials: OAuth credentials manager. Creates default if not provided.
            default_model: Default model to use.
            max_tokens: Default max tokens for responses.
        """
        self.credentials = credentials or AnthropicOAuthCredentials()
        self.default_model = default_model
        self.max_tokens = max_tokens
    
    @property
    def available(self) -> bool:
        """Check if provider is available."""
        return self.credentials.available
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
    
    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs,
    ) -> "LLMResponse":
        """Send a chat completion request.
        
        Args:
            messages: List of messages.
            model: Model to use (defaults to default_model).
            max_tokens: Max tokens for response.
            temperature: Temperature for sampling.
            tools: Optional tool definitions.
            
        Returns:
            LLMResponse with the result.
        """
        from nanobot.providers.base import LLMResponse, ToolCallRequest
        
        token = await self.credentials.get_access_token()
        if not token:
            return LLMResponse(
                content="Error: No valid OAuth token available. Please run 'claude auth' to authenticate.",
                tool_calls=[],
            )
        
        model = model or self.default_model
        max_tokens = max_tokens or self.max_tokens
        
        # Separate system message
        system_content = None
        api_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")
            else:
                api_messages.append(msg)
        
        # Build request
        request_body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": api_messages,
        }
        
        if system_content:
            request_body["system"] = system_content
        
        if temperature is not None:
            request_body["temperature"] = temperature
        
        if tools:
            request_body["tools"] = tools
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    API_URL,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token}",
                        "anthropic-version": ANTHROPIC_VERSION,
                    },
                    json=request_body,
                    timeout=300.0,
                )
                
                if response.status_code != 200:
                    error_text = response.text
                    logger.error(f"Anthropic API error: {response.status_code} {error_text}")
                    
                    # Check if it's an auth error - might need refresh
                    if response.status_code == 401:
                        logger.info("Got 401, attempting token refresh...")
                        if await self.credentials._refresh():
                            # Retry with new token
                            return await self.chat(
                                messages=messages,
                                model=model,
                                max_tokens=max_tokens,
                                temperature=temperature,
                                tools=tools,
                                **kwargs,
                            )
                    
                    return LLMResponse(
                        content=f"Error calling Anthropic API: {response.status_code} {error_text}",
                        tool_calls=[],
                    )
                
                data = response.json()
                
                # Parse response
                content = ""
                tool_calls = []
                
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        content += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tool_calls.append(ToolCallRequest(
                            id=block.get("id", ""),
                            name=block.get("name", ""),
                            arguments=block.get("input", {}),
                        ))
                
                return LLMResponse(
                    content=content,
                    tool_calls=tool_calls,
                )
                
        except httpx.TimeoutException:
            logger.error("Anthropic API timeout")
            return LLMResponse(
                content="Error: Request timed out",
                tool_calls=[],
            )
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return LLMResponse(
                content=f"Error: {str(e)}",
                tool_calls=[],
            )


def create_anthropic_oauth_provider(
    default_model: str = "claude-opus-4-5",
    max_tokens: int = 8192,
) -> AnthropicOAuthProvider | None:
    """Create an Anthropic OAuth provider if credentials are available.
    
    Args:
        default_model: Default model to use.
        max_tokens: Default max tokens.
        
    Returns:
        Provider instance or None if no credentials.
    """
    credentials = AnthropicOAuthCredentials()
    if not credentials.available:
        logger.warning("No Anthropic OAuth credentials found")
        return None
    
    return AnthropicOAuthProvider(
        credentials=credentials,
        default_model=default_model,
        max_tokens=max_tokens,
    )
