"""Bus configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


BackendType = Literal["in-process", "redis", "zmq", "nats"]


@dataclass
class BusConfig:
    """Configuration for the message bus backend.

    Default backend is ``"nats"`` — a lightweight pub/sub server
    designed for microservice messaging.  Also supports ``"in-process"``
    (no network), ``"redis"``, and ``"zmq"``.
    """

    backend: BackendType = "nats"
    agent_id: str = ""

    # Common connection URL (used by nats, redis, zmq)
    url: str = "nats://localhost:4222"

    # NATS-specific
    subject_prefix: str = "nanobot.agent"

    # Redis-specific
    stream_prefix: str = "nanobot:bus"
    read_block_ms: int = 2000

    # ZMQ-specific
    port: int = 5550
    peers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> BusConfig:
        backend = data.get("backend", "in-process")
        kwargs: dict = {
            "backend": backend,
            "agent_id": data.get("agentId", data.get("agent_id", "")),
        }

        if backend == "redis":
            kwargs.update(
                url=data.get("url", "redis://localhost:6379/0"),
                stream_prefix=data.get(
                    "streamPrefix", data.get("stream_prefix", "nanobot:bus")
                ),
                read_block_ms=data.get(
                    "readBlockMs", data.get("read_block_ms", 2000)
                ),
            )
        elif backend == "zmq":
            kwargs.update(
                url=data.get("url", "tcp://*:5550"),
                port=data.get("port", 5550),
                peers=data.get("peers", {}),
            )
        elif backend == "nats":
            kwargs.update(
                url=data.get("url", "nats://localhost:4222"),
                subject_prefix=data.get(
                    "subjectPrefix", data.get("subject_prefix", "nanobot.agent")
                ),
            )
        else:  # in-process
            kwargs["url"] = ""

        return cls(**kwargs)