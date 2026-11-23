from nanobot.config_base import Base


class MyToolConfig(Base):
    """Self-inspection tool configuration."""
    enable: bool = True
    allow_set: bool = False
