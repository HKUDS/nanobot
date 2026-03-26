"""Configuration schema using Pydantic."""
# size-exception: data definitions — Pydantic models with many fields by nature

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings, SettingsConfigDict

from nanobot.config.providers_registry import PROVIDERS, find_by_name


class Base(BaseModel):
    """Base model that accepts both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WhatsAppConfig(Base):
    """WhatsApp channel configuration."""

    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    bridge_token: str = ""  # Shared token for bridge auth (optional, recommended)
    allow_from: list[str] = Field(default_factory=list)  # Allowed phone numbers


class TelegramConfig(Base):
    """Telegram channel configuration."""

    enabled: bool = False
    token: str = ""  # Bot token from @BotFather
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs or usernames
    proxy: str | None = (
        None  # HTTP/SOCKS5 proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"
    )
    reply_to_message: bool = False  # If true, bot replies quote the original message


class DiscordConfig(Base):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""  # Bot token from Discord Developer Portal
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377  # GUILDS + GUILD_MESSAGES + DIRECT_MESSAGES + MESSAGE_CONTENT


class EmailConfig(Base):
    """Email channel configuration (IMAP inbound + SMTP outbound)."""

    enabled: bool = False
    consent_granted: bool = False  # Explicit owner permission to access mailbox data

    # IMAP (receive)
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_use_ssl: bool = True

    # SMTP (send)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    from_address: str = ""

    # Behavior
    auto_reply_enabled: bool = (
        True  # If false, inbound email is read but no automatic reply is sent
    )
    poll_interval_seconds: int = 30
    mark_seen: bool = True
    max_body_chars: int = 12000
    subject_prefix: str = "Re: "
    allow_from: list[str] = Field(default_factory=list)  # Allowed sender email addresses
    allow_to: list[str] = Field(default_factory=list)  # Allowed recipient email addresses
    proactive_send_policy: str = "known_only"  # "known_only", "allowlist", or "open"


class SlackDMConfig(Base):
    """Slack DM policy configuration."""

    enabled: bool = True
    policy: str = "open"  # "open" or "allowlist"
    allow_from: list[str] = Field(default_factory=list)  # Allowed Slack user IDs


class SlackConfig(Base):
    """Slack channel configuration."""

    enabled: bool = False
    mode: str = "socket"  # "socket" supported
    webhook_path: str = "/slack/events"
    bot_token: str = ""  # xoxb-...
    app_token: str = ""  # xapp-...
    user_token_read_only: bool = True
    reply_in_thread: bool = True
    react_emoji: str = "eyes"
    group_policy: str = "mention"  # "mention", "open", "allowlist"
    group_allow_from: list[str] = Field(default_factory=list)  # Allowed channel IDs if allowlist
    dm: SlackDMConfig = Field(default_factory=SlackDMConfig)


class WebChannelConfig(Base):
    """Web UI channel configuration."""

    enabled: bool = False
    host: str = "127.0.0.1"  # Bind address for the web UI server
    port: int = 8000  # Web UI port (separate from gateway health port)
    api_key: str = ""  # SEC-06: Bearer token for /api/* routes; empty = no auth (dev only)
    rate_limit_per_minute: int = 60  # Max API requests per IP per minute (0 = disabled)


class ChannelsConfig(Base):
    """Configuration for chat channels."""

    send_progress: bool = True  # stream agent's text progress to the channel
    send_tool_hints: bool = False  # stream tool-call hints (e.g. read_file("…"))
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    web: WebChannelConfig = Field(default_factory=WebChannelConfig)


class VectorSyncConfig(Base):
    """Vector sync adapter tuning (legacy mem0, now SQLite-backed)."""

    user_id: str = "nanobot"  # Vector user namespace (was MEM0_USER_ID)
    add_debug: bool = False  # Log add_text diagnostics (was MEM0_ADD_DEBUG)
    verify_write: bool = True  # Verify vector writes via count (was MEM0_VERIFY_WRITE)
    force_infer: bool = False  # Force infer=True mode (was MEM0_FORCE_INFER_TRUE)


class RerankerConfig(Base):
    """Cross-encoder re-ranker tuning."""

    mode: str = "enabled"  # enabled | shadow | disabled (was NANOBOT_RERANKER_MODE)
    alpha: float = 0.5  # Blend weight 0.0–1.0 (was NANOBOT_RERANKER_ALPHA)
    model: str = "onnx:ms-marco-MiniLM-L-6-v2"  # Model name (was NANOBOT_RERANKER_MODEL)


class MissionConfig(Base):
    """Background mission tuning."""

    max_concurrent: int = 3
    max_iterations: int = 15
    result_max_chars: int = 4000


class MemorySectionWeights(Base):
    """Per-section token budget weights for one retrieval intent.

    Values are normalised to sum to 1.0 at allocation time — only relative
    ratios matter. An empty dict means 'use DEFAULT_SECTION_WEIGHTS'.
    """

    long_term: float = Field(default=0.0, ge=0.0)
    profile: float = Field(default=0.0, ge=0.0)
    semantic: float = Field(default=0.0, ge=0.0)
    episodic: float = Field(default=0.0, ge=0.0)
    reflection: float = Field(default=0.0, ge=0.0)
    graph: float = Field(default=0.0, ge=0.0)
    unresolved: float = Field(default=0.0, ge=0.0)


class AgentDefaults(Base):
    """Default agent configuration."""

    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    temperature: float = 0.1
    max_tool_iterations: int = 40
    memory_window: int = 100
    memory_retrieval_k: int = 6
    memory_token_budget: int = 900
    memory_uncertainty_threshold: float = 0.6
    memory_enable_contradiction_check: bool = True
    memory_conflict_auto_resolve_gap: float = 0.25
    memory_rollout_mode: str = "enabled"  # enabled|shadow|disabled
    memory_type_separation_enabled: bool = True
    memory_router_enabled: bool = True
    memory_reflection_enabled: bool = True
    memory_shadow_mode: bool = False
    memory_shadow_sample_rate: float = 0.2
    memory_vector_health_enabled: bool = True
    memory_auto_reindex_on_empty_vector: bool = True
    memory_history_fallback_enabled: bool = False
    memory_fallback_allowed_sources: list[str] = Field(
        default_factory=lambda: ["profile", "events", "vector_search"]
    )
    memory_fallback_max_summary_chars: int = 280
    memory_rollout_gate_min_recall_at_k: float = 0.55
    memory_rollout_gate_min_precision_at_k: float = 0.25
    memory_rollout_gate_max_avg_memory_context_tokens: float = 1400.0
    memory_rollout_gate_max_history_fallback_ratio: float = 0.05

    # Tool-result truncation
    tool_result_max_chars: int = 2000
    tool_result_context_tokens: int = 500

    # Vision / multimodal
    vision_model: str = "gpt-4o-mini"

    # Knowledge graph (networkx + JSON persistence)
    graph_enabled: bool = False

    # Reranker
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)

    # Reranker / vector sync
    vector_sync: VectorSyncConfig = Field(default_factory=VectorSyncConfig)
    vector_raw_turn_ingestion: bool = True  # LAN-208: gate raw conversation turn ingestion

    # Missions
    mission: MissionConfig = Field(default_factory=MissionConfig)

    # Cost guardrails
    max_session_cost_usd: float = 0.0  # 0 = disabled; >0 raises BudgetExceededError when exceeded
    max_session_wall_time_seconds: int = 0  # 0 = disabled; >0 terminates session after N seconds

    # Delegation cost guard (LAN-83)
    max_delegation_depth: int = 8  # Max total delegations per turn (0 = unlimited)

    # Memory section token budget weights (keyed by intent name)
    memory_section_weights: dict[str, MemorySectionWeights] = Field(default_factory=dict)


class AgentConfig(Base):
    """Unified agent runtime configuration.

    Passed directly to ``AgentLoop.__init__`` so that callers no longer need
    to forward 30+ keyword arguments individually.  Build one from an
    ``AgentDefaults`` instance with ``AgentConfig.from_defaults()``.
    """

    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    temperature: float = 0.1
    max_iterations: int = 40
    context_window_tokens: int = 128_000

    # Memory
    memory_window: int = 100
    memory_retrieval_k: int = 6
    memory_token_budget: int = 900
    memory_md_token_cap: int = 1500  # max tokens for memory snapshot injection; 0 = unlimited
    memory_uncertainty_threshold: float = 0.6
    memory_enable_contradiction_check: bool = True
    memory_conflict_auto_resolve_gap: float = 0.25
    memory_rollout_mode: str = "enabled"
    memory_type_separation_enabled: bool = True
    memory_router_enabled: bool = True
    memory_reflection_enabled: bool = True
    memory_shadow_mode: bool = False
    memory_shadow_sample_rate: float = 0.2
    memory_vector_health_enabled: bool = True
    memory_auto_reindex_on_empty_vector: bool = True
    memory_history_fallback_enabled: bool = False
    memory_fallback_allowed_sources: list[str] = Field(
        default_factory=lambda: ["profile", "events", "vector_search"]
    )
    memory_fallback_max_summary_chars: int = 280
    memory_rollout_gate_min_recall_at_k: float = 0.55
    memory_rollout_gate_min_precision_at_k: float = 0.25
    memory_rollout_gate_max_avg_memory_context_tokens: float = 1400.0
    memory_rollout_gate_max_history_fallback_ratio: float = 0.05

    # Tool-result truncation
    tool_result_max_chars: int = 2000
    tool_result_context_tokens: int = 500

    # Tool-result cache & summary
    tool_summary_model: str = ""  # LLM for summarising large tool results; empty = main model

    # Planning & verification (Step 1 & 2)
    planning_enabled: bool = True
    verification_mode: str = "on_uncertainty"  # always | on_uncertainty | off

    # Feature flags (can be overridden by root FeaturesConfig kill-switches)
    delegation_enabled: bool = True
    memory_enabled: bool = True
    skills_enabled: bool = True
    streaming_enabled: bool = True

    # Micro-extraction: per-turn lightweight memory extraction
    micro_extraction_enabled: bool = False  # Feature gate (opt-in)
    micro_extraction_model: str | None = None  # None = "gpt-4o-mini"

    # Summarization-based compression (Step 3)
    summary_model: str | None = (
        None  # None = use main model; set e.g. "gpt-4o-mini" for cheaper compression
    )

    # Shell security (Step 11)
    shell_mode: str = "denylist"  # allowlist | denylist

    # Per-message timeout (seconds); 0 = no timeout
    message_timeout: int = 300

    # Knowledge graph (networkx + JSON persistence)
    graph_enabled: bool = False

    # Reranker / vector sync
    reranker_mode: str = "enabled"
    reranker_alpha: float = 0.5
    reranker_model: str = "onnx:ms-marco-MiniLM-L-6-v2"
    vector_user_id: str = "nanobot"
    vector_add_debug: bool = False
    vector_verify_write: bool = True
    vector_force_infer: bool = False
    vector_raw_turn_ingestion: bool = True  # LAN-208: gate raw conversation turn ingestion

    # Vision / multimodal
    vision_model: str = "gpt-4o-mini"

    # Tools
    restrict_to_workspace: bool = True

    # Missions
    mission_max_concurrent: int = 3
    mission_max_iterations: int = 15
    mission_result_max_chars: int = 4000

    # Cost guardrails
    max_session_cost_usd: float = 0.0  # 0 = disabled; >0 raises BudgetExceededError when exceeded
    max_session_wall_time_seconds: int = 0  # 0 = disabled; >0 terminates session after N seconds

    # Delegation cost guard (LAN-83)
    max_delegation_depth: int = 8  # Max total delegations per turn (0 = unlimited)

    # Memory section token budget weights (keyed by intent name)
    memory_section_weights: dict[str, MemorySectionWeights] = Field(default_factory=dict)

    @classmethod
    def from_defaults(cls, defaults: "AgentDefaults", **overrides: Any) -> "AgentConfig":
        """Build an ``AgentConfig`` from the ``AgentDefaults`` section of the config file.

        .. warning:: Adding a new config field requires **three** coordinated steps:

            1. Add the field to :class:`AgentDefaults` with its default value.
            2. Add the corresponding mapping entry in the ``data`` dict below
               (``"agent_config_key": defaults.agent_defaults_key``).
            3. Add the field to :class:`AgentConfig` with a matching type.

            Skipping any step causes silent misconfiguration — the field will
            silently use the ``AgentConfig`` default instead of the user's value.
        """
        data = {
            "workspace": defaults.workspace,
            "model": defaults.model,
            "max_tokens": defaults.max_tokens,
            "temperature": defaults.temperature,
            "max_iterations": defaults.max_tool_iterations,
            "memory_window": defaults.memory_window,
            "memory_retrieval_k": defaults.memory_retrieval_k,
            "memory_token_budget": defaults.memory_token_budget,
            "memory_uncertainty_threshold": defaults.memory_uncertainty_threshold,
            "memory_enable_contradiction_check": defaults.memory_enable_contradiction_check,
            "memory_conflict_auto_resolve_gap": defaults.memory_conflict_auto_resolve_gap,
            "memory_rollout_mode": defaults.memory_rollout_mode,
            "memory_type_separation_enabled": defaults.memory_type_separation_enabled,
            "memory_router_enabled": defaults.memory_router_enabled,
            "memory_reflection_enabled": defaults.memory_reflection_enabled,
            "memory_shadow_mode": defaults.memory_shadow_mode,
            "memory_shadow_sample_rate": defaults.memory_shadow_sample_rate,
            "memory_vector_health_enabled": defaults.memory_vector_health_enabled,
            "memory_auto_reindex_on_empty_vector": defaults.memory_auto_reindex_on_empty_vector,
            "memory_history_fallback_enabled": defaults.memory_history_fallback_enabled,
            "memory_fallback_allowed_sources": defaults.memory_fallback_allowed_sources,
            "memory_fallback_max_summary_chars": defaults.memory_fallback_max_summary_chars,
            "memory_rollout_gate_min_recall_at_k": defaults.memory_rollout_gate_min_recall_at_k,
            "memory_rollout_gate_min_precision_at_k": defaults.memory_rollout_gate_min_precision_at_k,
            "memory_rollout_gate_max_avg_memory_context_tokens": defaults.memory_rollout_gate_max_avg_memory_context_tokens,
            "memory_rollout_gate_max_history_fallback_ratio": defaults.memory_rollout_gate_max_history_fallback_ratio,
            "tool_result_max_chars": defaults.tool_result_max_chars,
            "tool_result_context_tokens": defaults.tool_result_context_tokens,
            "graph_enabled": defaults.graph_enabled,
            "reranker_mode": defaults.reranker.mode,
            "reranker_alpha": defaults.reranker.alpha,
            "reranker_model": defaults.reranker.model,
            "vector_user_id": defaults.vector_sync.user_id,
            "vector_add_debug": defaults.vector_sync.add_debug,
            "vector_verify_write": defaults.vector_sync.verify_write,
            "vector_force_infer": defaults.vector_sync.force_infer,
            "vector_raw_turn_ingestion": defaults.vector_raw_turn_ingestion,
            "vision_model": defaults.vision_model,
            "mission_max_concurrent": defaults.mission.max_concurrent,
            "mission_max_iterations": defaults.mission.max_iterations,
            "mission_result_max_chars": defaults.mission.result_max_chars,
            "max_session_cost_usd": defaults.max_session_cost_usd,
            "max_session_wall_time_seconds": defaults.max_session_wall_time_seconds,
            "max_delegation_depth": defaults.max_delegation_depth,
            "memory_section_weights": defaults.memory_section_weights,
        }
        data.update(overrides)
        return cls(**data)  # type: ignore[arg-type]

    @property
    def workspace_path(self) -> "Path":
        from pathlib import Path

        return Path(self.workspace).expanduser()


class AgentsConfig(Base):
    """Agent configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)
    routing: "RoutingConfig" = Field(default_factory=lambda: RoutingConfig())


