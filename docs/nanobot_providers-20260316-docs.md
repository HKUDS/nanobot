# Project Documentation

- **Generated at:** 2026-03-16 23:11:10
- **Root Dir:** `nanobot/providers`
- **File Count:** 8
- **Total Size:** 65.20 KB
 claude 解读：

 *Thinking...*

> The user wants me to explain the meaning of this codebase in detail. The document is in Chinese (the TOC and summary sections use Chinese), so I should respond in Chinese.
> 
> Let me analyze the entire codebase systematically.
> 
> This is a Python project called "nanobot" — specifically its `providers` module. It's an LLM (Large Language Model) provider abstraction layer that allows the application to interact with multiple AI model providers through a unified interface.
> 
> Let me break down each file and its role.

# Nanobot Providers 模块详细解读

这是一个 **LLM（大语言模型）多供应商抽象层**，其核心目标是：让上层业务代码通过统一的接口调用不同的 AI 模型服务（Anthropic、OpenAI、Azure、DeepSeek、Gemini、国内厂商等），而不必关心每家 API 的差异。下面逐文件、逐层解读。

---

## 整体架构

整个模块采用经典的**策略模式 + 注册表**设计。结构可以概括为三层：

第一层是 `base.py`，定义抽象基类 `LLMProvider` 和统一的数据结构（`LLMResponse`、`ToolCallRequest`），所有具体供应商都必须实现 `chat()` 方法。

第二层是具体的 Provider 实现，包括 `litellm_provider.py`（通过 LiteLLM 库路由到数十家供应商）、`azure_openai_provider.py`（直连 Azure OpenAI）、`openai_codex_provider.py`（通过 OAuth 调用 OpenAI Codex）、`custom_provider.py`（直连任意 OpenAI 兼容端点）。

第三层是 `registry.py`，作为供应商元数据的"单一真相源"，驱动模型名解析、环境变量配置、网关检测等逻辑。

`transcription.py` 是一个独立的语音转文字模块，不属于 LLM 对话链路。

---

## 逐文件详解

### 1. `base.py` — 抽象基类与公共逻辑

这是整个模块的骨架。

**`ToolCallRequest`** 数据类表示 LLM 返回的"工具调用请求"。当模型判断需要调用外部工具（如搜索、执行代码、查数据库）时，它不会直接给出答案，而是返回一个结构化的调用指令：包含调用 ID、函数名、参数。`to_openai_tool_call()` 方法将其序列化为 OpenAI 格式的字典，以便回传到对话历史中。额外的 `provider_specific_fields` 字段用于保留某些供应商的私有元数据（比如 Anthropic 的特殊字段），确保在多轮对话中不丢失信息。

**`LLMResponse`** 数据类是所有供应商返回结果的统一封装。`content` 是模型的文本回复；`tool_calls` 是工具调用列表；`finish_reason` 标识结束原因（正常结束 "stop"、达到长度限制 "length"、需要调用工具 "tool_calls"、出错 "error"）；`usage` 记录 token 消耗；`reasoning_content` 和 `thinking_blocks` 分别对应 DeepSeek-R1/Kimi 的推理链和 Anthropic 的扩展思考块——这些是各家"思维链可见"功能的产物。

**`GenerationSettings`** 是一个冻结的数据类，存储默认生成参数（温度、最大 token 数、推理力度）。它被挂在 Provider 实例上，这样调用方不必在每次调用时都传递这些参数。

**`LLMProvider` 抽象基类**定义了所有供应商必须实现的接口。其中有几个关键设计：

`_sanitize_empty_content()` 是一个静态方法，解决一个实际的工程痛点：当 MCP 工具返回空内容时，消息的 `content` 可能是空字符串或包含空文本块的列表，而大多数供应商的 API 会因此返回 400 错误。这个方法将空内容替换为 `"(empty)"` 或 `None`（对于带有 tool_calls 的 assistant 消息，内容应为 `None` 而非空字符串，因为 OpenAI 的 API 规范要求如此）。

`_sanitize_request_messages()` 过滤消息中的非标准字段。不同供应商只接受特定的 key（比如 Azure 不认识 `thinking_blocks`，Anthropic 不认识某些 OpenAI 扩展字段），所以在发送前必须清理。

`chat_with_retry()` 实现了带重试的调用逻辑。它使用 `_SENTINEL` 哨兵对象（而非 `None`）作为默认值，这样就能区分"调用方没传这个参数"和"调用方显式传了 None"。未传的参数从 `self.generation` 取默认值。重试策略是：遇到瞬态错误（429 限流、5xx 服务端错误、超时、连接失败等）时，按 1s、2s、4s 的延迟重试三次，最后再做一次最终尝试。非瞬态错误（如 400 参数错误）直接返回，不浪费重试。

---

### 2. `registry.py` — 供应商注册表

这是整个系统最重要的配置中心，采用"数据驱动"而非"代码驱动"的设计理念。

**`ProviderSpec`** 数据类用一个冻结的结构描述一个供应商的所有元数据。每个字段的含义：

`name` 是配置文件中的字段名（如 `"dashscope"`）。`keywords` 是模型名中的关键词，用于自动匹配供应商（如模型名含 `"qwen"` 就匹配 DashScope）。`env_key` 是 LiteLLM 需要的环境变量名。`litellm_prefix` 是 LiteLLM 路由所需的模型前缀（如 DeepSeek 的模型 `deepseek-chat` 必须变成 `deepseek/deepseek-chat` 才能被 LiteLLM 正确路由）。`skip_prefixes` 防止双重前缀（如模型已经是 `deepseek/xxx` 就不再加 `deepseek/`）。

`is_gateway` 标识"网关型"供应商——它们不提供自己的模型，而是转发请求到其他供应商（如 OpenRouter 可以路由到 Anthropic、OpenAI 等任何模型）。网关的检测不依赖模型名，而是依赖 API key 前缀（如 OpenRouter 的 key 以 `"sk-or-"` 开头）或 API base URL 中的关键词（如 URL 含 `"aihubmix"`）。

`strip_model_prefix` 是网关特有的设置。AiHubMix 是 OpenAI 兼容接口，不理解 `"anthropic/claude-3"` 这样的模型名，所以需要先去掉前缀变成 `"claude-3"`，再加上 `"openai/"` 前缀让 LiteLLM 走 OpenAI 兼容协议。

`env_extras` 处理某些供应商需要多个环境变量的情况。比如 Moonshot 需要 `MOONSHOT_API_BASE`，Zhipu 需要同时设置 `ZAI_API_KEY` 和 `ZHIPUAI_API_KEY`。值中的 `{api_key}` 和 `{api_base}` 占位符会在运行时被替换。

`model_overrides` 处理特定模型的参数覆盖。比如 Kimi K2.5 的 API 强制要求 temperature ≥ 1.0，所以注册表中配置了 `("kimi-k2.5", {"temperature": 1.0})`。

`is_direct` 标识"直连型"供应商（CustomProvider 和 AzureOpenAIProvider），它们完全绕过 LiteLLM，自己实现 HTTP 调用。

