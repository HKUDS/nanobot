"""Web configuration shared by search/fetch tools and the root schema."""

from pydantic import Field

from nanobot.config_base import Base


class WebSearchConfig(Base):
    """Web search configuration."""
    provider: str = "duckduckgo"
    api_key: str = ""
    base_url: str = ""
    max_results: int = 5
    timeout: int = 30


class WebFetchConfig(Base):
    """Web fetch tool configuration."""
    use_jina_reader: bool = True


class WebToolsConfig(Base):
    """Web tools configuration."""
    enable: bool = True
    proxy: str | None = None
    user_agent: str | None = None
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    fetch: WebFetchConfig = Field(default_factory=WebFetchConfig)
