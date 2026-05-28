"""Configuration schema using Pydantic."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings

from nanobot.cron.types import CronSchedule

if TYPE_CHECKING:
    from nanobot.agent.tools.cli_apps import CliAppsToolConfig
    from nanobot.agent.tools.image_generation import ImageGenerationToolConfig
    from nanobot.agent.tools.self import MyToolConfig
    from nanobot.agent.tools.shell import ExecToolConfig
    from nanobot.agent.tools.web import WebToolsConfig


class Base(BaseModel):
    """Base model that accepts both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ChannelsConfig(Base):
    """Configuration for chat channels.

    Built-in and plugin channel configs are stored as extra fields (dicts).
    Each channel parses its own config in __init__.
    Per-channel "streaming": true enables streaming output (requires send_delta impl).
    """

    model_config = ConfigDict(extra="allow")

    send_progress: bool = True  # stream agent's text progress to the channel
    send_tool_hints: bool = False  # stream tool-call hints (e.g. read_file("…"))
    show_reasoning: bool = True  # surface model reasoning when channel implements it
    send_max_retries: int = Field(default=3, ge=0, le=10)  # Max delivery attempts (initial send included)
    transcription_provider: str = "groq"  # Voice transcription backend: "groq" or "openai"
    transcription_language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")  # Optional ISO-639-1 hint for audio transcription


class DreamConfig(Base):
    """Dream memory consolidation configuration."""

    _HOUR_MS = 3_600_000

    interval_h: int = Field(default=2, ge=1)  # Every 2 hours by default
    cron: str | None = Field(default=None, exclude=True)  # Legacy compatibility override
    model_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("modelOverride", "model", "model_override"),
    )  # Optional Dream-specific model override
    max_batch_size: int = Field(default=20, ge=1)  # Max history entries per run
    # Bumped from 10 to 15 in #3212 (exp002: +30% dedup, no accuracy loss; >15 plateaus).
    max_iterations: int = Field(default=15, ge=1)  # Max tool calls per Phase 2
    # Per-line git-blame age annotation in Phase 1 prompt (see #3212). Default
    # on — set to False to feed MEMORY.md raw if a specific LLM reacts poorly
    # to the `← Nd` suffix or you want deterministic, git-independent prompts.
    annotate_line_ages: bool = True

    def build_schedule(self, timezone: str) -> CronSchedule:
        """Build the runtime schedule, preferring the legacy cron override if present."""
        if self.cron:
            return CronSchedule(kind="cron", expr=self.cron, tz=timezone)
        return CronSchedule(kind="every", every_ms=self.interval_h * self._HOUR_MS)

    def describe_schedule(self) -> str:
        """Return a human-readable summary for logs and startup output."""
        if self.cron:
            return f"cron {self.cron} (legacy)"
        hours = self.interval_h
        return f"every {hours}h"


class InlineFallbackConfig(Base):
    """One inline fallback model configuration."""

    model: str
    provider: str
    max_tokens: int | None = None
    context_window_tokens: int | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None


FallbackCandidate = str | InlineFallbackConfig


class ModelPresetConfig(Base):
    """A named set of model + generation parameters for quick switching."""

    model: str
    provider: str = "auto"
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    temperature: float = 0.1
    reasoning_effort: str | None = None

    def to_generation_settings(self) -> Any:
        from nanobot.providers.base import GenerationSettings
        return GenerationSettings(
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            reasoning_effort=self.reasoning_effort,
        )

