"""Agent hooks package"""

from .kosmos_hook import (
    KosmosAgentHook,
    KosmosSubagentHook,
    create_kosmos_hook,
    create_kosmos_subagent_hook,
)
from .nanocats_hook import (
    NanoCatsAgentHook,
    NanoCatsSubagentHook,
    create_nanocats_hook,
    create_subagent_hook,
)

__all__ = [
    "KosmosAgentHook",
    "KosmosSubagentHook",
    "create_kosmos_hook",
    "create_kosmos_subagent_hook",
    "NanoCatsAgentHook",
    "NanoCatsSubagentHook",
    "create_nanocats_hook",
    "create_subagent_hook",
]
