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


class ChannelsConfig(BaseModel):
    """Configuration for chat channels."""
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
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
    model_config = {"extra": "allow"}

    # No hardcoded fields, everything is dynamic via extra fields
    # Users can add "openai": {...}, "deepseek": {...} etc.
    pass


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


class ToolsConfig(BaseModel):
    """Tools configuration."""
    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)


class MCPToolConfig(BaseModel):
    """MCP tool configuration."""
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    transport: str = "stdio"  # "stdio" or "http" or "sse"
    env: dict[str, str] = Field(default_factory=dict)


class Config(BaseSettings):
    """Root configuration for nanobot."""
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    mcp_tool: dict[str, MCPToolConfig] = Field(default_factory=dict)
    
    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()
    
    def get_provider_config(self, model: str | None = None) -> tuple[str, ProviderConfig | dict] | None:
        """Resolve the provider configuration for a given model."""
        target_model = model or self.agents.defaults.model
        
        # 1. Try to find provider by model prefix (e.g. "deepseek/..." -> providers.deepseek)
        if target_model and "/" in target_model:
            provider_name = target_model.split("/")[0]
            
            # Use getattr which handles both standard fields and allowed extra fields
            provider = getattr(self.providers, provider_name, None)
            # If not found via getattr, check pydantic extra fields explicitly
            if not provider and self.providers.__pydantic_extra__:
                provider = self.providers.__pydantic_extra__.get(provider_name)

            if provider and isinstance(provider, (ProviderConfig, dict)):
                return provider_name, provider

        # 2. Fallback: iterate over all configured providers and return the first valid one
        # This replaces the hardcoded priority list. We trust the order in config or just pick any.
        # Since we don't have hardcoded fields anymore, we rely on __pydantic_extra__
        if self.providers.__pydantic_extra__:
             # Prioritize common providers if they exist, to have some deterministic behavior
             # but dynamically based on what's present
             priority_hint = ["openrouter", "anthropic", "openai", "gemini", "zhipu", "groq", "vllm", "deepseek", "qwen", "mistral"]
             
             # First pass: check priority list
             for name in priority_hint:
                 if name in self.providers.__pydantic_extra__:
                     provider = self.providers.__pydantic_extra__[name]
                     api_key = self._extract_api_key(provider)
                     if api_key:
                         return name, provider
            
             # Second pass: check any other provider
             for name, provider in self.providers.__pydantic_extra__.items():
                 if name not in priority_hint:
                     api_key = self._extract_api_key(provider)
                     if api_key:
                         return name, provider
            
        return None

    def _extract_api_key(self, provider: ProviderConfig | dict) -> str | None:
        if isinstance(provider, ProviderConfig):
            return provider.api_key
        elif isinstance(provider, dict):
            return provider.get("api_key") or provider.get("apiKey")
        return None

    def get_api_key(self, model: str | None = None) -> str | None:
        """Get API key based on model prefix or priority order."""
        result = self.get_provider_config(model)
        if result:
            _, provider = result
            if isinstance(provider, ProviderConfig):
                return provider.api_key
            elif isinstance(provider, dict):
                return provider.get("api_key") or provider.get("apiKey")
        return None
    
    def get_api_base(self, model: str | None = None) -> str | None:
        """Get API base URL based on model prefix or priority order."""
        result = self.get_provider_config(model)
        if result:
            _, provider = result
            if isinstance(provider, ProviderConfig):
                return provider.api_base
            elif isinstance(provider, dict):
                return provider.get("api_base") or provider.get("apiBase")
        return None
    
    class Config:
        env_prefix = "NANOBOT_"
        env_nested_delimiter = "__"