class SkillRetrievalConfig(Base):
    """按 query 检索 skill 摘要（FTS 目录）。默认关闭。"""

    enable: bool = True  # 启用 FTS top-k 检索，替代全量 skill 列表注入
    mode: Literal["fts", "llm", "hybrid", "auto"] = "llm" # 检索模式：fts 全量 FTS5 目录；llm 纯 LLM 推理；hybrid 混合模式（FTS + LLM）；auto 自动选择（默认）
    top_k: int = Field(default=8, ge=1, le=50)  # 每条用户消息最多召回的 skill 数量
    min_score: float | None = Field(default=None)  # BM25 分数阈值（越小越相关；None 表示不过滤）
    fallback_to_full_list: bool = True  # 检索失败或无结果时回退到全量 catalog
    index_body_chars: int = Field(default=0, ge=0, le=2000)  # 除 frontmatter 外索引的 SKILL.md 正文字符数（0 = 仅 name + description）
    rebuild_on_startup: bool = True  # Agent 启动时预热/重建索引
    rebuild_on_miss: bool = True  # 访问时发现 catalog 指纹不匹配则重建
    catalog_cache: bool = True  # L1 全量 catalog 内存缓存（fallback 时避免重复 SELECT）
    query_cache_size: int = Field(default=256, ge=0)  # L1 query LRU 容量（generation + query 命中）；0 表示禁用
    fts_candidate_k: int = Field(default=20, ge=1, le=100)  # FTS 检索候选池大小
    llm_skill_threshold: int = Field(default=15, ge=1, le=100)  # LLM 检索技能数量阈值
    llm_model: str | None = None  # LLM 模型名称
    llm_timeout_s: float = Field(default=10.0, gt=0, le=120)  # LLM 检索超时时间
    llm_max_tokens: int = Field(default=256, ge=32, le=4096)  # LLM 检索最大 token 数


class LayeredMemoryOffloadConfig(Base):
    """短期记忆：Task Canvas + node_id（对标 Tencent context offload 顶层）。"""

    enable: bool = False
    max_canvas_chars: int = Field(default=1500, ge=200, le=8000)
    max_node_summary_chars: int = Field(default=120, ge=20, le=500)
    update_canvas_every_n_tools: int = Field(
        default=0,
        ge=0,
        le=100,
    )  # 0 = 仅 turn 末刷新 canvas.mmd


class LayeredMemoryCaptureConfig(Base):
    """L0 原始对话落盘。"""

    enable: bool = False
    l0_retention_days: int = Field(default=30, ge=0)  # 0 = 不自动清理


class LayeredMemoryPipelineConfig(Base):
    """L1→L2→L3 异步流水线触发参数。"""

    every_n_conversations: int = Field(default=5, ge=1)
    enable_warmup: bool = True  # 1→2→4→…→every_n
    l1_idle_timeout_seconds: int = Field(default=600, ge=0)
    l2_delay_after_l1_seconds: int = Field(default=90, ge=0)
    l2_min_interval_seconds: int = Field(default=900, ge=0)
    l2_max_interval_seconds: int = Field(default=3600, ge=1)
    session_active_window_hours: int = Field(default=24, ge=1)
    max_memories_per_session: int = Field(default=20, ge=1)
    enable_l1_dedup: bool = True
    extraction_model: str | None = None  # None = 主 agent provider


class LayeredMemoryRecallConfig(Base):
    """Turn 前记忆召回。"""

    enable: bool = False
    strategy: Literal["fts", "embedding", "hybrid"] = "hybrid"
    top_k: int = Field(default=8, ge=1, le=50)
    timeout_ms: int = Field(default=5000, ge=500, le=60_000)
    max_prepend_chars: int = Field(default=4000, ge=500, le=20_000)
    max_search_calls_per_turn: int = Field(default=3, ge=1, le=10)


class LayeredMemoryEmbeddingConfig(Base):
    """L1 hybrid 召回可选向量（LM2+）。"""

    enable: bool = False
    model: str | None = None
    provider: str = "auto"


class LayeredMemorySubagentConfig(Base):
    """子 agent 默认不启用分层记忆，避免污染主会话画布。"""

    enable_offload: bool = False
    enable_recall: bool = False
    enable_capture: bool = False


