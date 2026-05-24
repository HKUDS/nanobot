"""Message bus module for decoupled channel-agent communication.

Backend selection
-----------------
| Backend    | Description                                   |
|------------|-----------------------------------------------|
| ``local``  | In-process ``asyncio.Queue`` (default)        |
| ``redis``  | Cross-instance via Redis Streams              |

Activate Redis by setting ``NANOBOT_BUS_BACKEND=redis`` (env var) or
adding a ``bus`` key to ``config.json`` (once ``BusConfig`` is wired into
the config schema).
"""

from nanobot.bus.config import BusConfig
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.factory import create_bus
from nanobot.bus.queue import MessageBus

__all__ = [
    "BusConfig",
    "InboundMessage",
    "MessageBus",
    "OutboundMessage",
    "create_bus",
]
