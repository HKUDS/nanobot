"""Agent fleet management (CLI-driven).

Per [[no-self-replicating-bots]], all infrastructure-mutating operations
live here as CLI commands invoked by a human, not as agent tools.

See vault/sketches/agent-fleet-cli.md for the design.
"""

from nanobot.fleet.registry import AgentRecord, Registry

__all__ = ["AgentRecord", "Registry"]