class LayeredMemoryConfig(Base):
    """分层记忆（L0–L3 + Task Canvas）。详见 ``.agent/layered-memory/design.md``。

    默认全关；与 Context Budget、Evolution 正交。
    """

    enable: bool = False

    offload: LayeredMemoryOffloadConfig = Field(default_factory=LayeredMemoryOffloadConfig)
    capture: LayeredMemoryCaptureConfig = Field(default_factory=LayeredMemoryCaptureConfig)
    pipeline: LayeredMemoryPipelineConfig = Field(default_factory=LayeredMemoryPipelineConfig)
    recall: LayeredMemoryRecallConfig = Field(default_factory=LayeredMemoryRecallConfig)
    embedding: LayeredMemoryEmbeddingConfig = Field(
        default_factory=LayeredMemoryEmbeddingConfig,
    )
    subagent: LayeredMemorySubagentConfig = Field(
        default_factory=LayeredMemorySubagentConfig,
    )

    def offload_enabled(self, *, is_subagent: bool = False) -> bool:
        if not self.enable or not self.offload.enable:
            return False
        if is_subagent and not self.subagent.enable_offload:
            return False
        return True

    def capture_enabled(self, *, is_subagent: bool = False) -> bool:
        if not self.enable or not self.capture.enable:
            return False
        if is_subagent and not self.subagent.enable_capture:
            return False
        return True

    def recall_enabled(self, *, is_subagent: bool = False) -> bool:
        if not self.enable or not self.recall.enable:
            return False
        if is_subagent and not self.subagent.enable_recall:
            return False
        return True


class EvolutionTraceConfig(Base):
    """Turn 执行轨迹存储（PostTask 与 GEPA 共用）。"""

    retention_days: int = Field(default=30, ge=1)  # 超过此天数的 trace 可被 prune


class EvolutionPostTaskConfig(Base):
    """Turn 结束后 skill 创建（MVP 仅 create，update 走 GEPA）。"""

    min_tool_calls: int = Field(default=3, ge=1)  # 单 turn 工具调用数达到此值才考虑触发
    cooldown_minutes: int = Field(default=10, ge=0)  # 同 session 两次 PostTask 的最小间隔（0 = 不冷却）
    min_confidence: float = Field(default=0.8, ge=0.0, le=1.0)  # LLM 判定 create 的置信度下限
    auto_apply: bool = False  # true = 直接写入 skills/；false = 提案 + /evolve-apply 审核
    model: str | None = None  # PostTask 路由 LLM；None 时使用主 agent provider
    llm_timeout_s: float = Field(default=120.0, gt=0, le=300)  # decide + skill-gen LLM 超时（秒）
    proposal_retention_days: int = Field(default=30, ge=1)  # 未 apply 的提案过期天数


class EvolutionGepaConfig(Base):
    """离线 DSPy + GEPA skill 优化（仅 update 已有 skill）。"""

    _HOUR_MS = 3_600_000

    enable: bool = False
    interval_hours: float | None = Field(default=None, gt=0)  # None = 仅手动 / CLI 触发
    model: str | None = None  # GEPA 运行模型；None 时使用主 agent provider
    max_budget_usd: float = Field(default=10.0, gt=0)  # 单次 GEPA 运行预算上限（USD）
    min_traces: int = Field(default=3, ge=1)  # 构建数据集所需最少 trace 数
    max_skills_per_run: int = Field(default=1, ge=1)  # 单次运行最多优化的 active skill 数
    notify_on_complete: bool = False  # cron 完成且有 proposal 时是否 bus 通知（需 notify_channel/chat_id）
    notify_channel: str | None = None  # cron 通知目标 channel（如 telegram）
    notify_chat_id: str | None = None  # cron 通知目标 chat_id

    def build_schedule(self, timezone: str) -> CronSchedule | None:
        """Build cron schedule when ``interval_hours`` is set; otherwise manual-only."""
        if self.interval_hours is None:
            return None
        every_ms = int(self.interval_hours * self._HOUR_MS)
        return CronSchedule(kind="every", every_ms=every_ms, tz=timezone)

    def describe_schedule(self) -> str:
        """Human-readable schedule for gateway startup logs."""
        if self.interval_hours is None:
            return "manual only"
        hours = self.interval_hours
        if hours == int(hours):
            return f"every {int(hours)}h"
        return f"every {hours}h"