class AgentRoleConfig(Base):
    """Configuration for a specialized agent role."""

    name: str  # Unique role identifier (e.g. "code", "research")
    description: str = ""  # What this agent specializes in (used in routing prompt)
    model: str | None = None  # Override model (None = use default)
    temperature: float | None = None  # Override temperature
    system_prompt: str = ""  # Additional system prompt injected after core identity
    allowed_tools: list[str] | None = None  # Tool allowlist (None = all tools)
    denied_tools: list[str] | None = None  # Tool denylist
    skills: list[str] = Field(default_factory=list)  # Skill names to always load
    max_iterations: int | None = None  # Override iteration limit
    enabled: bool = True


class RoutingConfig(Base):
    """Multi-agent routing configuration."""

    enabled: bool = False  # Feature gate (disabled by default)
    classifier_model: str | None = None  # Cheap model for classification (e.g. "gpt-4o-mini")
    roles: list[AgentRoleConfig] = Field(default_factory=list)  # User-defined agent roles
    default_role: str = "general"  # Fallback when classifier is uncertain
    confidence_threshold: float = 0.6  # Below this confidence, fall back to default_role


class ProviderConfig(Base):
    """LLM provider configuration."""

    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None  # Custom headers (e.g. APP-Code for AiHubMix)


class ProvidersConfig(Base):
    """Configuration for LLM providers."""

    custom: ProviderConfig = Field(default_factory=ProviderConfig)  # Any OpenAI-compatible endpoint
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)  # 阿里云通义千问
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)  # AiHubMix API gateway
    siliconflow: ProviderConfig = Field(
        default_factory=ProviderConfig
    )  # SiliconFlow (硅基流动) API gateway
    volcengine: ProviderConfig = Field(
        default_factory=ProviderConfig
    )  # VolcEngine (火山引擎) API gateway
    openai_codex: ProviderConfig = Field(default_factory=ProviderConfig)  # OpenAI Codex (OAuth)
    github_copilot: ProviderConfig = Field(default_factory=ProviderConfig)  # Github Copilot (OAuth)


