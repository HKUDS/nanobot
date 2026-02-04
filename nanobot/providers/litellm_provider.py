"""LiteLLM provider implementation for multi-provider support."""

import os
from typing import Any

import litellm
from litellm import acompletion

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.
    
    Supports OpenRouter, Anthropic, OpenAI, Gemini, and many other providers through
    a unified interface.
    """
    
    def __init__(
        self, 
        api_key: str | None = None, 
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        litellm_settings: Any | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.allowed_openai_params: list[str] = []
        self.drop_params: bool | None = None
        
        # Detect OpenRouter by api_key prefix or explicit api_base
        self.is_openrouter = (
            (api_key and api_key.startswith("sk-or-")) or
            (api_base and "openrouter" in api_base)
        )

        # Detect Together AI by api_base or model prefix
        self.is_together = (
            (api_base and "together" in api_base) or
            default_model.startswith("together_ai/")
        )
        
        # Track if using custom endpoint (vLLM, etc.)
        self.is_vllm = bool(api_base) and not self.is_openrouter and not self.is_together

        # Load LiteLLM settings (optional)
        def _get_setting(name: str, default: Any) -> Any:
            if litellm_settings is None:
                return default
            if isinstance(litellm_settings, dict):
                return litellm_settings.get(name, default)
            return getattr(litellm_settings, name, default)

        allowed_params = _get_setting("allowed_openai_params", None)
        if isinstance(allowed_params, str):
            self.allowed_openai_params = [allowed_params]
        elif allowed_params:
            self.allowed_openai_params = list(allowed_params)

        drop_params_setting = _get_setting("drop_params", None)
        if drop_params_setting is not None:
            self.drop_params = bool(drop_params_setting)
        
        # Configure LiteLLM based on provider
        if api_key:
            if self.is_openrouter:
                # OpenRouter mode - set key
                os.environ["OPENROUTER_API_KEY"] = api_key
            elif self.is_together:
                # Together AI mode
                os.environ.setdefault("TOGETHERAI_API_KEY", api_key)
                os.environ.setdefault("TOGETHER_API_KEY", api_key)
            elif self.is_vllm:
                # vLLM/custom endpoint - uses OpenAI-compatible API
                os.environ["OPENAI_API_KEY"] = api_key
            elif "anthropic" in default_model:
                os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
            elif "openai" in default_model or "gpt" in default_model:
                os.environ.setdefault("OPENAI_API_KEY", api_key)
            elif "gemini" in default_model.lower():
                os.environ.setdefault("GEMINI_API_KEY", api_key)
            elif "zhipu" in default_model or "glm" in default_model or "zai" in default_model:
                os.environ.setdefault("ZHIPUAI_API_KEY", api_key)
        
        if api_base:
            litellm.api_base = api_base
        
        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True

        # Configure LiteLLM param handling
        if self.drop_params is not None:
            litellm.drop_params = self.drop_params
        elif self.allowed_openai_params:
            # Ensure allowed params aren't stripped by a previous global drop_params setting.
            litellm.drop_params = False
        elif self.is_together:
            # Together AI rejects tool params for many models; drop unless explicitly allowed.
            litellm.drop_params = True
    
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LiteLLM.
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'anthropic/claude-sonnet-4-5').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
        
        Returns:
            LLMResponse with content and/or tool calls.
        """
        model = model or self.default_model
        
        # For OpenRouter, prefix model name if not already prefixed
        if self.is_openrouter and not model.startswith("openrouter/"):
            model = f"openrouter/{model}"
        
        # For Zhipu/Z.ai, ensure prefix is present
        # Handle cases like "glm-4.7-flash" -> "zhipu/glm-4.7-flash"
        if ("glm" in model.lower() or "zhipu" in model.lower()) and not (
            model.startswith("zhipu/") or 
            model.startswith("zai/") or 
            model.startswith("openrouter/")
        ):
            model = f"zhipu/{model}"
        
        # For Together AI, ensure together_ai/ prefix if not already present
        if self.is_together and not model.startswith("together_ai/"):
            known_prefixes = {
                "openrouter",
                "anthropic",
                "openai",
                "gemini",
                "zhipu",
                "zai",
                "hosted_vllm",
                "together_ai",
            }
            provider_prefix = model.split("/", 1)[0]
            if provider_prefix not in known_prefixes:
                model = f"together_ai/{model}"

        # For vLLM, use hosted_vllm/ prefix per LiteLLM docs
        # Convert openai/ prefix to hosted_vllm/ if user specified it
        if self.is_vllm:
            model = f"hosted_vllm/{model}"
        
        # For Gemini, ensure gemini/ prefix if not already present
        if "gemini" in model.lower() and not model.startswith("gemini/"):
            model = f"gemini/{model}"
        
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        # Pass api_base directly for custom endpoints (vLLM, etc.)
        if self.api_base:
            kwargs["api_base"] = self.api_base
        
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.allowed_openai_params:
            kwargs["allowed_openai_params"] = self.allowed_openai_params
        
        try:
            response = await acompletion(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            # Return error as content for graceful handling
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
                finish_reason="error",
            )
    
    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse LiteLLM response into our standard format."""
        choice = response.choices[0]
        message = choice.message
        
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                # Parse arguments from JSON string if needed
                args = tc.function.arguments
                if isinstance(args, str):
                    import json
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                
                tool_calls.append(ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))
        elif getattr(message, "content", None):
            # Fallback: parse tool calls embedded in text (Together-style)
            parsed_calls = self._parse_tool_calls_from_content(message.content)
            if parsed_calls:
                tool_calls.extend(parsed_calls)
        
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        
        return LLMResponse(
            content=None if tool_calls else message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )

    def _parse_tool_calls_from_content(self, content: str) -> list[ToolCallRequest]:
        """Parse tool calls from raw content when provider doesn't return tool_calls."""
        import json
        import re

        pattern = re.compile(
            r"<\\|tool_call_begin\\|>\\s*([^\\s]+)\\s*<\\|tool_call_argument_begin\\|>\\s*(\\{.*?\\})\\s*<\\|tool_call_end\\|>",
            re.DOTALL,
        )

        name_map = {
            "execute_command": "exec",
            "list_dir": "list_dir",
            "read_file": "read_file",
            "write_file": "write_file",
            "edit_file": "edit_file",
            "web_search": "web_search",
            "web_fetch": "web_fetch",
        }

        tool_calls: list[ToolCallRequest] = []
        for idx, match in enumerate(pattern.findall(content), start=1):
            raw_name, raw_args = match
            # Drop indexes like functions.execute_command:2
            name_part = raw_name.split(":", 1)[0]
            if name_part.startswith("functions."):
                name_part = name_part[len("functions."):]
            name = name_map.get(name_part, name_part)

            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {"raw": raw_args}

            tool_calls.append(ToolCallRequest(
                id=f"synthetic_{idx}",
                name=name,
                arguments=args,
            ))

        # Also support simple JSON tool format: {"tool": "...", "args": {...}}
        for obj in self._extract_json_objects(content):
            if not isinstance(obj, dict):
                continue
            if "tool" not in obj or "args" not in obj:
                continue
            raw_name = str(obj.get("tool"))
            name = raw_name
            if raw_name.startswith("functions."):
                name = raw_name[len("functions."):]
            name = name_map.get(name, name)
            args = obj.get("args") if isinstance(obj.get("args"), dict) else {"raw": obj.get("args")}
            tool_calls.append(ToolCallRequest(
                id=f"synthetic_json_{len(tool_calls) + 1}",
                name=name,
                arguments=args,
            ))

        return tool_calls

    def _extract_json_objects(self, text: str) -> list[Any]:
        """Extract top-level JSON objects from text (best-effort)."""
        import json

        objs: list[Any] = []
        in_string = False
        escape = False
        depth = 0
        start = None
        for i, ch in enumerate(text):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            else:
                if ch == '"':
                    in_string = True
                    continue
                if ch == "{":
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == "}":
                    if depth > 0:
                        depth -= 1
                        if depth == 0 and start is not None:
                            snippet = text[start : i + 1]
                            try:
                                objs.append(json.loads(snippet))
                            except json.JSONDecodeError:
                                pass
                            start = None
        return objs
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