class EvolutionConfig(Base):
    """Hermes 式自进化：PostTask 创建 skill + GEPA 离线优化。

    默认开启 trace + PostTask；生产环境可在 config 中设 ``enable: false`` 关闭。
    详见 ``.agent/hermes-design.md``。
    """

    enable: bool = True  # 总开关：开启后记录 trace，并按子配置运行 PostTask / GEPA

    trace: EvolutionTraceConfig = Field(default_factory=EvolutionTraceConfig)
    post_task: EvolutionPostTaskConfig = Field(default_factory=EvolutionPostTaskConfig)
    gepa: EvolutionGepaConfig = Field(default_factory=EvolutionGepaConfig)

    def recording_enabled(self) -> bool:
        """是否应在本 turn 结束后写入 trace。"""
        return self.enable

    def post_task_enabled(self) -> bool:
        """是否应在本 turn 结束后尝试 PostTask 进化。"""
        return self.enable

    def gepa_enabled(self) -> bool:
        """是否应调度 GEPA 离线优化。"""
        return self.enable and self.gepa.enable


class AgentDefaults(Base):
    """Default agent configuration."""

    workspace: str = "~/.nanobot/workspace"
    model_preset: str | None = None  # Active preset name — takes precedence over fields below
    model: str = "anthropic/claude-opus-4-5"
    provider: str = (
        "auto"  # Provider name (e.g. "anthropic", "openrouter") or "auto" for auto-detection
    )
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    context_block_limit: int | None = None
    temperature: float = 0.1
    fallback_models: list[FallbackCandidate] = Field(default_factory=list)
    max_tool_iterations: int = 200
    max_concurrent_subagents: int = Field(default=1, ge=1)
    max_tool_result_chars: int = 16_000
    provider_retry_mode: Literal["standard", "persistent"] = "standard"
    tool_hint_max_length: int = Field(
        default=40,
        ge=20,
        le=500,
        validation_alias=AliasChoices("toolHintMaxLength"),
        serialization_alias="toolHintMaxLength",
    )  # Max characters for tool hint display (e.g. "$ cd …/project && npm test")
    reasoning_effort: str | None = None  # low / medium / high / adaptive / none — LLM thinking effort; None preserves the provider default
    timezone: str = "UTC"  # IANA timezone, e.g. "Asia/Shanghai", "America/New_York"
    bot_name: str = "nanobot"  # Display name shown in CLI prompts (e.g. "{name} is thinking...")
    bot_icon: str = "🐈"  # Short icon (emoji or text) shown next to the bot name in CLI; "" to omit
    unified_session: bool = False  # Share one session across all channels (single-user multi-device)
    disabled_skills: list[str] = Field(default_factory=list)  # Skill names to exclude from loading (e.g. ["summarize", "skill-creator"])
    skill_retrieval: SkillRetrievalConfig = Field(default_factory=SkillRetrievalConfig)
    session_ttl_minutes: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("idleCompactAfterMinutes", "sessionTtlMinutes"),
        serialization_alias="idleCompactAfterMinutes",
    )  # Auto-compact idle threshold in minutes (0 = disabled)
    max_messages: int = Field(
        default=120,
        ge=0,
    )  # Max messages to replay from session history (0 = use default 120, respects token budget)
    consolidation_ratio: float = Field(
        default=0.5,
        ge=0.1,
        le=0.95,
        validation_alias=AliasChoices("consolidationRatio"),
        serialization_alias="consolidationRatio",
    )  # Consolidation target ratio (0.5 = 50% of budget retained after compression)
    dream: DreamConfig = Field(default_factory=DreamConfig)
    evolution: EvolutionConfig = Field(default_factory=EvolutionConfig)
    layered_memory: LayeredMemoryConfig = Field(default_factory=LayeredMemoryConfig)