`is_oauth` 标识使用 OAuth 认证而非 API key 的供应商（OpenAI Codex 和 GitHub Copilot）。

`supports_prompt_caching` 标识是否支持提示缓存（Anthropic 和 OpenRouter 支持），启用后会在系统消息和工具列表上注入 `cache_control` 标记，让供应商缓存这些不常变化的内容，降低延迟和成本。

**查找函数**有三个：`find_by_model()` 根据模型名中的关键词匹配标准供应商（跳过网关和本地部署）；`find_gateway()` 按优先级检测网关——先看配置文件中的 provider_name，再看 API key 前缀，最后看 API base URL；`find_by_name()` 按名称精确查找。

注册表的顺序很重要：网关排在前面（因为网关可以路由任何模型，需要优先被检测到），标准供应商按常用度排列，本地部署和辅助供应商排在最后。

---

### 3. `litellm_provider.py` — 主力供应商实现

这是最复杂也最常用的 Provider，通过 LiteLLM 开源库支持数十家供应商。

**构造函数**中的 `_setup_env()` 根据注册表配置环境变量。LiteLLM 依赖环境变量来定位各家 API（如 `ANTHROPIC_API_KEY`、`DEEPSEEK_API_KEY`）。网关模式下会覆盖已有环境变量（因为网关的 key 优先级最高），标准模式下只设置默认值（`os.environ.setdefault`），不覆盖用户已有的配置。

**`_resolve_model()`** 是模型名解析的核心。如果当前是网关模式，可能需要先去掉供应商前缀（`strip_model_prefix`），再加上网关的 LiteLLM 前缀。标准模式下则根据注册表给模型加上正确的前缀。`_canonicalize_explicit_prefix()` 处理用户显式写了供应商前缀的情况（如 `"github-copilot/model"`），将其规范化。

**`_apply_cache_control()`** 为支持提示缓存的供应商注入 `cache_control` 标记。具体做法是将系统消息的内容包装成带 `{"cache_control": {"type": "ephemeral"}}` 的内容块，并在工具列表的最后一个工具上也加上同样的标记。"ephemeral" 类型表示这是临时缓存，供应商自行决定缓存时长。

**`_sanitize_messages()`** 在基类的基础上增加了工具调用 ID 的标准化处理。某些供应商（如 Mistral）对 tool_call_id 的格式有严格要求（必须是 9 位字母数字），而 OpenAI 返回的 ID 通常是 `"call_xxxxxxxx"` 这样的长字符串。所以这里用 SHA1 哈希截取前 9 位来标准化，并且维护一个 `id_map` 字典确保 assistant 消息中的 tool_calls[].id 和后续 tool 消息中的 tool_call_id 保持一致——否则严格的供应商会因为链接断裂而拒绝请求。

**`chat()`** 方法组装请求参数并调用 LiteLLM 的 `acompletion()`。几个值得注意的细节：`max_tokens` 被钳制为最小 1（因为 LiteLLM 不接受 0 或负数）；`litellm.drop_params = True` 让 LiteLLM 自动丢弃目标供应商不支持的参数（比如 GPT-5 可能不支持某些旧参数）；如果启用了 LangSmith（通过环境变量 `LANGSMITH_API_KEY`），会注入 LangSmith 回调用于追踪和监控。

**`_parse_response()`** 处理 LiteLLM 返回的响应。一个有趣的设计是它会合并多个 choices——某些供应商（如 GitHub Copilot）可能将文本内容和工具调用分散在不同的 choice 中返回，这里把它们合并起来确保工具调用不会丢失。工具调用的 ID 使用 `_short_tool_id()` 生成新的 9 位随机 ID，而不是沿用供应商返回的 ID，这是为了跨供应商兼容性。

---

### 4. `azure_openai_provider.py` — Azure OpenAI 直连

Azure OpenAI 的 API 与标准 OpenAI API 有几个关键差异，所以单独实现而不走 LiteLLM。

URL 格式不同：Azure 使用 `https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version=2024-10-21`，其中模型名实际上是部署名。

认证方式不同：Azure 使用 `api-key` 请求头而非 `Authorization: Bearer` 头。

参数名不同：Azure API 2024-10-21 版本使用 `max_completion_tokens` 代替 `max_tokens`。

**`_supports_temperature()`** 判断部署是否支持温度参数。GPT-5、O1、O3、O4 系列模型（以及使用了 reasoning_effort 的请求）不支持设置温度，必须跳过。

请求头中的 `x-session-affinity` 是一个 UUID，用于提示 Azure 的负载均衡器将同一会话的请求路由到同一后端节点，提高缓存命中率。

响应解析中，`reasoning_content` 字段对应 Azure 上部署的推理模型（如 O1）返回的推理过程。

---

### 5. `openai_codex_provider.py` — OpenAI Codex（OAuth SSE）

这个 Provider 调用 ChatGPT 的 Codex API，使用 OAuth 认证（而非 API key），通过 SSE（Server-Sent Events）流式接收响应。

**`_convert_messages()`** 将标准的 OpenAI chat 格式消息转换为 Codex 的 Responses API 格式。主要差异在于：用户消息的文本类型是 `"input_text"` 而非 `"text"`；助手消息的文本类型是 `"output_text"`；工具调用使用 `"function_call"` 类型而非嵌入在 message 中的 `tool_calls` 数组；工具返回使用 `"function_call_output"` 类型。

**`_split_tool_call_id()`** 处理一个巧妙的编码：Codex 的工具调用有两个 ID（`call_id` 用于关联调用和返回，`item_id` 用于标识输出项），这个 Provider 用 `|` 分隔符将两者编码在一个字符串中（如 `"call_123|fc_456"`），这样在多轮对话中传递时不会丢失任何 ID。

**`_prompt_cache_key()`** 对整个消息历史做 SHA256 哈希，作为 Codex 的提示缓存键。如果两次请求的消息完全相同，Codex 可以复用之前的计算结果。

**SSE 流处理**是这个文件最复杂的部分。`_iter_sse()` 解析 HTTP 响应的 SSE 流——SSE 协议以空行分隔事件，每个事件以 `data:` 开头。`_consume_sse()` 根据事件类型组装最终结果：`response.output_text.delta` 事件累积文本内容；`response.output_item.added` 和 `response.function_call_arguments.delta` 事件逐步构建工具调用；`response.output_item.done` 事件确认工具调用完成并解析参数 JSON。

SSL 证书验证失败时会自动降级为不验证（`verify=False`），并记录警告——这是为了在某些企业网络环境中仍能工作。

---

### 6. `custom_provider.py` — 通用 OpenAI 兼容端点

这是最简单的 Provider，直接使用 OpenAI 官方 Python SDK（`AsyncOpenAI`）连接任意 OpenAI 兼容的服务端点。它不走 LiteLLM，适用于用户自建的推理服务（如 vLLM、TGI、LocalAI 等）。

构造函数中创建一个持久的 `AsyncOpenAI` 客户端实例（带 `x-session-affinity` 头），整个 Provider 生命周期内复用，避免频繁建立连接。

---

### 7. `transcription.py` — 语音转文字

