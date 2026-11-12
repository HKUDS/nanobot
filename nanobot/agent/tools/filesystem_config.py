"""Filesystem configuration shared by the tools and root schema."""

from nanobot.config_base import Base


class FileToolsConfig(Base):
    """Filesystem tools configuration."""

    enable: bool = True