class AgentsConfig(Base):
    """Agent configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(Base):
    """LLM provider configuration."""

    api_key: str | None = None
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None  # Custom headers (e.g. APP-Code for AiHubMix)
    extra_body: dict[str, Any] | None = None  # Extra fields merged into every request body


class BedrockProviderConfig(ProviderConfig):
    """AWS Bedrock Runtime provider configuration."""

    region: str | None = None  # AWS region, falls back to AWS_REGION/AWS_DEFAULT_REGION/profile
    profile: str | None = None  # Optional AWS shared config profile


class ProvidersConfig(Base):
    """Configuration for LLM providers."""

    custom: ProviderConfig = Field(default_factory=ProviderConfig)  # Any OpenAI-compatible endpoint
    azure_openai: ProviderConfig = Field(default_factory=ProviderConfig)  # Azure OpenAI (model = deployment name)
    bedrock: BedrockProviderConfig = Field(default_factory=BedrockProviderConfig)  # AWS Bedrock Converse
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    huggingface: ProviderConfig = Field(default_factory=ProviderConfig)
    skywork: ProviderConfig = Field(default_factory=ProviderConfig)  # Skywork / APIFree API gateway
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    ollama: ProviderConfig = Field(default_factory=ProviderConfig)  # Ollama local models
    lm_studio: ProviderConfig = Field(default_factory=ProviderConfig)  # LM Studio local models
    atomic_chat: ProviderConfig = Field(default_factory=ProviderConfig)  # Atomic Chat local models
    ovms: ProviderConfig = Field(default_factory=ProviderConfig)  # OpenVINO Model Server (OVMS)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax_anthropic: ProviderConfig = Field(default_factory=ProviderConfig)  # MiniMax Anthropic endpoint (thinking)
    mistral: ProviderConfig = Field(default_factory=ProviderConfig)
    stepfun: ProviderConfig = Field(default_factory=ProviderConfig)  # Step Fun (阶跃星辰)
    xiaomi_mimo: ProviderConfig = Field(default_factory=ProviderConfig)  # Xiaomi MIMO (小米)
    longcat: ProviderConfig = Field(default_factory=ProviderConfig)  # LongCat
    ant_ling: ProviderConfig = Field(default_factory=ProviderConfig)  # Ant Ling
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)  # AiHubMix API gateway
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig)  # SiliconFlow (硅基流动)
    novita: ProviderConfig = Field(default_factory=ProviderConfig)  # Novita AI
    volcengine: ProviderConfig = Field(default_factory=ProviderConfig)  # VolcEngine (火山引擎)
    volcengine_coding_plan: ProviderConfig = Field(default_factory=ProviderConfig)  # VolcEngine Coding Plan
    byteplus: ProviderConfig = Field(default_factory=ProviderConfig)  # BytePlus (VolcEngine international)
    byteplus_coding_plan: ProviderConfig = Field(default_factory=ProviderConfig)  # BytePlus Coding Plan
    openai_codex: ProviderConfig = Field(default_factory=ProviderConfig, exclude=True)  # OpenAI Codex (OAuth)
    github_copilot: ProviderConfig = Field(default_factory=ProviderConfig, exclude=True)  # Github Copilot (OAuth)
    qianfan: ProviderConfig = Field(default_factory=ProviderConfig)  # Qianfan (百度千帆)
    nvidia: ProviderConfig = Field(default_factory=ProviderConfig)  # NVIDIA NIM (nvapi- keys)


class HeartbeatConfig(Base):
    """Heartbeat service configuration."""

    enabled: bool = True
    interval_s: int = 30 * 60  # 30 minutes
    keep_recent_messages: int = 8


class ApiConfig(Base):
    """OpenAI-compatible API server configuration."""

    host: str = "127.0.0.1"  # Safer default: local-only bind.
    port: int = 8900
    timeout: float = 120.0  # Per-request timeout in seconds.


class GatewayConfig(Base):
    """Gateway/server configuration."""

    host: str = "127.0.0.1"  # Safer default: local-only bind.
    port: int = 18790
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class MCPServerConfig(Base):
    """MCP server connection configuration (stdio or HTTP)."""

    type: Literal["stdio", "sse", "streamableHttp"] | None = None  # auto-detected if omitted
    command: str = ""  # Stdio: command to run (e.g. "npx")
    args: list[str] = Field(default_factory=list)  # Stdio: command arguments
    env: dict[str, str] = Field(default_factory=dict)  # Stdio: extra env vars
    url: str = ""  # HTTP/SSE: endpoint URL
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP/SSE: custom headers
    tool_timeout: int = 30  # seconds before a tool call is cancelled
    enabled_tools: list[str] = Field(default_factory=lambda: ["*"])  # Only register these tools; accepts raw MCP names or wrapped mcp_<server>_<tool> names; ["*"] = all tools; [] = no tools


def _lazy_default(module_path: str, class_name: str) -> Any:
    """Deferred import helper for ToolsConfig default factories."""
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


class ToolsConfig(Base):
    """Tools configuration.

    Field types for tool-specific sub-configs are resolved via model_rebuild()
    at the bottom of this file to avoid circular imports (tool modules import
    Base from schema.py).
    """

    web: WebToolsConfig = Field(default_factory=lambda: _lazy_default("nanobot.agent.tools.web", "WebToolsConfig"))
    exec: ExecToolConfig = Field(default_factory=lambda: _lazy_default("nanobot.agent.tools.shell", "ExecToolConfig"))
    cli_apps: CliAppsToolConfig = Field(default_factory=lambda: _lazy_default("nanobot.agent.tools.cli_apps", "CliAppsToolConfig"))
    my: MyToolConfig = Field(default_factory=lambda: _lazy_default("nanobot.agent.tools.self", "MyToolConfig"))
    image_generation: ImageGenerationToolConfig = Field(
        default_factory=lambda: _lazy_default("nanobot.agent.tools.image_generation", "ImageGenerationToolConfig"),
    )
    restrict_to_workspace: bool = False  # restrict all tool access to workspace directory
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)
    ssrf_whitelist: list[str] = Field(default_factory=list)  # CIDR ranges to exempt from SSRF blocking (e.g. ["100.64.0.0/10"] for Tailscale)


class Config(BaseSettings):
    """Root configuration for nanobot."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    model_presets: dict[str, ModelPresetConfig] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("modelPresets", "model_presets"),
    )

    @model_validator(mode="after")
    def _validate_model_preset(self) -> "Config":
        if "default" in self.model_presets:
            raise ValueError("model_preset name 'default' is reserved for agents.defaults")
        name = self.agents.defaults.model_preset
        if name and name != "default" and name not in self.model_presets:
            raise ValueError(f"model_preset {name!r} not found in model_presets")
        for fallback in self.agents.defaults.fallback_models:
            if isinstance(fallback, str) and fallback not in self.model_presets:
                raise ValueError(f"fallback_models entry {fallback!r} not found in model_presets")
        return self

    def resolve_default_preset(self) -> ModelPresetConfig:
        """Return the implicit `default` preset from agents.defaults fields."""
        d = self.agents.defaults
        return ModelPresetConfig(
            model=d.model, provider=d.provider, max_tokens=d.max_tokens,
            context_window_tokens=d.context_window_tokens,
            temperature=d.temperature, reasoning_effort=d.reasoning_effort,
        )

    def resolve_preset(self, name: str | None = None) -> ModelPresetConfig:
        """Return effective model params from a named preset or the implicit default."""
        name = self.agents.defaults.model_preset if name is None else name
        if not name or name == "default":
            return self.resolve_default_preset()
        if name not in self.model_presets:
            raise KeyError(f"model_preset {name!r} not found in model_presets")
        return self.model_presets[name]

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()

    def _match_provider(
        self, model: str | None = None,
        *,
        preset: ModelPresetConfig | None = None,
    ) -> tuple["ProviderConfig | None", str | None]:
        """Match provider config and its registry name. Returns (config, spec_name)."""
        from nanobot.providers.registry import PROVIDERS, find_by_name

        resolved = preset or self.resolve_preset()
        forced = resolved.provider
        if forced != "auto":
            spec = find_by_name(forced)
            if spec:
                p = getattr(self.providers, spec.name, None)
                return (p, spec.name) if p else (None, None)
            return None, None

        model_lower = (model or resolved.model).lower()
        model_normalized = model_lower.replace("-", "_")
        model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
        normalized_prefix = model_prefix.replace("-", "_")

        def _kw_matches(kw: str) -> bool:
            kw = kw.lower()
            return kw in model_lower or kw.replace("-", "_") in model_normalized

        # Explicit provider prefix wins — prevents `github-copilot/...codex` matching openai_codex.
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and model_prefix and normalized_prefix == spec.name:
                if spec.is_oauth or spec.is_local or spec.is_direct or p.api_key:
                    return p, spec.name

        # Match by keyword (order follows PROVIDERS registry)
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and any(_kw_matches(kw) for kw in spec.keywords):
                if spec.is_oauth or spec.is_local or spec.is_direct or p.api_key:
                    return p, spec.name

        # Fallback: configured local providers can route models without
        # provider-specific keywords (for example plain "llama3.2" on Ollama).
        # Prefer providers whose detect_by_base_keyword matches the configured api_base
        # (e.g. Ollama's "11434" in "http://localhost:11434") over plain registry order.
        local_fallback: tuple[ProviderConfig, str] | None = None
        for spec in PROVIDERS:
            if not spec.is_local:
                continue
            p = getattr(self.providers, spec.name, None)
            if not (p and p.api_base):
                continue
            if spec.detect_by_base_keyword and spec.detect_by_base_keyword in p.api_base:
                return p, spec.name
            if local_fallback is None:
                local_fallback = (p, spec.name)
        if local_fallback:
            return local_fallback

        # Fallback: gateways first, then others (follows registry order)
        # OAuth providers are NOT valid fallbacks — they require explicit model selection
        for spec in PROVIDERS:
            if spec.is_oauth:
                continue
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p, spec.name
        return None, None

    def get_provider(
        self,
        model: str | None = None,
        *,
        preset: ModelPresetConfig | None = None,
    ) -> ProviderConfig | None:
        """Get matched provider config (api_key, api_base, extra_headers). Falls back to first available."""
        p, _ = self._match_provider(model, preset=preset)
        return p

    def get_provider_name(
        self,
        model: str | None = None,
        *,
        preset: ModelPresetConfig | None = None,
    ) -> str | None:
        """Get the registry name of the matched provider (e.g. "deepseek", "openrouter")."""
        _, name = self._match_provider(model, preset=preset)
        return name

    def get_api_key(
        self,
        model: str | None = None,
        *,
        preset: ModelPresetConfig | None = None,
    ) -> str | None:
        """Get API key for the given model. Falls back to first available key."""
        p = self.get_provider(model, preset=preset)
        return p.api_key if p else None

    def get_api_base(
        self,
        model: str | None = None,
        *,
        preset: ModelPresetConfig | None = None,
    ) -> str | None:
        """Get API base URL for the given model, falling back to the provider default when present."""
        from nanobot.providers.registry import find_by_name

        p, name = self._match_provider(model, preset=preset)
        if p and p.api_base:
            return p.api_base
        if name:
            spec = find_by_name(name)
            if spec and spec.default_api_base:
                return spec.default_api_base
        return None

    model_config = ConfigDict(env_prefix="NANOBOT_", env_nested_delimiter="__")


