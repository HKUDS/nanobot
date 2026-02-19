"""Node types and configuration."""

from pydantic import BaseModel, Field


class NodeServerConfig(BaseModel):
    """Server configuration (runs on main instance)."""

    enabled: bool = False
    port: int = 18792
    token: str = ""


class NodeClientConfig(BaseModel):
    """Client configuration (runs on remote node)."""

    enabled: bool = False
    name: str = ""
    server_url: str = ""
    token: str = ""


class NodesConfig(BaseModel):
    """Nodes configuration."""

    server: NodeServerConfig = Field(default_factory=NodeServerConfig)
    client: NodeClientConfig = Field(default_factory=NodeClientConfig)