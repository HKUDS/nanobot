from pydantic import Field

from nanobot.config_base import Base


class WebSearchConfig(Base):
    """Web search configuration.

    For the ``mst`` provider, configure available engines via
    ``mst_engines`` (e.g. ``["ddg", "google", "brave"]``) or the
    ``MST_ENGINES`` environment variable (comma-separated). Override engine
    ranking weights via ``mst_weights`` or ``MST_WEIGHTS`` (JSON object).
    """
    provider: str = "duckduckgo"
    api_key: str = ""
    base_url: str = ""
    max_results: int = 5
    timeout: int = 30
    # mst-specific options (only used when provider == "mst")
    mst_engines: list[str] = Field(default_factory=list)
    mst_weights: dict[str, float] = Field(default_factory=dict)


class WebFetchConfig(Base):
    """Web fetch tool configuration."""
    use_jina_reader: bool = True


class WebToolsConfig(Base):
    """Web tools configuration."""
    enable: bool = True
    use_proxy: bool = False
    user_agent: str | None = None
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    fetch: WebFetchConfig = Field(default_factory=WebFetchConfig)
