"""Ollama LLM provider implementation."""

import asyncio
import json
import os
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class OllamaProvider(LLMProvider):
    """
    LLM provider using Ollama for local and cloud models.
    
    Supports:
    - Local Ollama models (default: http://localhost:11434)
    - Ollama cloud models
    - Tool calling
    - Token counting from Ollama metrics
    """
    
    def __init__(
        self,
        mode: str = "local",
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = "qwen3:4b",
        timeout: int = 120,
    ):
        # For compatibility with base class
        super().__init__(api_key, base_url)
        self.default_model = default_model
        self.timeout = timeout
        
        # Determine mode and configuration
        self.mode = mode
        self.is_cloud = (mode == "cloud")
        
        if self.is_cloud:
            # Cloud mode: requires API key
            if not api_key:
                logger.warning("Ollama cloud mode requires API key")
                self._available = False
                return
            self.base_url = "https://ollama.com"
            self.api_key = api_key
        else:
            # Local mode
            self.base_url = base_url or "http://localhost:11434"
            self.api_key = None
        
        # Import ollama here to allow graceful degradation
        try:
            import ollama
            self.ollama = ollama
            
            # Create client with appropriate configuration
            if self.is_cloud:
                # Cloud mode with authentication
                self.client = ollama.Client(
                    host=self.base_url,
                    headers={'Authorization': f'Bearer {api_key}'}
                )
            else:
                # Local mode
                self.client = ollama.Client(host=self.base_url)
            
            self._available = True
            logger.info(f"Ollama provider initialized: {mode} mode at {self.base_url}")
        except ImportError:
            logger.warning("ollama package not installed. Run: pip install ollama")
            self.ollama = None
            self.client = None
            self._available = False
    
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via Ollama.
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'qwen3:4b', 'llama3.2').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
        
        Returns:
            LLMResponse with content and/or tool calls.
        """
        if not self._available:
            return LLMResponse(
                content="Error: Ollama provider not available. Install with: pip install ollama",
                finish_reason="error",
            )
        
        model = model or self.default_model
        
        # Preprocess messages: Ollama SDK expects tool_call arguments as dict, not JSON string
        messages = self._preprocess_messages(messages)
        
        # Build request parameters
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        
        # Add tools if provided
        if tools:
            kwargs["tools"] = tools
        
        try:
            # Use synchronous chat for now (ollama SDK doesn't have async)
            # Wrap in asyncio.to_thread to avoid blocking
            response = await asyncio.to_thread(
                self.client.chat,
                **kwargs
            )
            return self._parse_response(response, model)
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            return LLMResponse(
                content=f"Error calling Ollama: {str(e)}",
                finish_reason="error",
            )
    
    def _preprocess_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Preprocess messages to convert tool_call arguments from JSON strings to dicts.
        Ollama SDK expects arguments as dict objects, not JSON strings.
        """
        processed = []
        
        for msg in messages:
            msg_copy = msg.copy()
            
            # If message has tool_calls, convert arguments from JSON string to dict
            if "tool_calls" in msg_copy and msg_copy["tool_calls"]:
                tool_calls_copy = []
                for tc in msg_copy["tool_calls"]:
                    tc_copy = tc.copy()
                    if "function" in tc_copy and "arguments" in tc_copy["function"]:
                        arguments = tc_copy["function"]["arguments"]
                        # Convert JSON string to dict if necessary
                        if isinstance(arguments, str):
                            try:
                                tc_copy["function"]["arguments"] = json.loads(arguments)
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse tool_call arguments: {arguments}")
                                tc_copy["function"]["arguments"] = {}
                    tool_calls_copy.append(tc_copy)
                msg_copy["tool_calls"] = tool_calls_copy
            
            processed.append(msg_copy)
        
        return processed
    
    def _parse_response(self, response: Any, model: str) -> LLMResponse:
        """Parse Ollama response into our standard format."""
        message = response.get("message", {})
        
        # Extract content
        content = message.get("content", "")
        
        # Extract tool calls
        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                function = tc.get("function", {})
                arguments = function.get("arguments", {})
                
                # Ollama may return arguments as JSON string, need to parse it
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse arguments as JSON: {arguments}")
                        arguments = {}
                
                tool_calls.append(ToolCallRequest(
                    id=tc.get("id", ""),
                    name=function.get("name", ""),
                    arguments=arguments,
                ))
        
        # Extract usage information
        usage = {}
        
        # Ollama provides: prompt_eval_count (input tokens) and eval_count (output tokens)
        prompt_tokens = response.get("prompt_eval_count", 0)
        completion_tokens = response.get("eval_count", 0)
        
        if prompt_tokens or completion_tokens:
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
            logger.debug(f"Ollama usage: {usage}")
        else:
            # For local models that don't return token counts
            if self.is_cloud:
                logger.debug(f"Ollama cloud model '{model}': Token counting from metrics")
            else:
                logger.debug(f"Ollama local model '{model}': Token counting available from metrics")
        
        # Determine finish reason
        finish_reason = response.get("done_reason", "stop")
        if not response.get("done", True):
            finish_reason = "length"
        
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
