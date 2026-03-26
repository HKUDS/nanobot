"""Configuration schema using Pydantic."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from nanobot.config.base import Base  # noqa: F401 — re-exported for consumers
from nanobot.config.providers_registry import PROVIDERS, find_by_name

if TYPE_CHECKING:
    from nanobot.config.agent import AgentConfig


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


def _default_agent_config() -> AgentConfig:
    """Lazy import to avoid circular dependency (schema -> agent -> schema)."""
    from nanobot.config import agent as _agent_mod

    return _agent_mod.AgentConfig()


class AgentsConfig(Base):
    """Agent configuration."""

    defaults: "AgentConfig" = Field(default_factory=_default_agent_config)
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


# Resolve forward references now that all submodules import Base from base.py (no cycle).
from nanobot.config.agent import AgentConfig  # noqa: E402

AgentsConfig.model_rebuild(_types_namespace={"AgentConfig": AgentConfig})