class HeartbeatConfig(Base):
    """Heartbeat service configuration."""

    enabled: bool = False
    interval_s: int = 30 * 60  # 30 minutes
    model: str | None = None  # Override agent default model for heartbeat


class GatewayConfig(Base):
    """Gateway/server configuration."""

    host: str = "0.0.0.0"
    port: int = 18790
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class WebSearchConfig(Base):
    """Web search tool configuration."""

    api_key: str = ""  # Brave Search API key
    max_results: int = 5


class WebToolsConfig(Base):
    """Web tools configuration."""

    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(Base):
    """Shell exec tool configuration."""

    timeout: int = 60
    shell_mode: str = "denylist"  # "denylist" | "allowlist" — propagated to delegated agents


class MCPServerConfig(Base):
    """MCP server connection configuration (stdio or HTTP)."""

    command: str = ""  # Stdio: command to run (e.g. "npx")
    args: list[str] = Field(default_factory=list)  # Stdio: command arguments
    env: dict[str, str] = Field(default_factory=dict)  # Stdio: extra env vars
    url: str = ""  # HTTP: streamable HTTP endpoint URL
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP: Custom HTTP Headers
    tool_timeout: int = 30  # Seconds before a tool call is cancelled


class ToolsConfig(Base):
    """Tools configuration."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = True  # If true, restrict all tool access to workspace directory
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


class FeaturesConfig(Base):
    """Feature flags for toggling agent capabilities without code changes."""

    planning_enabled: bool = True
    verification_enabled: bool = True  # master switch; mode set in AgentConfig
    delegation_enabled: bool = True
    memory_enabled: bool = True
    skills_enabled: bool = True
    streaming_enabled: bool = True


class LogConfig(Base):
    """Structured logging configuration."""

    level: str = "INFO"  # Loguru level: TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL
    json_stdout: bool = False  # Emit logs as JSON to stderr (loguru serialize mode)
    json_file: str = ""  # Path to a JSON log file sink (empty = disabled)


class LLMConfig(Base):
    """LLM call tuning — consolidates scattered os.getenv() calls."""

    timeout_s: float = 60.0  # Per-call timeout (was NANOBOT_LLM_TIMEOUT_S)
    max_retries: int = 1  # Retry count (was NANOBOT_LLM_MAX_RETRIES)


class LangfuseConfig(Base):
    """Langfuse observability configuration."""

    enabled: bool = True
    public_key: str = ""
    secret_key: str = ""
    host: str = "https://cloud.langfuse.com"
    environment: str = "development"
    sample_rate: float = 1.0
    debug: bool = False


class Config(BaseSettings):
    """Root configuration for nanobot.

    Supports three configuration sources (highest priority first):

    1. **Environment variables** — prefixed with ``NANOBOT_``, nested via ``__``.
       Example: ``NANOBOT_AGENTS__DEFAULTS__MODEL=gpt-4o``
    2. **``.env`` file** — loaded from the working directory if present.
    3. **``~/.nanobot/config.json``** — loaded by ``load_config()``.
    """

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()

    def _match_provider(
        self, model: str | None = None
    ) -> tuple["ProviderConfig | None", str | None]:
        """Match provider config and its registry name. Returns (config, spec_name)."""
        model_lower = (model or self.agents.defaults.model).lower()
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
                if spec.is_oauth or p.api_key:
                    return p, spec.name

        # Match by keyword (order follows PROVIDERS registry)
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and any(_kw_matches(kw) for kw in spec.keywords):
                if spec.is_oauth or p.api_key:
                    return p, spec.name

        # Fallback: gateways first, then others (follows registry order)
        # OAuth providers are NOT valid fallbacks — they require explicit model selection
        for spec in PROVIDERS:
            if spec.is_oauth:
                continue
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p, spec.name
        return None, None

    def get_provider(self, model: str | None = None) -> ProviderConfig | None:
        """Get matched provider config (api_key, api_base, extra_headers). Falls back to first available."""
        p, _ = self._match_provider(model)
        return p

    def get_provider_name(self, model: str | None = None) -> str | None:
        """Get the registry name of the matched provider (e.g. "deepseek", "openrouter")."""
        _, name = self._match_provider(model)
        return name

    def get_api_key(self, model: str | None = None) -> str | None:
        """Get API key for the given model. Falls back to first available key."""
        p = self.get_provider(model)
        return p.api_key if p else None

    def get_api_base(self, model: str | None = None) -> str | None:
        """Get API base URL for the given model. Applies default URLs for known gateways."""
        p, name = self._match_provider(model)
        if p and p.api_base:
            return p.api_base
        # Only gateways get a default api_base here. Standard providers
        # (like Moonshot) set their base URL via env vars in _setup_env
        # to avoid polluting the global litellm.api_base.
        if name:
            spec = find_by_name(name)
            if spec and spec.is_gateway and spec.default_api_base:
                return spec.default_api_base
        return None

    model_config = SettingsConfigDict(
        env_prefix="NANOBOT_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )
