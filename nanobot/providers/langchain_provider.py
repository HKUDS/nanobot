"""LangChain provider implementation for multi-provider support."""

import os
import logging
import json
from typing import Any, Dict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool as lc_tool

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

logger = logging.getLogger(__name__)

class LangChainProvider(LLMProvider):
    """
    LLM provider using LangChain for multi-provider support.
    
    Supports OpenAI-compatible providers through ChatOpenAI.
    """
    
    def __init__(
        self, 
        api_key: str | None = None, 
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        provider_name: str | None = None
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.provider_name = provider_name
        
        # Known base URLs for popular providers
        # Includes variants for domestic (CN) and international endpoints
        self.known_bases = {
            # International / Official
            "deepseek": "https://api.deepseek.com",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4",
            "zai": "https://open.bigmodel.cn/api/paas/v4",
            "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "groq": "https://api.groq.com/openai/v1",
            "mistral": "https://api.mistral.ai/v1",
            "moonshot": "https://api.moonshot.cn/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "yi": "https://api.lingyiwanwu.com/v1",
            "01": "https://api.lingyiwanwu.com/v1",
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
            
            # Domestic (CN) variants - appending _cn suffix convention
            "deepseek_cn": "https://api.deepseek.com", # DeepSeek is CN based anyway
            "qwen_cn": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "yi_cn": "https://api.lingyiwanwu.com/v1",
            "moonshot_cn": "https://api.moonshot.cn/v1",
            "minimax": "https://api.minimax.chat/v1",
            "minimax_cn": "https://api.minimax.chat/v1",
            "baichuan": "https://api.baichuan-ai.com/v1",
            "baichuan_cn": "https://api.baichuan-ai.com/v1",
            "siliconflow": "https://api.siliconflow.cn/v1",
            "siliconflow_cn": "https://api.siliconflow.cn/v1",
        }
        
        # If api_base is missing, try to infer it
        if not self.api_base:
            if self.provider_name and self.provider_name in self.known_bases:
                self.api_base = self.known_bases[self.provider_name]
            elif "/" in self.default_model:
                prefix = self.default_model.split("/")[0].lower()
                if prefix in self.known_bases:
                    self.api_base = self.known_bases[prefix]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LangChain.
        """
        model = model or self.default_model
        
        # Prepare ChatOpenAI parameters
        # Most providers are OpenAI-compatible, so we use ChatOpenAI
        # but we need to handle model names and base URLs carefully
        
        resolved_model = self._resolve_model_name(model)
        logger.info(f"Calling LLM: model={resolved_model}, base_url={self.api_base}")
        
        chat_kwargs: Dict[str, Any] = {
            "model": resolved_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "api_key": self.api_key or "dummy", # Some local providers need non-empty key
            "request_timeout": 60.0, # Add explicit timeout
            "max_retries": 2,
        }
        
        if self.api_base:
            chat_kwargs["base_url"] = self.api_base
            
        # Initialize ChatOpenAI
        try:
            chat_model = ChatOpenAI(**chat_kwargs)
        except Exception as e:
            logger.error(f"Failed to init ChatOpenAI: {e}")
            raise e
        
        # Bind tools if provided
        if tools:
            # LangChain ChatOpenAI expects OpenAI-format tools directly
            chat_model = chat_model.bind_tools(tools)
            
        # Convert messages to LangChain format
        lc_messages = self._convert_messages(messages)
        
        try:
            # Execute invocation
            response = await chat_model.ainvoke(lc_messages)
            return self._parse_response(response)
        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
                finish_reason="error",
            )
            
    def _resolve_model_name(self, model: str) -> str:
        """Resolve the model name for the provider."""
        # Clean up model prefixes if necessary
        # Many providers (like vLLM, DeepSeek) work best with just the model name
        # if the base_url is set correctly.
        
        if "/" in model:
            # Check for specific prefixes that we know we should strip or modify
            prefix, suffix = model.split("/", 1)
        
            
            if self.api_base:
                # For vLLM, users often config "vllm/meta-llama/..."
                # If we strip "vllm/", we get "meta-llama/..." which is usually correct for vLLM
                if prefix == "vllm":
                    return suffix
                
                known_prefixes = list(self.known_bases.keys()) + ["zhipu", "zai"] # zai/zhipu might not be in keys if only values are used, but we added them. 
                # Actually, zai and zhipu are keys in known_bases now, so just using keys() is fine.
                
                if prefix in self.known_bases:
                    return suffix
                    
        return model

    def _convert_messages(self, messages: list[dict[str, Any]]) -> list[BaseMessage]:
        """Convert standard message dicts to LangChain BaseMessages."""
        lc_messages = []
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    # Convert OpenAI tool calls format back to LangChain format if needed
                    lc_tool_calls = []
                    for tc in tool_calls:
                        if "function" in tc:
                            # OpenAI format conversion
                            # OpenAI format: {"type": "function", "function": {"name": "...", "arguments": "..."}}
                            # LangChain format: {"name": "...", "args": {...}, "id": "..."}
                            try:
                                args = tc["function"]["arguments"]
                                if isinstance(args, str):
                                    args = json.loads(args)
                            except (json.JSONDecodeError, KeyError, TypeError):
                                args = {}
                                
                            lc_tool_calls.append({
                                "id": tc.get("id"),
                                "name": tc["function"].get("name"),
                                "args": args,
                                "type": "tool_call"
                            })
                        else:
                            # Already LangChain format or unknown
                            lc_tool_calls.append(tc)
                            
                    lc_messages.append(AIMessage(content=content or "", tool_calls=lc_tool_calls))
                else:
                    lc_messages.append(AIMessage(content=content or ""))
            elif role == "tool":
                # Tool response
                lc_messages.append(ToolMessage(
                    content=content,
                    tool_call_id=msg.get("tool_call_id")
                ))
                
        return lc_messages

    def _parse_response(self, message: BaseMessage) -> LLMResponse:
        """Parse LangChain AIMessage response into standard format."""
        content = str(message.content) if message.content else None
        
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(ToolCallRequest(
                    id=tc.get("id"),
                    name=tc.get("name"),
                    arguments=tc.get("args") or {},
                ))
        
        # Estimate usage if available (LangChain often puts it in response_metadata)
        usage = {}
        if hasattr(message, "response_metadata"):
            token_usage = message.response_metadata.get("token_usage", {})
            if token_usage:
                usage = {
                    "prompt_tokens": token_usage.get("prompt_tokens", 0),
                    "completion_tokens": token_usage.get("completion_tokens", 0),
                    "total_tokens": token_usage.get("total_tokens", 0),
                }
        
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason="stop", # LangChain often doesn't normalize this well across providers
            usage=usage,
        )
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