独立于 LLM 对话链路，使用 Groq 的 Whisper API 做语音转写。Groq 以极快的推理速度著称，并提供慷慨的免费额度。实现很直接：读取音频文件，以 multipart/form-data 形式 POST 到 Groq API，返回转写文本。

---

### 8. `__init__.py` — 模块导出

只导出核心类：`LLMProvider`（基类）、`LLMResponse`（响应）、`LiteLLMProvider`（主力）、`OpenAICodexProvider`（Codex）、`AzureOpenAIProvider`（Azure）。注意 `CustomProvider` 没有在这里导出，可能是因为它通过注册表的 `is_direct` 标志在别处动态加载。

---

## 关键设计思想总结

**数据驱动的供应商管理**：新增供应商只需在 `registry.py` 的 `PROVIDERS` 元组中添加一个 `ProviderSpec`，无需修改任何 if-elif 链。注册表驱动了环境变量设置、模型名前缀解析、网关检测、参数覆盖、缓存控制等所有逻辑。

**防御性消息清理**：从空内容处理、非标准字段过滤到工具调用 ID 标准化，多层清理确保请求在任何供应商都不会因格式问题被拒绝。这反映了作者在实际对接多家 API 时踩过的大量坑。

**优雅降级**：错误不会抛异常，而是封装在 `LLMResponse(finish_reason="error")` 中返回，让上层业务逻辑统一处理。重试机制只针对瞬态错误，避免在参数错误上浪费时间。

**缓存友好**：session affinity 头、prompt cache key、cache_control 注入，多处设计都在优化缓存命中率，降低延迟和成本。

