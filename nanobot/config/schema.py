"""Configuration schema using Pydantic."""

from pathlib import Path

from pydantic import BaseModel, Field
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
    proxy: str | None = (
        None  # HTTP/SOCKS5 proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"
    )


class FeishuConfig(BaseModel):
    """Feishu/Lark channel configuration using WebSocket long connection."""

    enabled: bool = False
    app_id: str = ""  # App ID from Feishu Open Platform
    app_secret: str = ""  # App Secret from Feishu Open Platform
    encrypt_key: str = ""  # Encrypt Key for event subscription (optional)
    verification_token: str = ""  # Verification Token for event subscription (optional)
    allow_from: list[str] = Field(default_factory=list)  # Allowed user open_ids


class DiscordConfig(BaseModel):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""  # Bot token from Discord Developer Portal
    guild_id: str = ""  # The server ID where nanobot lives
    default_channel_id: str = ""  # Channel for proactive messages (cron, notifications)
    trigger_word: str = "nano"  # Respond when this word appears in messages
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs
    context_messages: int = Field(default=0, alias="contextMessages")  # Recent channel messages
    # Reaction emojis (customizable)
    emoji_processing: str = "\u23f3"  # Hourglass
    emoji_complete: str = "\u2705"  # Checkmark
    emoji_error: str = "\u274c"  # X mark


class ChannelsConfig(BaseModel):
    """Configuration for chat channels."""

    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)


class ContextConfig(BaseModel):
    """Context window management configuration."""

    max_context_tokens: int = Field(default=100000, alias="maxContextTokens")
    system_prompt_budget: int = Field(default=20000, alias="systemPromptBudget")
    history_budget: int = Field(default=60000, alias="historyBudget")
    tool_result_budget: int = Field(default=15000, alias="toolResultBudget")
    safety_margin: int = Field(default=5000, alias="safetyMargin")


class CompactionConfig(BaseModel):
    """Message compaction configuration."""

    enabled: bool = True
    threshold: float = 0.8  # Compact at 80% capacity
    model: str | None = None  # None = use main model
    provider: str | None = None  # Named provider from providers section
    keep_recent: int = Field(default=10, alias="keepRecent")


class MemoryConfig(BaseModel):
    """Semantic memory configuration."""

    enabled: bool = True
    embedding_model: str = Field(default="openai/text-embedding-3-small", alias="embeddingModel")
    embedding_provider: str | None = Field(default=None, alias="embeddingProvider")
    extraction_model: str | None = Field(default=None, alias="extractionModel")
    extraction_provider: str | None = Field(default=None, alias="extractionProvider")
    consolidation_provider: str | None = Field(default=None, alias="consolidationProvider")
    index_conversations: bool = Field(default=True, alias="indexConversations")
    extract_facts: bool = Field(default=True, alias="extractFacts")
    auto_recall: bool = Field(default=True, alias="autoRecall")
    search_top_k: int = Field(default=5, alias="searchTopK")
    min_similarity: float = Field(default=0.5, alias="minSimilarity")
    db_path: str = Field(default="~/.nanobot/memory/vectors.db", alias="dbPath")
    recency_weight: float = Field(default=0.005, alias="recencyWeight")
    enable_core_memory: bool = Field(default=True, alias="enableCoreMemory")
    enable_entities: bool = Field(default=True, alias="enableEntities")
    enable_consolidation: bool = Field(default=True, alias="enableConsolidation")
    enable_proactive: bool = Field(default=False, alias="enableProactive")
    entities_db_path: str = Field(default="~/.nanobot/memory/entities.db", alias="entitiesDbPath")


class MemoryExtractionConfig(BaseModel):
    """Configuration for automatic memory extraction and consolidation."""

    enabled: bool = False
    extraction_model: str = Field(default="gpt-4o-mini", alias="extractionModel")
    embedding_model: str = Field(default="text-embedding-3-small", alias="embeddingModel")
    max_memories: int = Field(default=1000, alias="maxMemories")
    extraction_interval: int = Field(default=10, alias="extractionInterval")
    max_facts_per_extraction: int = Field(default=5, alias="maxFactsPerExtraction")
    max_lessons_per_extraction: int = Field(default=3, alias="maxLessonsPerExtraction")
    enable_pre_compaction_flush: bool = Field(default=True, alias="enablePreCompactionFlush")
    enable_tool_lessons: bool = Field(default=True, alias="enableToolLessons")
    candidate_threshold: float = Field(default=0.7, alias="candidateThreshold")


