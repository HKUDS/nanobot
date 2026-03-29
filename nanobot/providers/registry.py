"""
Provider Registry — single source of truth for LLM provider metadata.

Adding a new provider:
  1. Add a ProviderSpec to PROVIDERS below.
  2. Add a field to ProvidersConfig in config/schema.py.
  Done. Env vars, config matching, status display all derive from here.

Order matters — it controls match priority and fallback. Gateways first.
Every entry writes out all fields so you can copy-paste as a template.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic.alias_generators import to_snake


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
    env_key: str  # env var for API key, e.g. "DASHSCOPE_API_KEY"
    display_name: str = ""  # shown in `nanobot status`

    # which provider implementation to use
    # "openai_compat" | "anthropic" | "azure_openai" | "openai_codex"
    backend: str = "openai_compat"

    # extra env vars, e.g. (("ZHIPUAI_API_KEY", "{api_key}"),)
    env_extras: tuple[tuple[str, str], ...] = ()

    # gateway / local detection
    is_gateway: bool = False  # routes any model (OpenRouter, AiHubMix)
    is_local: bool = False  # local deployment (vLLM, Ollama)
    detect_by_key_prefix: str = ""  # match api_key prefix, e.g. "sk-or-"
    detect_by_base_keyword: str = ""  # match substring in api_base URL
    default_api_base: str = ""  # OpenAI-compatible base URL for this provider

    # gateway behavior
    strip_model_prefix: bool = False  # strip "provider/" before sending to gateway
    supports_max_completion_tokens: bool = False

    # per-model param overrides, e.g. (("kimi-k2.5", {"temperature": 1.0}),)
    model_overrides: tuple[tuple[str, dict[str, Any]], ...] = ()

    # OAuth-based providers (e.g., OpenAI Codex) don't use API keys
    is_oauth: bool = False

    # Direct providers skip API-key validation (user supplies everything)
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
    # === Custom (direct OpenAI-compatible endpoint) ========================
    ProviderSpec(
        name="custom",
        keywords=(),
        env_key="",
        display_name="Custom",
        backend="openai_compat",
        is_direct=True,
    ),

    # === Azure OpenAI (direct API calls with API version 2024-10-21) =====
    ProviderSpec(
        name="azure_openai",
        keywords=("azure", "azure-openai"),
        env_key="",
        display_name="Azure OpenAI",
        backend="azure_openai",
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
        backend="openai_compat",
        is_gateway=True,
        detect_by_key_prefix="sk-or-",
        detect_by_base_keyword="openrouter",
        default_api_base="https://openrouter.ai/api/v1",
        supports_prompt_caching=True,
    ),
    # AiHubMix: global gateway, OpenAI-compatible interface.
    # strip_model_prefix=True: doesn't understand "anthropic/claude-3",
    # strips to bare "claude-3".
    ProviderSpec(
        name="aihubmix",
        keywords=("aihubmix",),
        env_key="OPENAI_API_KEY",
        display_name="AiHubMix",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="aihubmix",
        default_api_base="https://aihubmix.com/v1",
        strip_model_prefix=True,
    ),
    # SiliconFlow (硅基流动): OpenAI-compatible gateway, model names keep org prefix
    ProviderSpec(
        name="siliconflow",
        keywords=("siliconflow",),
        env_key="OPENAI_API_KEY",
        display_name="SiliconFlow",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="siliconflow",
        default_api_base="https://api.siliconflow.cn/v1",
    ),

    # VolcEngine (火山引擎): OpenAI-compatible gateway, pay-per-use models
    ProviderSpec(
        name="volcengine",
        keywords=("volcengine", "volces", "ark"),
        env_key="OPENAI_API_KEY",
        display_name="VolcEngine",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="volces",
        default_api_base="https://ark.cn-beijing.volces.com/api/v3",
    ),

    # VolcEngine Coding Plan (火山引擎 Coding Plan): same key as volcengine
    ProviderSpec(
        name="volcengine_coding_plan",
        keywords=("volcengine-plan",),
        env_key="OPENAI_API_KEY",
        display_name="VolcEngine Coding Plan",
        backend="openai_compat",
        is_gateway=True,
        default_api_base="https://ark.cn-beijing.volces.com/api/coding/v3",
        strip_model_prefix=True,
    ),

    # BytePlus: VolcEngine international, pay-per-use models
    ProviderSpec(
        name="byteplus",
        keywords=("byteplus",),
        env_key="OPENAI_API_KEY",
        display_name="BytePlus",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="bytepluses",
        default_api_base="https://ark.ap-southeast.bytepluses.com/api/v3",
        strip_model_prefix=True,
    ),

    # BytePlus Coding Plan: same key as byteplus
    ProviderSpec(
        name="byteplus_coding_plan",
        keywords=("byteplus-plan",),
        env_key="OPENAI_API_KEY",
        display_name="BytePlus Coding Plan",
        backend="openai_compat",
        is_gateway=True,
        default_api_base="https://ark.ap-southeast.bytepluses.com/api/coding/v3",
        strip_model_prefix=True,
    ),


    # === Standard providers (matched by model-name keywords) ===============
    # Anthropic: native Anthropic SDK
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        backend="anthropic",
        supports_prompt_caching=True,
    ),
    # OpenAI: SDK default base URL (no override needed)
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        backend="openai_compat",
    ),
    # OpenAI Codex: OAuth-based, dedicated provider
    ProviderSpec(
        name="openai_codex",
        keywords=("openai-codex",),
        env_key="",
        display_name="OpenAI Codex",
        backend="openai_codex",
        detect_by_base_keyword="codex",
        default_api_base="https://chatgpt.com/backend-api",
        is_oauth=True,
    ),
    # GitHub Copilot: OAuth-based
    ProviderSpec(
        name="github_copilot",
        keywords=("github_copilot", "copilot"),
        env_key="",
        display_name="Github Copilot",
        backend="openai_compat",
        default_api_base="https://api.githubcopilot.com",
        is_oauth=True,
    ),
    # DeepSeek: OpenAI-compatible at api.deepseek.com
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        backend="openai_compat",
        default_api_base="https://api.deepseek.com",
    ),
    # Gemini: Google's OpenAI-compatible endpoint
    ProviderSpec(
        name="gemini",
        keywords=("gemini",),
        env_key="GEMINI_API_KEY",
        display_name="Gemini",
        backend="openai_compat",
        default_api_base="https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    # Zhipu (智谱): OpenAI-compatible at open.bigmodel.cn
    ProviderSpec(
        name="zhipu",
        keywords=("zhipu", "glm", "zai"),
        env_key="ZAI_API_KEY",
        display_name="Zhipu AI",
        backend="openai_compat",
        env_extras=(("ZHIPUAI_API_KEY", "{api_key}"),),
        default_api_base="https://open.bigmodel.cn/api/paas/v4",
    ),
    # DashScope (通义): Qwen models, OpenAI-compatible endpoint
    ProviderSpec(
        name="dashscope",
        keywords=("qwen", "dashscope"),
        env_key="DASHSCOPE_API_KEY",
        display_name="DashScope",
        backend="openai_compat",
        default_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    # DashScope Coding Plan (通义灵码): dedicated coding endpoint
    ProviderSpec(
        name="dashscope_coding_plan",
        keywords=("dashscope-coding-plan", "dashscope_coding_plan"),
        env_key="DASHSCOPE_API_KEY",
        display_name="DashScope Coding Plan",
        backend="openai_compat",
        detect_by_base_keyword="coding.dashscope",
        default_api_base="https://coding.dashscope.aliyuncs.com/v1",
    ),
    # Moonshot (月之暗面): Kimi models. K2.5 enforces temperature >= 1.0.
    ProviderSpec(
        name="moonshot",
        keywords=("moonshot", "kimi"),
        env_key="MOONSHOT_API_KEY",
        display_name="Moonshot",
        backend="openai_compat",
        default_api_base="https://api.moonshot.ai/v1",
        model_overrides=(("kimi-k2.5", {"temperature": 1.0}),),
    ),
    # MiniMax: OpenAI-compatible API
    ProviderSpec(
        name="minimax",
        keywords=("minimax",),
        env_key="MINIMAX_API_KEY",
        display_name="MiniMax",
        backend="openai_compat",
        default_api_base="https://api.minimax.io/v1",
    ),
    # Mistral AI: OpenAI-compatible API
    ProviderSpec(
        name="mistral",
        keywords=("mistral",),
        env_key="MISTRAL_API_KEY",
        display_name="Mistral",
        backend="openai_compat",
        default_api_base="https://api.mistral.ai/v1",
    ),
    # Step Fun (阶跃星辰): OpenAI-compatible API
    ProviderSpec(
        name="stepfun",
        keywords=("stepfun", "step"),
        env_key="STEPFUN_API_KEY",
        display_name="Step Fun",
        backend="openai_compat",
        default_api_base="https://api.stepfun.com/v1",
    ),
    # === Local deployment (matched by config key, NOT by api_base) =========
    # vLLM / any OpenAI-compatible local server
    ProviderSpec(
        name="vllm",
        keywords=("vllm",),
        env_key="HOSTED_VLLM_API_KEY",
        display_name="vLLM/Local",
        backend="openai_compat",
        is_local=True,
    ),
    # Ollama (local, OpenAI-compatible)
    ProviderSpec(
        name="ollama",
        keywords=("ollama", "nemotron"),
        env_key="OLLAMA_API_KEY",
        display_name="Ollama",
        backend="openai_compat",
        is_local=True,
        detect_by_base_keyword="11434",
        default_api_base="http://localhost:11434/v1",
    ),
    # === OpenVINO Model Server (direct, local, OpenAI-compatible at /v3) ===
    ProviderSpec(
        name="ovms",
        keywords=("openvino", "ovms"),
        env_key="",
        display_name="OpenVINO Model Server",
        backend="openai_compat",
        is_direct=True,
        is_local=True,
        default_api_base="http://localhost:8000/v3",
    ),
    # === Auxiliary (not a primary LLM provider) ============================
    # Groq: mainly used for Whisper voice transcription, also usable for LLM
    ProviderSpec(
        name="groq",
        keywords=("groq",),
        env_key="GROQ_API_KEY",
        display_name="Groq",
        backend="openai_compat",
        default_api_base="https://api.groq.com/openai/v1",
    ),
)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def find_by_name(name: str) -> ProviderSpec | None:
    """Find a provider spec by config field name, e.g. "dashscope"."""
    normalized = to_snake(name.replace("-", "_"))
    for spec in PROVIDERS:
        if spec.name == normalized:
            return spec
    return None
