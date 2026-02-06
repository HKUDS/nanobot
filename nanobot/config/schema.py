"""Configuration schema using Pydantic."""

from pathlib import Path

from pydantic import BaseModel, Field, field_validator
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


class TTSConfig(BaseModel):
    """Text-to-speech configuration."""
    enabled: bool = False  # Enable TTS output
    provider: str = "openai"  # openai, elevenlabs
    voice: str = "alloy"  # openai: alloy, echo, fable, onyx, nova, shimmer
    api_key: str = ""  # Optional override for TTS provider
    model: str = "tts-1"  # TTS model: tts-1 (fast), tts-1-hd (high quality)
    max_text_length: int = 4000  # Maximum characters to synthesize
    timeout: float = 60.0  # HTTP request timeout in seconds

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate TTS provider is supported."""
        valid_providers = {"openai"}  # Only openai is currently implemented
        provider = v.lower()
        if provider not in valid_providers:
            raise ValueError(
                f"Invalid TTS provider: {v}. "
                f"Valid options: {', '.join(valid_providers)}"
            )
        return provider

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        """Validate TTS model is supported."""
        valid_models = {"tts-1", "tts-1-hd"}
        if v not in valid_models:
            raise ValueError(
                f"Invalid TTS model: {v}. Valid options: {', '.join(valid_models)}"
            )
        return v

    @field_validator("max_text_length")
    @classmethod
    def validate_max_text_length(cls, v: int) -> int:
        """Validate max_text_length is within reasonable bounds."""
        if v < 100:
            raise ValueError("max_text_length must be at least 100 characters")
        if v > 10000:
            raise ValueError("max_text_length cannot exceed 10000 characters")
        return v

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: float) -> float:
        """Validate timeout is within reasonable bounds."""
        if v < 5:
            raise ValueError("TTS timeout must be at least 5 seconds")
        if v > 300:
            raise ValueError("TTS timeout cannot exceed 300 seconds")
        return v


class MultimodalConfig(BaseModel):
    """Multi-modal capabilities configuration."""
    vision_enabled: bool = True  # Enable image/vision analysis
    max_image_size: int = 20 * 1024 * 1024  # 20MB default
    max_video_size: int = 100 * 1024 * 1024  # 100MB default
    max_video_frames: int = 5  # Max frames to extract from video
    video_processing_timeout: int = 30  # ffmpeg timeout in seconds
    tts: TTSConfig = Field(default_factory=TTSConfig)

    @field_validator("max_image_size")
    @classmethod
    def validate_max_image_size(cls, v: int) -> int:
        """Validate max_image_size is within reasonable bounds."""
        min_size = 1024 * 1024  # 1MB minimum
        max_size = 200 * 1024 * 1024  # 200MB maximum
        if v < min_size:
            raise ValueError(f"max_image_size must be at least {min_size} bytes")
        if v > max_size:
            raise ValueError(f"max_image_size cannot exceed {max_size} bytes")
        return v

    @field_validator("max_video_size")
    @classmethod
    def validate_max_video_size(cls, v: int) -> int:
        """Validate max_video_size is within reasonable bounds."""
        min_size = 1024 * 1024  # 1MB minimum
        max_size = 500 * 1024 * 1024  # 500MB maximum
        if v < min_size:
            raise ValueError(f"max_video_size must be at least {min_size} bytes")
        if v > max_size:
            raise ValueError(f"max_video_size cannot exceed {max_size} bytes")
        return v

    @field_validator("max_video_frames")
    @classmethod
    def validate_max_video_frames(cls, v: int) -> int:
        """Validate max_video_frames is within reasonable bounds."""
        if v < 1:
            raise ValueError("max_video_frames must be at least 1")
        if v > 20:
            raise ValueError("max_video_frames cannot exceed 20")
        return v

    @field_validator("video_processing_timeout")
    @classmethod
    def validate_video_processing_timeout(cls, v: int) -> int:
        """Validate video_processing_timeout is within reasonable bounds."""
        if v < 5:
            raise ValueError("video_processing_timeout must be at least 5 seconds")
        if v > 300:  # 5 minutes
            raise ValueError("video_processing_timeout cannot exceed 300 seconds")
        return v


class ToolsConfig(BaseModel):
    """Tools configuration."""
    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    multimodal: MultimodalConfig = Field(default_factory=MultimodalConfig)
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

    def _match_provider(self, model: str | None = None) -> ProviderConfig | None:
        """Match a provider based on model name."""
        model = (model or self.agents.defaults.model).lower()
        # Map of keywords to provider configs
        providers = {
            "openrouter": self.providers.openrouter,
            "deepseek": self.providers.deepseek,
            "anthropic": self.providers.anthropic,
            "claude": self.providers.anthropic,
            "openai": self.providers.openai,
            "gpt": self.providers.openai,
            "gemini": self.providers.gemini,
            "zhipu": self.providers.zhipu,
            "glm": self.providers.zhipu,
            "zai": self.providers.zhipu,
            "groq": self.providers.groq,
            "moonshot": self.providers.moonshot,
            "kimi": self.providers.moonshot,
            "vllm": self.providers.vllm,
        }
        for keyword, provider in providers.items():
            if keyword in model and provider.api_key:
                return provider
        return None

    def get_api_key(self, model: str | None = None) -> str | None:
        """Get API key for the given model (or default model). Falls back to first available key."""
        # Try matching by model name first
        matched = self._match_provider(model)
        if matched:
            return matched.api_key
        # Fallback: return first available key
        for provider in [
            self.providers.openrouter, self.providers.deepseek,
            self.providers.anthropic, self.providers.openai,
            self.providers.gemini, self.providers.zhipu,
            self.providers.moonshot, self.providers.vllm,
            self.providers.groq,
        ]:
            if provider.api_key:
                return provider.api_key
        return None

    def get_api_base(self, model: str | None = None) -> str | None:
        """Get API base URL based on model name."""
        model = (model or self.agents.defaults.model).lower()
        if "openrouter" in model:
            return self.providers.openrouter.api_base or "https://openrouter.ai/api/v1"
        if any(k in model for k in ("zhipu", "glm", "zai")):
            return self.providers.zhipu.api_base
        if "vllm" in model:
            return self.providers.vllm.api_base
        return None

    class Config:
        env_prefix = "NANOBOT_"
        env_nested_delimiter = "__"
