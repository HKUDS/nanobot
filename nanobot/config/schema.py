"""Configuration schema using Pydantic."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings


class WhatsAppConfig(BaseModel):
    """WhatsApp channel configuration."""
    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    allow_from: list[str] = Field(default_factory=list)  # Allowed phone numbers


class TelegramConfig(BaseModel):
    """Telegram channel configuration."""
    enabled: bool = False
    token: str = ""  # Bot token from @BotFather
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs or usernames
    proxy: str | None = None  # HTTP/SOCKS5 proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"


class FeishuConfig(BaseModel):
    """Feishu/Lark channel configuration using WebSocket long connection."""
    enabled: bool = False
    app_id: str = ""  # App ID from Feishu Open Platform
    app_secret: str = ""  # App Secret from Feishu Open Platform
    encrypt_key: str = ""  # Encrypt Key for event subscription (optional)
    verification_token: str = ""  # Verification Token for event subscription (optional)
    allow_from: list[str] = Field(default_factory=list)  # Allowed user open_ids


class ChannelsConfig(BaseModel):
    """Configuration for chat channels."""
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)


class MemoryConfig(BaseModel):
    """Memory system configuration."""
    enabled: bool = True
    embedding_model: str = Field(default="text-embedding-3-small", description="Model for generating embeddings")
    extraction_model: str = Field(default="gpt-4o-mini", description="Model for fact extraction")
    max_memories: int = Field(default=1000, ge=1, le=100000, description="Maximum memories per namespace")
    namespace: str = Field(default="default", pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    compaction_threshold: int = Field(default=50, ge=10, le=1000, description="Messages before compaction triggers")
    search_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="Minimum similarity for retrieval")
    max_requests_per_minute: int = Field(default=3000, ge=1, le=10000, description="Rate limit for embedding API")
    extraction_interval: int = Field(default=10, ge=1, le=100, description="User messages between extractions")


class AgentDefaults(BaseModel):
    """Default agent configuration."""
    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    temperature: float = 0.7
    max_tool_iterations: int = 20


class AgentsConfig(BaseModel):
    """Agent configuration."""
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(BaseModel):
    """LLM provider configuration."""
    api_key: str = ""
    api_base: str | None = None


class ProvidersConfig(BaseModel):
    """Configuration for LLM providers."""
    model_config = ConfigDict(extra="ignore")  # Allow unknown fields for backwards compat

    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig | None = Field(default=None, description="Deprecated: will be removed in 0.3.0")
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)


class GatewayConfig(BaseModel):
    """Gateway/server configuration."""
    host: str = "0.0.0.0"
    port: int = 18790


class WebSearchConfig(BaseModel):
    """Web search tool configuration."""
    api_key: str = ""  # Brave Search API key
    max_results: int = 5


class WebToolsConfig(BaseModel):
    """Web tools configuration."""
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ToolsConfig(BaseModel):
    """Tools configuration."""
    model_config = ConfigDict(extra="ignore")  # Allow unknown fields for backwards compat

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)


class Config(BaseSettings):
    """Root configuration for nanobot."""
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()

    def get_api_key(self) -> str | None:
        """Get API key in priority order: OpenRouter > Anthropic > OpenAI > Gemini > Zhipu > vLLM.

        Note: Groq support is deprecated and will be removed in 0.3.0.
        """
        # Check for deprecated Groq usage
        if self.providers.groq and self.providers.groq.api_key:
            import warnings
            warnings.warn(
                "Groq provider is deprecated and will be removed in 0.3.0. "
                "Please migrate to OpenRouter or another provider.",
                DeprecationWarning,
                stacklevel=2
            )
            return self.providers.groq.api_key

        return (
            self.providers.openrouter.api_key or
            self.providers.anthropic.api_key or
            self.providers.openai.api_key or
            self.providers.gemini.api_key or
            self.providers.zhipu.api_key or
            self.providers.vllm.api_key or
            None
        )

    def get_api_base(self) -> str | None:
        """Get API base URL if using OpenRouter, Zhipu or vLLM."""
        if self.providers.openrouter.api_key:
            return self.providers.openrouter.api_base or "https://openrouter.ai/api/v1"
        if self.providers.zhipu.api_key:
            return self.providers.zhipu.api_base
        if self.providers.vllm.api_base:
            return self.providers.vllm.api_base
        return None

    class Config:
        env_prefix = "NANOBOT_"
        env_nested_delimiter = "__"
