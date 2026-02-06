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
    proxy: str | None = None  # HTTP/SOCKS5 proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"


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
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377  # GUILDS + GUILD_MESSAGES + DIRECT_MESSAGES + MESSAGE_CONTENT


class ChannelsConfig(BaseModel):
    """Configuration for chat channels."""
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)


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
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    custom: ProviderConfig = Field(default_factory=ProviderConfig)


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


class ToolsConfig(BaseModel):
    """Tools configuration."""
    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False  # If true, restrict all tool access to workspace directory


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
    
    def get_api_key(self, model_name: str | None = None) -> str | None:
        """Get API key based on model name prefix or priority order."""
        if model_name:
            if model_name.startswith("anthropic/"):
                return self.providers.anthropic.api_key or self.get_api_key()
            if model_name.startswith("openai/"):
                return self.providers.openai.api_key or self.get_api_key()
            if model_name.startswith("openrouter/"):
                return self.providers.openrouter.api_key or self.get_api_key()
            if model_name.startswith("deepseek/"):
                return self.providers.deepseek.api_key or self.providers.custom.api_key or self.get_api_key()
            if model_name.startswith("groq/"):
                return self.providers.groq.api_key or self.get_api_key()
            if model_name.startswith("gemini/"):
                return self.providers.gemini.api_key or self.get_api_key()
            if model_name.startswith("zai/") or model_name.startswith("zhipu/"):
                return self.providers.zhipu.api_key or self.get_api_key()
            if model_name.startswith("moonshot/") or model_name.startswith("kimi/"):
                return self.providers.moonshot.api_key or self.get_api_key()
            if model_name.startswith("vllm/") or model_name.startswith("hosted_vllm/"):
                return self.providers.vllm.api_key or self.get_api_key()
            if model_name.startswith("xai/"):
                # Explicit handling for xAI if used via custom or future provider
                return self.providers.custom.api_key
        
        # Priority fallback
        return (
            self.providers.openrouter.api_key or
            self.providers.deepseek.api_key or
            self.providers.anthropic.api_key or
            self.providers.openai.api_key or
            self.providers.gemini.api_key or
            self.providers.zhipu.api_key or
            self.providers.moonshot.api_key or
            self.providers.groq.api_key or
            self.providers.vllm.api_key or
            self.providers.custom.api_key or
            None
        )
    
    def get_api_base(self, model_name: str | None = None) -> str | None:
        """Get API base URL based on model name or explicit provider config."""
        if model_name:
            if model_name.startswith("openrouter/"):
                return self.providers.openrouter.api_base or "https://openrouter.ai/api/v1"
            if model_name.startswith("deepseek/"):
                return self.providers.deepseek.api_base
            if model_name.startswith("moonshot/"):
                return self.providers.moonshot.api_base or "https://api.moonshot.cn/v1"
            if model_name.startswith("vllm/") or model_name.startswith("hosted_vllm/"):
                return self.providers.vllm.api_base
            if model_name.startswith("zai/") or model_name.startswith("zhipu/"):
                return self.providers.zhipu.api_base
        
        # Explicit priority fallback
        if self.providers.openrouter.api_key:
            return self.providers.openrouter.api_base or "https://openrouter.ai/api/v1"
        return None
    
    class Config:
        env_prefix = "NANOBOT_"
        env_nested_delimiter = "__"