<a name="toc"></a>
## 📂 扫描目录
- [__init__.py](#📄-__init__py) (8 lines, 0.40 KB)
- [azure_openai_provider.py](#📄-azure_openai_providerpy) (213 lines, 7.59 KB)
- [base.py](#📄-basepy) (270 lines, 9.01 KB)
- [custom_provider.py](#📄-custom_providerpy) (62 lines, 2.56 KB)
- [litellm_provider.py](#📄-litellm_providerpy) (355 lines, 13.94 KB)
- [openai_codex_provider.py](#📄-openai_codex_providerpy) (317 lines, 11.63 KB)
- [registry.py](#📄-registrypy) (523 lines, 18.21 KB)
- [transcription.py](#📄-transcriptionpy) (64 lines, 1.85 KB)

---

## 📄 __init__.py

````python
"""LLM provider abstraction module."""

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.openai_codex_provider import OpenAICodexProvider
from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

__all__ = ["LLMProvider", "LLMResponse", "LiteLLMProvider", "OpenAICodexProvider", "AzureOpenAIProvider"]

````

[⬆ 回到目录](#toc)

## 📄 azure_openai_provider.py

````python
"""Azure OpenAI provider implementation with API version 2024-10-21."""

from __future__ import annotations

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
    - Uses api-key header instead of Authorization Bearer
    - Uses max_completion_tokens instead of max_tokens
    - Direct HTTP calls, bypasses LiteLLM
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        default_model: str = "gpt-5.2-chat",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.api_version = "2024-10-21"
        
        # Validate required parameters
        if not api_key:
            raise ValueError("Azure OpenAI api_key is required")
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

    def _build_headers(self) -> dict[str, str]:
        """Build headers for Azure OpenAI API with api-key header."""
        return {
            "Content-Type": "application/json",
            "api-key": self.api_key,  # Azure OpenAI uses api-key header, not Authorization
            "x-session-affinity": uuid.uuid4().hex,  # For cache locality
        }

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
        headers = self._build_headers()
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
````

[⬆ 回到目录](#toc)

## 📄 base.py

````python
"""Base LLM provider interface."""

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class ToolCallRequest:
    """A tool call request from the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]
    provider_specific_fields: dict[str, Any] | None = None
    function_provider_specific_fields: dict[str, Any] | None = None

    def to_openai_tool_call(self) -> dict[str, Any]:
        """Serialize to an OpenAI-style tool_call payload."""
        tool_call = {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }
        if self.provider_specific_fields:
            tool_call["provider_specific_fields"] = self.provider_specific_fields
        if self.function_provider_specific_fields:
            tool_call["function"]["provider_specific_fields"] = self.function_provider_specific_fields
        return tool_call


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    reasoning_content: str | None = None  # Kimi, DeepSeek-R1 etc.
    thinking_blocks: list[dict] | None = None  # Anthropic extended thinking
    
    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0


@dataclass(frozen=True)
class GenerationSettings:
    """Default generation parameters for LLM calls.

    Stored on the provider so every call site inherits the same defaults
    without having to pass temperature / max_tokens / reasoning_effort
    through every layer.  Individual call sites can still override by
    passing explicit keyword arguments to chat() / chat_with_retry().
    """

    temperature: float = 0.7
    max_tokens: int = 4096
    reasoning_effort: str | None = None


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    Implementations should handle the specifics of each provider's API
    while maintaining a consistent interface.
    """

    _CHAT_RETRY_DELAYS = (1, 2, 4)
    _TRANSIENT_ERROR_MARKERS = (
        "429",
        "rate limit",
        "500",
        "502",
        "503",
        "504",
        "overloaded",
        "timeout",
        "timed out",
        "connection",
        "server error",
        "temporarily unavailable",
    )

    _SENTINEL = object()

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base
        self.generation: GenerationSettings = GenerationSettings()

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace empty text content that causes provider 400 errors.

        Empty content can appear when MCP tools return nothing. Most providers
        reject empty-string content or empty text blocks in list content.
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")

            if isinstance(content, str) and not content:
                clean = dict(msg)
                clean["content"] = None if (msg.get("role") == "assistant" and msg.get("tool_calls")) else "(empty)"
                result.append(clean)
                continue

            if isinstance(content, list):
                filtered = [
                    item for item in content
                    if not (
                        isinstance(item, dict)
                        and item.get("type") in ("text", "input_text", "output_text")
                        and not item.get("text")
                    )
                ]
                if len(filtered) != len(content):
                    clean = dict(msg)
                    if filtered:
                        clean["content"] = filtered
                    elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                        clean["content"] = None
                    else:
                        clean["content"] = "(empty)"
                    result.append(clean)
                    continue

            if isinstance(content, dict):
                clean = dict(msg)
                clean["content"] = [content]
                result.append(clean)
                continue

            result.append(msg)
        return result

    @staticmethod
    def _sanitize_request_messages(
        messages: list[dict[str, Any]],
        allowed_keys: frozenset[str],
    ) -> list[dict[str, Any]]:
        """Keep only provider-safe message keys and normalize assistant content."""
        sanitized = []
        for msg in messages:
            clean = {k: v for k, v in msg.items() if k in allowed_keys}
            if clean.get("role") == "assistant" and "content" not in clean:
                clean["content"] = None
            sanitized.append(clean)
        return sanitized

    @abstractmethod
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
        Send a chat completion request.
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions.
            model: Model identifier (provider-specific).
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            tool_choice: Tool selection strategy ("auto", "required", or specific tool dict).
        
        Returns:
            LLMResponse with content and/or tool calls.
        """
        pass

    @classmethod
    def _is_transient_error(cls, content: str | None) -> bool:
        err = (content or "").lower()
        return any(marker in err for marker in cls._TRANSIENT_ERROR_MARKERS)

    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: object = _SENTINEL,
        temperature: object = _SENTINEL,
        reasoning_effort: object = _SENTINEL,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Call chat() with retry on transient provider failures.

        Parameters default to ``self.generation`` when not explicitly passed,
        so callers no longer need to thread temperature / max_tokens /
        reasoning_effort through every layer.
        """
        if max_tokens is self._SENTINEL:
            max_tokens = self.generation.max_tokens
        if temperature is self._SENTINEL:
            temperature = self.generation.temperature
        if reasoning_effort is self._SENTINEL:
            reasoning_effort = self.generation.reasoning_effort

        for attempt, delay in enumerate(self._CHAT_RETRY_DELAYS, start=1):
            try:
                response = await self.chat(
                    messages=messages,
                    tools=tools,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    tool_choice=tool_choice,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                response = LLMResponse(
                    content=f"Error calling LLM: {exc}",
                    finish_reason="error",
                )

            if response.finish_reason != "error":
                return response
            if not self._is_transient_error(response.content):
                return response

            err = (response.content or "").lower()
            logger.warning(
                "LLM transient error (attempt {}/{}), retrying in {}s: {}",
                attempt,
                len(self._CHAT_RETRY_DELAYS),
                delay,
                err[:120],
            )
            await asyncio.sleep(delay)

        try:
            return await self.chat(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return LLMResponse(
                content=f"Error calling LLM: {exc}",
                finish_reason="error",
            )

    @abstractmethod
    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        pass

````

[⬆ 回到目录](#toc)

## 📄 custom_provider.py

````python
"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

import uuid
from typing import Any

import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CustomProvider(LLMProvider):

    def __init__(self, api_key: str = "no-key", api_base: str = "http://localhost:8000/v1", default_model: str = "default"):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        # Keep affinity stable for this provider instance to improve backend cache locality.
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers={"x-session-affinity": uuid.uuid4().hex},
        )

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
                   reasoning_effort: str | None = None,
                   tool_choice: str | dict[str, Any] | None = None) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs.update(tools=tools, tool_choice=tool_choice or "auto")
        try:
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    def _parse(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message
        tool_calls = [
            ToolCallRequest(id=tc.id, name=tc.function.name,
                            arguments=json_repair.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments)
            for tc in (msg.tool_calls or [])
        ]
        u = response.usage
        return LLMResponse(
            content=msg.content, tool_calls=tool_calls, finish_reason=choice.finish_reason or "stop",
            usage={"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "total_tokens": u.total_tokens} if u else {},
            reasoning_content=getattr(msg, "reasoning_content", None) or None,
        )

    def get_default_model(self) -> str:
        return self.default_model


````

[⬆ 回到目录](#toc)

## 📄 litellm_provider.py

````python
"""LiteLLM provider implementation for multi-provider support."""

import hashlib
import os
import secrets
import string
from typing import Any

import json_repair
import litellm
from litellm import acompletion
from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.registry import find_by_model, find_gateway

# Standard chat-completion message keys.
_ALLOWED_MSG_KEYS = frozenset({"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content"})
_ANTHROPIC_EXTRA_KEYS = frozenset({"thinking_blocks"})
_ALNUM = string.ascii_letters + string.digits

def _short_tool_id() -> str:
    """Generate a 9-char alphanumeric ID compatible with all providers (incl. Mistral)."""
    return "".join(secrets.choice(_ALNUM) for _ in range(9))


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.
    
    Supports OpenRouter, Anthropic, OpenAI, Gemini, MiniMax, and many other providers through
    a unified interface.  Provider-specific logic is driven by the registry
    (see providers/registry.py) — no if-elif chains needed here.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}

        # Detect gateway / local deployment.
        # provider_name (from config key) is the primary signal;
        # api_key / api_base are fallback for auto-detection.
        self._gateway = find_gateway(provider_name, api_key, api_base)

        # Configure environment variables
        if api_key:
            self._setup_env(api_key, api_base, default_model)

        if api_base:
            litellm.api_base = api_base

        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True
        # Drop unsupported parameters for providers (e.g., gpt-5 rejects some params)
        litellm.drop_params = True

        self._langsmith_enabled = bool(os.getenv("LANGSMITH_API_KEY"))

    def _setup_env(self, api_key: str, api_base: str | None, model: str) -> None:
        """Set environment variables based on detected provider."""
        spec = self._gateway or find_by_model(model)
        if not spec:
            return
        if not spec.env_key:
            # OAuth/provider-only specs (for example: openai_codex)
            return

        # Gateway/local overrides existing env; standard provider doesn't
        if self._gateway:
            os.environ[spec.env_key] = api_key
        else:
            os.environ.setdefault(spec.env_key, api_key)

        # Resolve env_extras placeholders:
        #   {api_key}  → user's API key
        #   {api_base} → user's api_base, falling back to spec.default_api_base
        effective_base = api_base or spec.default_api_base
        for env_name, env_val in spec.env_extras:
            resolved = env_val.replace("{api_key}", api_key)
            resolved = resolved.replace("{api_base}", effective_base)
            os.environ.setdefault(env_name, resolved)

    def _resolve_model(self, model: str) -> str:
        """Resolve model name by applying provider/gateway prefixes."""
        if self._gateway:
            prefix = self._gateway.litellm_prefix
            if self._gateway.strip_model_prefix:
                model = model.split("/")[-1]
            if prefix:
                model = f"{prefix}/{model}"
            return model

        # Standard mode: auto-prefix for known providers
        spec = find_by_model(model)
        if spec and spec.litellm_prefix:
            model = self._canonicalize_explicit_prefix(model, spec.name, spec.litellm_prefix)
            if not any(model.startswith(s) for s in spec.skip_prefixes):
                model = f"{spec.litellm_prefix}/{model}"

        return model

    @staticmethod
    def _canonicalize_explicit_prefix(model: str, spec_name: str, canonical_prefix: str) -> str:
        """Normalize explicit provider prefixes like `github-copilot/...`."""
        if "/" not in model:
            return model
        prefix, remainder = model.split("/", 1)
        if prefix.lower().replace("-", "_") != spec_name:
            return model
        return f"{canonical_prefix}/{remainder}"

    def _supports_cache_control(self, model: str) -> bool:
        """Return True when the provider supports cache_control on content blocks."""
        if self._gateway is not None:
            return self._gateway.supports_prompt_caching
        spec = find_by_model(model)
        return spec is not None and spec.supports_prompt_caching

    def _apply_cache_control(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Return copies of messages and tools with cache_control injected."""
        new_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg["content"]
                if isinstance(content, str):
                    new_content = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                else:
                    new_content = list(content)
                    new_content[-1] = {**new_content[-1], "cache_control": {"type": "ephemeral"}}
                new_messages.append({**msg, "content": new_content})
            else:
                new_messages.append(msg)

        new_tools = tools
        if tools:
            new_tools = list(tools)
            new_tools[-1] = {**new_tools[-1], "cache_control": {"type": "ephemeral"}}

        return new_messages, new_tools

    def _apply_model_overrides(self, model: str, kwargs: dict[str, Any]) -> None:
        """Apply model-specific parameter overrides from the registry."""
        model_lower = model.lower()
        spec = find_by_model(model)
        if spec:
            for pattern, overrides in spec.model_overrides:
                if pattern in model_lower:
                    kwargs.update(overrides)
                    return

    @staticmethod
    def _extra_msg_keys(original_model: str, resolved_model: str) -> frozenset[str]:
        """Return provider-specific extra keys to preserve in request messages."""
        spec = find_by_model(original_model) or find_by_model(resolved_model)
        if (spec and spec.name == "anthropic") or "claude" in original_model.lower() or resolved_model.startswith("anthropic/"):
            return _ANTHROPIC_EXTRA_KEYS
        return frozenset()

    @staticmethod
    def _normalize_tool_call_id(tool_call_id: Any) -> Any:
        """Normalize tool_call_id to a provider-safe 9-char alphanumeric form."""
        if not isinstance(tool_call_id, str):
            return tool_call_id
        if len(tool_call_id) == 9 and tool_call_id.isalnum():
            return tool_call_id
        return hashlib.sha1(tool_call_id.encode()).hexdigest()[:9]

    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]], extra_keys: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
        """Strip non-standard keys and ensure assistant messages have a content key."""
        allowed = _ALLOWED_MSG_KEYS | extra_keys
        sanitized = LLMProvider._sanitize_request_messages(messages, allowed)
        id_map: dict[str, str] = {}

        def map_id(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            return id_map.setdefault(value, LiteLLMProvider._normalize_tool_call_id(value))

        for clean in sanitized:
            # Keep assistant tool_calls[].id and tool tool_call_id in sync after
            # shortening, otherwise strict providers reject the broken linkage.
            if isinstance(clean.get("tool_calls"), list):
                normalized_tool_calls = []
                for tc in clean["tool_calls"]:
                    if not isinstance(tc, dict):
                        normalized_tool_calls.append(tc)
                        continue
                    tc_clean = dict(tc)
                    tc_clean["id"] = map_id(tc_clean.get("id"))
                    normalized_tool_calls.append(tc_clean)
                clean["tool_calls"] = normalized_tool_calls

            if "tool_call_id" in clean and clean["tool_call_id"]:
                clean["tool_call_id"] = map_id(clean["tool_call_id"])
        return sanitized

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
        original_model = model or self.default_model
        model = self._resolve_model(original_model)
        extra_msg_keys = self._extra_msg_keys(original_model, model)

        if self._supports_cache_control(original_model):
            messages, tools = self._apply_cache_control(messages, tools)

        # Clamp max_tokens to at least 1 — negative or zero values cause
        # LiteLLM to reject the request with "max_tokens must be at least 1".
        max_tokens = max(1, max_tokens)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._sanitize_messages(self._sanitize_empty_content(messages), extra_keys=extra_msg_keys),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if self._gateway:
            kwargs.update(self._gateway.litellm_kwargs)

        # Apply model-specific overrides (e.g. kimi-k2.5 temperature)
        self._apply_model_overrides(model, kwargs)

        if self._langsmith_enabled:
            kwargs.setdefault("callbacks", []).append("langsmith")

        # Pass api_key directly — more reliable than env vars alone
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # Pass api_base for custom endpoints
        if self.api_base:
            kwargs["api_base"] = self.api_base

        # Pass extra headers (e.g. APP-Code for AiHubMix)
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers
        
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
            kwargs["drop_params"] = True
        
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

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
        content = message.content
        finish_reason = choice.finish_reason

        # Some providers (e.g. GitHub Copilot) split content and tool_calls
        # across multiple choices. Merge them so tool_calls are not lost.
        raw_tool_calls = []
        for ch in response.choices:
            msg = ch.message
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                raw_tool_calls.extend(msg.tool_calls)
                if ch.finish_reason in ("tool_calls", "stop"):
                    finish_reason = ch.finish_reason
            if not content and msg.content:
                content = msg.content

        if len(response.choices) > 1:
            logger.debug("LiteLLM response has {} choices, merged {} tool_calls",
                         len(response.choices), len(raw_tool_calls))

        tool_calls = []
        for tc in raw_tool_calls:
            # Parse arguments from JSON string if needed
            args = tc.function.arguments
            if isinstance(args, str):
                args = json_repair.loads(args)

            provider_specific_fields = getattr(tc, "provider_specific_fields", None) or None
            function_provider_specific_fields = (
                getattr(tc.function, "provider_specific_fields", None) or None
            )

            tool_calls.append(ToolCallRequest(
                id=_short_tool_id(),
                name=tc.function.name,
                arguments=args,
                provider_specific_fields=provider_specific_fields,
                function_provider_specific_fields=function_provider_specific_fields,
            ))

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        reasoning_content = getattr(message, "reasoning_content", None) or None
        thinking_blocks = getattr(message, "thinking_blocks", None) or None

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            usage=usage,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model

````

[⬆ 回到目录](#toc)

## 📄 openai_codex_provider.py

````python
"""OpenAI Codex Responses Provider."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, AsyncGenerator

import httpx
from loguru import logger
from oauth_cli_kit import get_token as get_codex_token

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

DEFAULT_CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_ORIGINATOR = "nanobot"


class OpenAICodexProvider(LLMProvider):
    """Use Codex OAuth to call the Responses API."""

    def __init__(self, default_model: str = "openai-codex/gpt-5.1-codex"):
        super().__init__(api_key=None, api_base=None)
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
        model = model or self.default_model
        system_prompt, input_items = _convert_messages(messages)

        token = await asyncio.to_thread(get_codex_token)
        headers = _build_headers(token.account_id, token.access)

        body: dict[str, Any] = {
            "model": _strip_model_prefix(model),
            "store": False,
            "stream": True,
            "instructions": system_prompt,
            "input": input_items,
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": _prompt_cache_key(messages),
            "tool_choice": tool_choice or "auto",
            "parallel_tool_calls": True,
        }

        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}

        if tools:
            body["tools"] = _convert_tools(tools)

        url = DEFAULT_CODEX_URL

        try:
            try:
                content, tool_calls, finish_reason = await _request_codex(url, headers, body, verify=True)
            except Exception as e:
                if "CERTIFICATE_VERIFY_FAILED" not in str(e):
                    raise
                logger.warning("SSL certificate verification failed for Codex API; retrying with verify=False")
                content, tool_calls, finish_reason = await _request_codex(url, headers, body, verify=False)
            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
            )
        except Exception as e:
            return LLMResponse(
                content=f"Error calling Codex: {str(e)}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        return self.default_model


def _strip_model_prefix(model: str) -> str:
    if model.startswith("openai-codex/") or model.startswith("openai_codex/"):
        return model.split("/", 1)[1]
    return model


def _build_headers(account_id: str, token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": DEFAULT_ORIGINATOR,
        "User-Agent": "nanobot (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }


async def _request_codex(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    verify: bool,
) -> tuple[str, list[ToolCallRequest], str]:
    async with httpx.AsyncClient(timeout=60.0, verify=verify) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                text = await response.aread()
                raise RuntimeError(_friendly_error(response.status_code, text.decode("utf-8", "ignore")))
            return await _consume_sse(response)


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI function-calling schema to Codex flat format."""
    converted: list[dict[str, Any]] = []
    for tool in tools:
        fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
        name = fn.get("name")
        if not name:
            continue
        params = fn.get("parameters") or {}
        converted.append({
            "type": "function",
            "name": name,
            "description": fn.get("description") or "",
            "parameters": params if isinstance(params, dict) else {},
        })
    return converted


def _convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_prompt = ""
    input_items: list[dict[str, Any]] = []

    for idx, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            system_prompt = content if isinstance(content, str) else ""
            continue

        if role == "user":
            input_items.append(_convert_user_message(content))
            continue

        if role == "assistant":
            # Handle text first.
            if isinstance(content, str) and content:
                input_items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                        "status": "completed",
                        "id": f"msg_{idx}",
                    }
                )
            # Then handle tool calls.
            for tool_call in msg.get("tool_calls", []) or []:
                fn = tool_call.get("function") or {}
                call_id, item_id = _split_tool_call_id(tool_call.get("id"))
                call_id = call_id or f"call_{idx}"
                item_id = item_id or f"fc_{idx}"
                input_items.append(
                    {
                        "type": "function_call",
                        "id": item_id,
                        "call_id": call_id,
                        "name": fn.get("name"),
                        "arguments": fn.get("arguments") or "{}",
                    }
                )
            continue

        if role == "tool":
            call_id, _ = _split_tool_call_id(msg.get("tool_call_id"))
            output_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output_text,
                }
            )
            continue

    return system_prompt, input_items


def _convert_user_message(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        return {"role": "user", "content": [{"type": "input_text", "text": content}]}
    if isinstance(content, list):
        converted: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                converted.append({"type": "input_text", "text": item.get("text", "")})
            elif item.get("type") == "image_url":
                url = (item.get("image_url") or {}).get("url")
                if url:
                    converted.append({"type": "input_image", "image_url": url, "detail": "auto"})
        if converted:
            return {"role": "user", "content": converted}
    return {"role": "user", "content": [{"type": "input_text", "text": ""}]}


def _split_tool_call_id(tool_call_id: Any) -> tuple[str, str | None]:
    if isinstance(tool_call_id, str) and tool_call_id:
        if "|" in tool_call_id:
            call_id, item_id = tool_call_id.split("|", 1)
            return call_id, item_id or None
        return tool_call_id, None
    return "call_0", None


def _prompt_cache_key(messages: list[dict[str, Any]]) -> str:
    raw = json.dumps(messages, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _iter_sse(response: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
    buffer: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if buffer:
                data_lines = [l[5:].strip() for l in buffer if l.startswith("data:")]
                buffer = []
                if not data_lines:
                    continue
                data = "\n".join(data_lines).strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    yield json.loads(data)
                except Exception:
                    continue
            continue
        buffer.append(line)


async def _consume_sse(response: httpx.Response) -> tuple[str, list[ToolCallRequest], str]:
    content = ""
    tool_calls: list[ToolCallRequest] = []
    tool_call_buffers: dict[str, dict[str, Any]] = {}
    finish_reason = "stop"

    async for event in _iter_sse(response):
        event_type = event.get("type")
        if event_type == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                tool_call_buffers[call_id] = {
                    "id": item.get("id") or "fc_0",
                    "name": item.get("name"),
                    "arguments": item.get("arguments") or "",
                }
        elif event_type == "response.output_text.delta":
            content += event.get("delta") or ""
        elif event_type == "response.function_call_arguments.delta":
            call_id = event.get("call_id")
            if call_id and call_id in tool_call_buffers:
                tool_call_buffers[call_id]["arguments"] += event.get("delta") or ""
        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id")
            if call_id and call_id in tool_call_buffers:
                tool_call_buffers[call_id]["arguments"] = event.get("arguments") or ""
        elif event_type == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                buf = tool_call_buffers.get(call_id) or {}
                args_raw = buf.get("arguments") or item.get("arguments") or "{}"
                try:
                    args = json.loads(args_raw)
                except Exception:
                    args = {"raw": args_raw}
                tool_calls.append(
                    ToolCallRequest(
                        id=f"{call_id}|{buf.get('id') or item.get('id') or 'fc_0'}",
                        name=buf.get("name") or item.get("name"),
                        arguments=args,
                    )
                )
        elif event_type == "response.completed":
            status = (event.get("response") or {}).get("status")
            finish_reason = _map_finish_reason(status)
        elif event_type in {"error", "response.failed"}:
            raise RuntimeError("Codex response failed")

    return content, tool_calls, finish_reason


_FINISH_REASON_MAP = {"completed": "stop", "incomplete": "length", "failed": "error", "cancelled": "error"}


def _map_finish_reason(status: str | None) -> str:
    return _FINISH_REASON_MAP.get(status or "completed", "stop")


def _friendly_error(status_code: int, raw: str) -> str:
    if status_code == 429:
        return "ChatGPT usage quota exceeded or rate limit triggered. Please try again later."
    return f"HTTP {status_code}: {raw}"

````

[⬆ 回到目录](#toc)

## 📄 registry.py

````python
"""
Provider Registry — single source of truth for LLM provider metadata.

Adding a new provider:
  1. Add a ProviderSpec to PROVIDERS below.
  2. Add a field to ProvidersConfig in config/schema.py.
  Done. Env vars, prefixing, config matching, status display all derive from here.

Order matters — it controls match priority and fallback. Gateways first.
Every entry writes out all fields so you can copy-paste as a template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderSpec:
    """One LLM provider's metadata. See PROVIDERS below for real examples.

    Placeholders in env_extras values:
      {api_key}  — the user's API key
      {api_base} — api_base from config, or this spec's default_api_base
    """

    # identity
    name: str  # config field name, e.g. "dashscope"
    keywords: tuple[str, ...]  # model-name keywords for matching (lowercase)
    env_key: str  # LiteLLM env var, e.g. "DASHSCOPE_API_KEY"
    display_name: str = ""  # shown in `nanobot status`

    # model prefixing
    litellm_prefix: str = ""  # "dashscope" → model becomes "dashscope/{model}"
    skip_prefixes: tuple[str, ...] = ()  # don't prefix if model already starts with these

    # extra env vars, e.g. (("ZHIPUAI_API_KEY", "{api_key}"),)
    env_extras: tuple[tuple[str, str], ...] = ()

    # gateway / local detection
    is_gateway: bool = False  # routes any model (OpenRouter, AiHubMix)
    is_local: bool = False  # local deployment (vLLM, Ollama)
    detect_by_key_prefix: str = ""  # match api_key prefix, e.g. "sk-or-"
    detect_by_base_keyword: str = ""  # match substring in api_base URL
    default_api_base: str = ""  # fallback base URL

    # gateway behavior
    strip_model_prefix: bool = False  # strip "provider/" before re-prefixing
    litellm_kwargs: dict[str, Any] = field(default_factory=dict)  # extra kwargs passed to LiteLLM

    # per-model param overrides, e.g. (("kimi-k2.5", {"temperature": 1.0}),)
    model_overrides: tuple[tuple[str, dict[str, Any]], ...] = ()

    # OAuth-based providers (e.g., OpenAI Codex) don't use API keys
    is_oauth: bool = False  # if True, uses OAuth flow instead of API key

    # Direct providers bypass LiteLLM entirely (e.g., CustomProvider)
    is_direct: bool = False

    # Provider supports cache_control on content blocks (e.g. Anthropic prompt caching)
    supports_prompt_caching: bool = False

    @property
    def label(self) -> str:
        return self.display_name or self.name.title()


# ---------------------------------------------------------------------------
# PROVIDERS — the registry. Order = priority. Copy any entry as template.
# ---------------------------------------------------------------------------

PROVIDERS: tuple[ProviderSpec, ...] = (
    # === Custom (direct OpenAI-compatible endpoint, bypasses LiteLLM) ======
    ProviderSpec(
        name="custom",
        keywords=(),
        env_key="",
        display_name="Custom",
        litellm_prefix="",
        is_direct=True,
    ),

    # === Azure OpenAI (direct API calls with API version 2024-10-21) =====
    ProviderSpec(
        name="azure_openai",
        keywords=("azure", "azure-openai"),
        env_key="",
        display_name="Azure OpenAI",
        litellm_prefix="",
        is_direct=True,
    ),
    # === Gateways (detected by api_key / api_base, not model name) =========
    # Gateways can route any model, so they win in fallback.
    # OpenRouter: global gateway, keys start with "sk-or-"
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        env_key="OPENROUTER_API_KEY",
        display_name="OpenRouter",
        litellm_prefix="openrouter",  # anthropic/claude-3 → openrouter/anthropic/claude-3
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="sk-or-",
        detect_by_base_keyword="openrouter",
        default_api_base="https://openrouter.ai/api/v1",
        strip_model_prefix=False,
        model_overrides=(),
        supports_prompt_caching=True,
    ),
    # AiHubMix: global gateway, OpenAI-compatible interface.
    # strip_model_prefix=True: it doesn't understand "anthropic/claude-3",
    # so we strip to bare "claude-3" then re-prefix as "openai/claude-3".
    ProviderSpec(
        name="aihubmix",
        keywords=("aihubmix",),
        env_key="OPENAI_API_KEY",  # OpenAI-compatible
        display_name="AiHubMix",
        litellm_prefix="openai",  # → openai/{model}
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="aihubmix",
        default_api_base="https://aihubmix.com/v1",
        strip_model_prefix=True,  # anthropic/claude-3 → claude-3 → openai/claude-3
        model_overrides=(),
    ),
    # SiliconFlow (硅基流动): OpenAI-compatible gateway, model names keep org prefix
    ProviderSpec(
        name="siliconflow",
        keywords=("siliconflow",),
        env_key="OPENAI_API_KEY",
        display_name="SiliconFlow",
        litellm_prefix="openai",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="siliconflow",
        default_api_base="https://api.siliconflow.cn/v1",
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # VolcEngine (火山引擎): OpenAI-compatible gateway, pay-per-use models
    ProviderSpec(
        name="volcengine",
        keywords=("volcengine", "volces", "ark"),
        env_key="OPENAI_API_KEY",
        display_name="VolcEngine",
        litellm_prefix="volcengine",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="volces",
        default_api_base="https://ark.cn-beijing.volces.com/api/v3",
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # VolcEngine Coding Plan (火山引擎 Coding Plan): same key as volcengine
    ProviderSpec(
        name="volcengine_coding_plan",
        keywords=("volcengine-plan",),
        env_key="OPENAI_API_KEY",
        display_name="VolcEngine Coding Plan",
        litellm_prefix="volcengine",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="https://ark.cn-beijing.volces.com/api/coding/v3",
        strip_model_prefix=True,
        model_overrides=(),
    ),

    # BytePlus: VolcEngine international, pay-per-use models
    ProviderSpec(
        name="byteplus",
        keywords=("byteplus",),
        env_key="OPENAI_API_KEY",
        display_name="BytePlus",
        litellm_prefix="volcengine",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="bytepluses",
        default_api_base="https://ark.ap-southeast.bytepluses.com/api/v3",
        strip_model_prefix=True,
        model_overrides=(),
    ),

    # BytePlus Coding Plan: same key as byteplus
    ProviderSpec(
        name="byteplus_coding_plan",
        keywords=("byteplus-plan",),
        env_key="OPENAI_API_KEY",
        display_name="BytePlus Coding Plan",
        litellm_prefix="volcengine",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="https://ark.ap-southeast.bytepluses.com/api/coding/v3",
        strip_model_prefix=True,
        model_overrides=(),
    ),


    # === Standard providers (matched by model-name keywords) ===============
    # Anthropic: LiteLLM recognizes "claude-*" natively, no prefix needed.
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        litellm_prefix="",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
        supports_prompt_caching=True,
    ),
    # OpenAI: LiteLLM recognizes "gpt-*" natively, no prefix needed.
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        litellm_prefix="",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # OpenAI Codex: uses OAuth, not API key.
    ProviderSpec(
        name="openai_codex",
        keywords=("openai-codex",),
        env_key="",  # OAuth-based, no API key
        display_name="OpenAI Codex",
        litellm_prefix="",  # Not routed through LiteLLM
        skip_prefixes=(),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="codex",
        default_api_base="https://chatgpt.com/backend-api",
        strip_model_prefix=False,
        model_overrides=(),
        is_oauth=True,  # OAuth-based authentication
    ),
    # Github Copilot: uses OAuth, not API key.
    ProviderSpec(
        name="github_copilot",
        keywords=("github_copilot", "copilot"),
        env_key="",  # OAuth-based, no API key
        display_name="Github Copilot",
        litellm_prefix="github_copilot",  # github_copilot/model → github_copilot/model
        skip_prefixes=("github_copilot/",),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
        is_oauth=True,  # OAuth-based authentication
    ),
    # DeepSeek: needs "deepseek/" prefix for LiteLLM routing.
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        litellm_prefix="deepseek",  # deepseek-chat → deepseek/deepseek-chat
        skip_prefixes=("deepseek/",),  # avoid double-prefix
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # Gemini: needs "gemini/" prefix for LiteLLM.
    ProviderSpec(
        name="gemini",
        keywords=("gemini",),
        env_key="GEMINI_API_KEY",
        display_name="Gemini",
        litellm_prefix="gemini",  # gemini-pro → gemini/gemini-pro
        skip_prefixes=("gemini/",),  # avoid double-prefix
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # Zhipu: LiteLLM uses "zai/" prefix.
    # Also mirrors key to ZHIPUAI_API_KEY (some LiteLLM paths check that).
    # skip_prefixes: don't add "zai/" when already routed via gateway.
    ProviderSpec(
        name="zhipu",
        keywords=("zhipu", "glm", "zai"),
        env_key="ZAI_API_KEY",
        display_name="Zhipu AI",
        litellm_prefix="zai",  # glm-4 → zai/glm-4
        skip_prefixes=("zhipu/", "zai/", "openrouter/", "hosted_vllm/"),
        env_extras=(("ZHIPUAI_API_KEY", "{api_key}"),),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # DashScope: Qwen models, needs "dashscope/" prefix.
    ProviderSpec(
        name="dashscope",
        keywords=("qwen", "dashscope"),
        env_key="DASHSCOPE_API_KEY",
        display_name="DashScope",
        litellm_prefix="dashscope",  # qwen-max → dashscope/qwen-max
        skip_prefixes=("dashscope/", "openrouter/"),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # Moonshot: Kimi models, needs "moonshot/" prefix.
    # LiteLLM requires MOONSHOT_API_BASE env var to find the endpoint.
    # Kimi K2.5 API enforces temperature >= 1.0.
    ProviderSpec(
        name="moonshot",
        keywords=("moonshot", "kimi"),
        env_key="MOONSHOT_API_KEY",
        display_name="Moonshot",
        litellm_prefix="moonshot",  # kimi-k2.5 → moonshot/kimi-k2.5
        skip_prefixes=("moonshot/", "openrouter/"),
        env_extras=(("MOONSHOT_API_BASE", "{api_base}"),),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="https://api.moonshot.ai/v1",  # intl; use api.moonshot.cn for China
        strip_model_prefix=False,
        model_overrides=(("kimi-k2.5", {"temperature": 1.0}),),
    ),
    # MiniMax: needs "minimax/" prefix for LiteLLM routing.
    # Uses OpenAI-compatible API at api.minimax.io/v1.
    ProviderSpec(
        name="minimax",
        keywords=("minimax",),
        env_key="MINIMAX_API_KEY",
        display_name="MiniMax",
        litellm_prefix="minimax",  # MiniMax-M2.1 → minimax/MiniMax-M2.1
        skip_prefixes=("minimax/", "openrouter/"),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="https://api.minimax.io/v1",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # === Local deployment (matched by config key, NOT by api_base) =========
    # vLLM / any OpenAI-compatible local server.
    # Detected when config key is "vllm" (provider_name="vllm").
    ProviderSpec(
        name="vllm",
        keywords=("vllm",),
        env_key="HOSTED_VLLM_API_KEY",
        display_name="vLLM/Local",
        litellm_prefix="hosted_vllm",  # Llama-3-8B → hosted_vllm/Llama-3-8B
        skip_prefixes=(),
        env_extras=(),
        is_gateway=False,
        is_local=True,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",  # user must provide in config
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # === Ollama (local, OpenAI-compatible) ===================================
    ProviderSpec(
        name="ollama",
        keywords=("ollama", "nemotron"),
        env_key="OLLAMA_API_KEY",
        display_name="Ollama",
        litellm_prefix="ollama_chat",  # model → ollama_chat/model
        skip_prefixes=("ollama/", "ollama_chat/"),
        env_extras=(),
        is_gateway=False,
        is_local=True,
        detect_by_key_prefix="",
        detect_by_base_keyword="11434",
        default_api_base="http://localhost:11434",
        strip_model_prefix=False,
        model_overrides=(),
    ),
    # === Auxiliary (not a primary LLM provider) ============================
    # Groq: mainly used for Whisper voice transcription, also usable for LLM.
    # Needs "groq/" prefix for LiteLLM routing. Placed last — it rarely wins fallback.
    ProviderSpec(
        name="groq",
        keywords=("groq",),
        env_key="GROQ_API_KEY",
        display_name="Groq",
        litellm_prefix="groq",  # llama3-8b-8192 → groq/llama3-8b-8192
        skip_prefixes=("groq/",),  # avoid double-prefix
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def find_by_model(model: str) -> ProviderSpec | None:
    """Match a standard provider by model-name keyword (case-insensitive).
    Skips gateways/local — those are matched by api_key/api_base instead."""
    model_lower = model.lower()
    model_normalized = model_lower.replace("-", "_")
    model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
    normalized_prefix = model_prefix.replace("-", "_")
    std_specs = [s for s in PROVIDERS if not s.is_gateway and not s.is_local]

    # Prefer explicit provider prefix — prevents `github-copilot/...codex` matching openai_codex.
    for spec in std_specs:
        if model_prefix and normalized_prefix == spec.name:
            return spec

    for spec in std_specs:
        if any(
            kw in model_lower or kw.replace("-", "_") in model_normalized for kw in spec.keywords
        ):
            return spec
    return None


def find_gateway(
    provider_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> ProviderSpec | None:
    """Detect gateway/local provider.

    Priority:
      1. provider_name — if it maps to a gateway/local spec, use it directly.
      2. api_key prefix — e.g. "sk-or-" → OpenRouter.
      3. api_base keyword — e.g. "aihubmix" in URL → AiHubMix.

    A standard provider with a custom api_base (e.g. DeepSeek behind a proxy)
    will NOT be mistaken for vLLM — the old fallback is gone.
    """
    # 1. Direct match by config key
    if provider_name:
        spec = find_by_name(provider_name)
        if spec and (spec.is_gateway or spec.is_local):
            return spec

    # 2. Auto-detect by api_key prefix / api_base keyword
    for spec in PROVIDERS:
        if spec.detect_by_key_prefix and api_key and api_key.startswith(spec.detect_by_key_prefix):
            return spec
        if spec.detect_by_base_keyword and api_base and spec.detect_by_base_keyword in api_base:
            return spec

    return None


def find_by_name(name: str) -> ProviderSpec | None:
    """Find a provider spec by config field name, e.g. "dashscope"."""
    for spec in PROVIDERS:
        if spec.name == name:
            return spec
    return None

````

[⬆ 回到目录](#toc)

## 📄 transcription.py

````python
"""Voice transcription provider using Groq."""

import os
from pathlib import Path

import httpx
from loguru import logger


class GroqTranscriptionProvider:
    """
    Voice transcription provider using Groq's Whisper API.

    Groq offers extremely fast transcription with a generous free tier.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.api_url = "https://api.groq.com/openai/v1/audio/transcriptions"

    async def transcribe(self, file_path: str | Path) -> str:
        """
        Transcribe an audio file using Groq.

        Args:
            file_path: Path to the audio file.

        Returns:
            Transcribed text.
        """
        if not self.api_key:
            logger.warning("Groq API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    files = {
                        "file": (path.name, f),
                        "model": (None, "whisper-large-v3"),
                    }
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                    }

                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        files=files,
                        timeout=60.0
                    )

                    response.raise_for_status()
                    data = response.json()
                    return data.get("text", "")

        except Exception as e:
            logger.error("Groq transcription error: {}", e)
            return ""

````

[⬆ 回到目录](#toc)

---
### 📊 最终统计汇总
- **文件总数:** 8
- **代码总行数:** 1812
- **物理总大小:** 65.20 KB