class DaemonConfig(BaseModel):
    """Daemon mode: three-tier autonomous agent execution."""

    enabled: bool = True
    interval: int = Field(default=300, alias="interval")
    triage_model: str | None = Field(default=None, alias="triageModel")
    triage_provider: str | None = Field(default=None, alias="triageProvider")
    execution_model: str | None = Field(default=None, alias="executionModel")
    execution_provider: str | None = Field(default=None, alias="executionProvider")
    strategy_file: str = Field(default="HEARTBEAT.md", alias="strategyFile")
    max_iterations: int = Field(default=25, alias="maxIterations")
    cooldown_after_action: int = Field(default=600, alias="cooldownAfterAction")


class AgentDefaults(BaseModel):
    """Default agent configuration."""

    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    provider: str | None = None  # Named provider from providers section
    max_tokens: int = 8192
    temperature: float = 0.7
    max_tool_iterations: int = 20
    context: ContextConfig = Field(default_factory=ContextConfig)
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    memory_extraction: MemoryExtractionConfig = Field(
        default_factory=MemoryExtractionConfig, alias="memoryExtraction"
    )
    daemon: DaemonConfig = Field(default_factory=DaemonConfig, alias="daemon")


class AgentsConfig(BaseModel):
    """Agent configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(BaseModel):
    """LLM provider configuration."""

    api_key: str = ""
    api_base: str | None = None


class ProvidersConfig(BaseModel):
    """Configuration for LLM providers."""

    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
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


class ExecToolConfig(BaseModel):
    """Shell exec tool configuration."""

    timeout: int = 60
    restrict_to_workspace: bool = False  # If true, block commands accessing paths outside workspace


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    command: str  # e.g., "npx", "uvx", "python"
    args: list[str] = Field(default_factory=list)  # Command arguments
    env: dict[str, str] = Field(default_factory=dict)  # Environment variables
    enabled: bool = True
    timeout: int = 30  # Startup/request timeout in seconds


class MCPToolConfig(BaseModel):
    """Configuration for an individual MCP tool."""

    enabled: bool = True  # Can disable specific tools


class MCPConfig(BaseModel):
    """MCP (Model Context Protocol) configuration."""

    enabled: bool = False
    servers: dict[str, MCPServerConfig] = Field(default_factory=dict)
    tools: dict[str, MCPToolConfig] = Field(default_factory=dict)  # Tool-specific overrides


class ToolsConfig(BaseModel):
    """Tools configuration."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)


class Config(BaseSettings):
    """Root configuration for nanobot."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()

    def get_api_key(self) -> str | None:
        """Get API key in priority order: OpenRouter > Anthropic > OpenAI > Gemini > Zhipu > Groq > vLLM."""
        return (
            self.providers.openrouter.api_key
            or self.providers.anthropic.api_key
            or self.providers.openai.api_key
            or self.providers.gemini.api_key
            or self.providers.zhipu.api_key
            or self.providers.groq.api_key
            or self.providers.vllm.api_key
            or None
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

    def resolve_provider(self, name: str | None = None) -> tuple[str | None, str | None]:
        """Resolve (api_key, api_base) for a named provider or the default.

        Args:
            name: Provider name from the providers section (e.g. "openrouter", "zhipu").
                  If None, falls back to priority-based resolution.

        Returns:
            Tuple of (api_key, api_base).
        """
        if name:
            provider = getattr(self.providers, name, None)
            if provider and provider.api_key:
                api_base = provider.api_base
                if name == "openrouter" and not api_base:
                    api_base = "https://openrouter.ai/api/v1"
                return provider.api_key, api_base
        return self.get_api_key(), self.get_api_base()

    class Config:
        env_prefix = "NANOBOT_"
        env_nested_delimiter = "__"
