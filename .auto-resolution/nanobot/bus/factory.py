"""Factory for creating the appropriate MessageBus backend from config."""

from __future__ import annotations

import logging
import os

from .queue import MessageBus

logger = logging.getLogger(__name__)


def create_bus(config: object | None = None) -> MessageBus:
    """Create a MessageBus instance based on the provided config or env vars.

    Priority
    --------
    1. ``config.bus.backend`` from the Pydantic Config object.
    2. ``NANOBOT_BUS_BACKEND`` environment variable.
    3. Default: in-process ``MessageBus`` (no network dependencies).

    Supported backends
    ------------------
    - ``local`` / ``in-process`` — in-process asyncio.Queue (no deps)
    - ``nats`` — NATS pub/sub (requires nats-py + NATS server)
    - ``redis`` — Redis Streams (requires redis-py + Redis server)
    - ``zmq`` — ZeroMQ PUB/SUB (requires pyzmq)

    Args:
        config: Pydantic ``Config`` object (from config.json), or None.

    Returns:
        A MessageBus instance for the resolved backend.
    """
    backend: str | None = None
    env_fallback_url: str = ""
    agent_id: str = ""

    # 1. Check config object
    if config is not None:
        bc = getattr(config, "bus", None)
        if bc is not None:
            backend = getattr(bc, "backend", None) or None
            agent_id = getattr(bc, "agent_id", "")
            env_fallback_url = getattr(bc, "url", "")

    # 2. Check environment variables (lower priority)
    if not backend:
        backend = os.environ.get("NANOBOT_BUS_BACKEND") or "local"

    if not agent_id:
        agent_id = os.environ.get("NANOBOT_AGENT_ID", "")

    # Normalise: Pydantic schema uses "local", internal uses "in-process"
    if backend == "local":
        backend = "in-process"

    if backend == "in-process":
        return MessageBus(agent_id=agent_id)

    if backend == "nats":
        from .nats import NATSMessageBus

        url = env_fallback_url
        subject_prefix = "nanobot.agent"

        if bc is not None:
            url = url or getattr(bc, "url", "nats://localhost:4222")
            subject_prefix = getattr(bc, "subject_prefix", "nanobot.agent")
        else:
            url = url or os.environ.get("NANOBOT_BUS_URL", "nats://localhost:4222")
            subject_prefix = os.environ.get(
                "NANOBOT_BUS_SUBJECT_PREFIX", "nanobot.agent"
            )

        cfg = _to_bus_config(
            backend="nats",
            agent_id=agent_id,
            url=url,
            subject_prefix=subject_prefix,
        )
        return NATSMessageBus(cfg)

    if backend == "redis":
        from .redis import RedisMessageBus

        if bc is not None:
            return RedisMessageBus(
                redis_url=(
                    getattr(bc, "url", None)
                    or os.environ.get("NANOBOT_BUS_URL", "redis://localhost:6379/0")
                ),
                agent_id=agent_id,
                channel_prefix=getattr(bc, "channel_prefix", "nanobot:agent"),
            )

        return RedisMessageBus(
            redis_url=os.environ.get(
                "NANOBOT_BUS_URL", "redis://localhost:6379/0"
            ),
            agent_id=agent_id,
            channel_prefix=os.environ.get(
                "NANOBOT_BUS_CHANNEL_PREFIX", "nanobot:agent"
            ),
        )

    if backend == "zmq":
        from .zmq import ZMQMessageBus

        url = env_fallback_url
        port = 5550
        peers: dict[str, str] = {}

        if bc is not None:
            url = url or getattr(bc, "url", "tcp://*:5550")
            port = getattr(bc, "port", 5550)
            peers = getattr(bc, "peers", {})
        else:
            url = url or os.environ.get("NANOBOT_BUS_URL", "tcp://*:5550")
            port = int(os.environ.get("NANOBOT_BUS_PORT", "5550"))

        cfg = _to_bus_config(
            backend="zmq",
            agent_id=agent_id,
            url=url,
            port=port,
            peers=peers,
        )
        return ZMQMessageBus(cfg)

    msg = f"Unknown bus backend: {backend!r}"
    raise ValueError(msg)


def _to_bus_config(**kwargs):
    """Build a lightweight config object with attribute-style access.

    Returns an object that works with getattr() — compatible with both
    the Pydantic BusConfig model and our internal dataclass-ish pattern.
    """
    return type("_BusConfig", (), kwargs)()