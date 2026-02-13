"""Configuration schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ========== Channel configs ==========

class WhatsAppConfig(BaseModel):
    """WhatsApp channel configuration."""
    enabled: bool = False
    bridge_url: str = "ws://localhost:8080/ws"
    api_url: str = "http://localhost:8080"
    phone: str = ""
    auto_accept: bool = True


class TelegramConfig(BaseModel):
    """Telegram channel configuration."""
    enabled: bool = False
    bot_token: str = ""
    allowed_users: list[str] = Field(default_factory=list)
    proxy: str | None = None


class FeishuConfig(BaseModel):
    """Feishu (Lark) channel configuration."""
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    encrypt_key: str = ""
    allowed_users: list[str] = Field(default_factory=list)


class DingTalkConfig(BaseModel):
    """DingTalk channel configuration."""
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    allowed_users: list[str] = Field(default_factory=list)


class DiscordConfig(BaseModel):
    """Discord channel configuration."""
    enabled: bool = False
    bot_token: str = ""
    allowed_users: list[str] = Field(default_factory=list)
    group_policy: str = "off"  # off | all | mention


class EmailConfig(BaseModel):
    """Email channel configuration."""
    enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    email: str = ""
    password: str = ""
    check_interval: int = 60
    allowed_senders: list[str] = Field(default_factory=list)


class MochatConfig(BaseModel):
    """Mochat (web UI) configuration."""
    enabled: bool = False
    port: int = 8000


class SlackConfig(BaseModel):
    """Slack channel configuration."""
    enabled: bool = False
    bot_token: str = ""
    app_token: str = ""
    allowed_users: list[str] = Field(default_factory=list)


class QQConfig(BaseModel):
    """QQ channel configuration."""
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    allowed_users: list[str] = Field(default_factory=list)


class ChannelsConfig(BaseModel):
    """All channel configurations."""
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    dingtalk: DingTalkConfig = Field(default_factory=DingTalkConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    mochat: MochatConfig = Field(default_factory=MochatConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    qq: QQConfig = Field(default_factory=QQConfig)


# ========== Agent config ==========

class AgentDefaults(BaseModel):
    """Default agent settings."""
    workspace: str = "~/.nanobot/workspace"
    model: str = "openai/gpt-4.1-mini"
    max_tokens: int = 4096
    temperature: float = 0.7
    max_rounds: int = 20
    skills_dir: str = "~/.nanobot/skills"


class AgentsConfig(BaseModel):
    """Agents configuration."""
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


# ========== Provider config ==========

class ProviderConfig(BaseModel):
    """LLM provider configuration."""
    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None


class ProvidersConfig(BaseModel):
    """Configuration for LLM providers."""
    custom: ProviderConfig = Field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)


# ========== Gateway config ==========

class GatewayConfig(BaseModel):
    """Gateway configuration."""
    host: str = "0.0.0.0"
    port: int = 4000
    auth_token: str = ""


# ========== Tools config ==========

class WebToolsConfig(BaseModel):
    """Web tools configuration."""
    enabled: bool = True
    search_engine: str = "duckduckgo"
    api_key: str = ""


class ExecToolConfig(BaseModel):
    """Shell exec tool configuration."""
    timeout: int = 60
    command_wrapper: str = ""


class ToolsConfig(BaseModel):
    """Tools configuration."""
    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False


# ========== Cron config ==========

class CronConfig(BaseModel):
    """Cron configuration."""
    enabled: bool = True


# ========== Root config ==========

class Config(BaseModel):
    """Root nanobot configuration."""
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    cron: CronConfig = Field(default_factory=CronConfig)

    workspace_path: str = "~/.nanobot/workspace"

    class Config:
        env_prefix = "NANOBOT_"
        env_nested_delimiter = "__"

    def get_provider(self, name: str) -> ProviderConfig:
        """Get a provider config by name."""
        return getattr(self.providers, name, ProviderConfig())

    def get_api_key(self, provider_name: str) -> str:
        """Get API key for a provider."""
        prov = self.get_provider(provider_name)
        return prov.api_key
