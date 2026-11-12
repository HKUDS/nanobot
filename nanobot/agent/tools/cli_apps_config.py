"""CLI Apps configuration shared by the tool and root schema."""

from pydantic import Field

from nanobot.config_base import Base


class CliAppsToolConfig(Base):
    """CLI Apps tool configuration."""

    enable: bool = True
    install_timeout: int = Field(default=300, ge=1, le=3600)
    run_timeout: int = Field(default=60, ge=1, le=600)
    catalog_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
