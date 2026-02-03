"""Configuration schema using Pydantic."""

from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class PrefixRule(BaseModel):
    """Prefix rule for filtering messages."""
    phone: str  # Phone number (partial match, e.g., "992247834")
    prefix: str  # Required prefix (e.g., "nano")
    strip: bool = True  # Remove prefix before processing


class WhatsAppConfig(BaseModel):
    """WhatsApp channel configuration."""
    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    allow_from: list[str] = Field(default_factory=list)  # Allowed phone numbers
    prefix_rules: list[PrefixRule] = Field(default_factory=list)  # Require prefix from specific numbers


class TelegramConfig(BaseModel):
    """Telegram channel configuration."""
    enabled: bool = False
    token: str = ""  # Bot token from @BotFather
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs or usernames


class ChannelsConfig(BaseModel):
    """Configuration for chat channels."""
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


class CompactionConfig(BaseModel):
    """Context compaction configuration."""
    enabled: bool = True
    max_context_tokens: int = 128000  # Model's context window


class HindsightConfig(BaseModel):
    """Hindsight memory configuration."""
    enabled: bool = False
    url: str = "http://localhost:8888"
    bank_id: str | None = None  # Defaults to workspace name


class SoulConfig(BaseModel):
    """Soul/personality configuration - loads .md files as system context."""
    enabled: bool = True
    path: str = "~/.nanobot/soul"  # Directory containing soul files
    files: list[str] = Field(default_factory=lambda: [
        "SOUL.md",      # Core personality & rules
        "IDENTITY.md",  # Who the agent is
        "USER.md",      # About the user
        "MEMORY.md",    # Long-term curated memory
        "AGENTS.md",    # Behavior rules
        "TOOLS.md",     # Tool usage notes
    ])
    inject_datetime: bool = True  # Add current date/time to context
    inject_runtime: bool = True   # Add runtime info (model, channel, etc)


class Mem0Config(BaseModel):
    """mem0 semantic memory configuration."""
    enabled: bool = False
    storage_path: str | None = None  # Path for vector DB, None = in-memory
    llm_provider: str = "anthropic"  # anthropic, openai, etc
    llm_model: str = "claude-sonnet-4-20250514"  # Model for memory operations
    auto_add: bool = True  # Auto-add memories after each conversation
    auto_recall: bool = True  # Auto-recall relevant memories before responding
    recall_limit: int = 5  # Max memories to recall


class AgentDefaults(BaseModel):
    """Default agent configuration."""
    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    temperature: float = 0.7
    max_tool_iterations: int = 20
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    hindsight: HindsightConfig = Field(default_factory=HindsightConfig)
    soul: SoulConfig = Field(default_factory=SoulConfig)
    mem0: Mem0Config = Field(default_factory=Mem0Config)


class AgentsConfig(BaseModel):
    """Agent configuration."""
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(BaseModel):
    """LLM provider configuration."""
    api_key: str = ""
    api_base: str | None = None


class ClaudeCliConfig(BaseModel):
    """Claude CLI provider configuration (uses Claude Code subscription)."""
    enabled: bool = False
    command: str = "claude"  # Path to claude CLI
    default_model: str = "opus"  # opus, sonnet, haiku
    timeout_seconds: int = 300


class ProvidersConfig(BaseModel):
    """Configuration for LLM providers."""
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    claude_cli: ClaudeCliConfig = Field(default_factory=ClaudeCliConfig)


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
    web: WebToolsConfig = Field(default_factory=WebToolsConfig)


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
            self.providers.openrouter.api_key or
            self.providers.anthropic.api_key or
            self.providers.openai.api_key or
            self.providers.gemini.api_key or
            self.providers.zhipu.api_key or
            self.providers.groq.api_key or
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
    
    def use_claude_cli(self) -> bool:
        """Check if Claude CLI provider should be used."""
        return self.providers.claude_cli.enabled
    
    def get_claude_cli_config(self) -> ClaudeCliConfig:
        """Get Claude CLI configuration."""
        return self.providers.claude_cli
    
    class Config:
        env_prefix = "NANOBOT_"
        env_nested_delimiter = "__"
