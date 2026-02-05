"""Configuration schema using Pydantic."""

from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class WhatsAppConfig(BaseModel):
    """WhatsApp channel configuration."""
    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    allow_from: list[str] = Field(default_factory=list)


class TelegramConfig(BaseModel):
    """Telegram channel configuration."""
    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    proxy: str | None = None


class FeishuConfig(BaseModel):
    """Feishu/Lark channel configuration."""
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    encrypt_key: str = ""
    verification_token: str = ""
    allow_from: list[str] = Field(default_factory=list)


class ChannelsConfig(BaseModel):
    """Configuration for chat channels."""
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)


class AgentDefaults(BaseModel):
    """Default agent configuration."""
    workspace: str = "~/.nanobot/workspace"
    model: str = "gpt-4o"
    max_tokens: int = 8192
    temperature: float = 0.7
    max_tool_iterations: int = 20


class AgentsConfig(BaseModel):
    """Agent configuration."""
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


# OpenAI-compatible provider configuration (covers 50+ providers)
class OpenAIConfig(BaseModel):
    """OpenAI-compatible provider configuration.

    Works with: OpenAI, DeepSeek, Groq, Together, Fireworks,
    SiliconFlow, local models (Ollama, vLLM), and 40+ others.
    """
    api_key: str = ""
    api_base: str | None = None


# Native SDK providers (non-OpenAI protocol)
class AnthropicConfig(BaseModel):
    """Anthropic Claude native SDK configuration.

    Only needed if using Claude-specific features (extended thinking, etc.)
    or when model name has "@anthropic/" prefix.
    """
    api_key: str = ""
    api_base: str | None = None


class GeminiConfig(BaseModel):
    """Google Gemini native SDK configuration.

    Only needed when model name has "@gemini/" prefix.
    """
    api_key: str = ""
    api_base: str | None = None  # Not supported by google-genai SDK


class GatewayConfig(BaseModel):
    """Gateway/server configuration."""
    host: str = "0.0.0.0"
    port: int = 18790


class WebSearchConfig(BaseModel):
    """Web search tool configuration."""
    api_key: str = ""
    max_results: int = 5


class WebToolsConfig(BaseModel):
    """Web tools configuration."""
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(BaseModel):
    """Shell exec tool configuration."""
    timeout: int = 60
    restrict_to_workspace: bool = False


class ToolsConfig(BaseModel):
    """Tools configuration."""
    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)


class Config(BaseSettings):
    """Root configuration for nanobot.

    Convention over configuration:
    - Default: OpenAI-compatible protocol (all providers use this)
    - Exception: "@anthropic/" prefix → AnthropicConfig
    - Exception: "@gemini/" prefix → GeminiConfig

    To switch providers: change api_key and api_base in openai config.
    """
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()

    def get_api_key(self) -> str | None:
        """Get API key from openai config."""
        return self.openai.api_key or None

    def get_api_base(self) -> str | None:
        """Get API base URL from openai config."""
        return self.openai.api_base or None

    class Config:
        env_prefix = "NANOBOT_"
        env_nested_delimiter = "__"