def _resolve_tool_config_refs() -> None:
    """Resolve forward references in ToolsConfig by importing tool config classes.

    Must be called after all modules are loaded (breaks circular imports).
    Re-exports the classes into this module's namespace so existing imports
    like ``from nanobot.config.schema import ExecToolConfig`` continue to work.
    """
    import sys

    from nanobot.agent.tools.cli_apps import CliAppsToolConfig
    from nanobot.agent.tools.image_generation import ImageGenerationToolConfig
    from nanobot.agent.tools.self import MyToolConfig
    from nanobot.agent.tools.shell import ExecToolConfig
    from nanobot.agent.tools.web import WebFetchConfig, WebSearchConfig, WebToolsConfig

    # Re-export into this module's namespace
    mod = sys.modules[__name__]
    mod.ExecToolConfig = ExecToolConfig  # type: ignore[attr-defined]
    mod.CliAppsToolConfig = CliAppsToolConfig  # type: ignore[attr-defined]
    mod.WebToolsConfig = WebToolsConfig  # type: ignore[attr-defined]
    mod.WebSearchConfig = WebSearchConfig  # type: ignore[attr-defined]
    mod.WebFetchConfig = WebFetchConfig  # type: ignore[attr-defined]
    mod.MyToolConfig = MyToolConfig  # type: ignore[attr-defined]
    mod.ImageGenerationToolConfig = ImageGenerationToolConfig  # type: ignore[attr-defined]

    ToolsConfig.model_rebuild()
    Config.model_rebuild()


# Eagerly resolve when the import chain allows it (no circular deps at this
# point).  If it fails (first import triggers a cycle), the rebuild will
# happen lazily when Config/ToolsConfig is first used at runtime.
try:
    _resolve_tool_config_refs()
except ImportError:
    pass
