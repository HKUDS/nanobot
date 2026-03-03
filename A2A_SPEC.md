# A2A Protocol Channel for Nanobot — Updated Spec (Using Official SDK)

## Overview

Implement an A2A (Agent-to-Agent) protocol channel for Nanobot using the official `a2a-sdk` library, enabling deployment as an HTTP/JSON-RPC endpoint with SSE streaming support.

## Background

- **A2A Protocol:** Open standard from Google/Linux Foundation for agent interoperability
- **Official SDK:** `a2a-sdk` (PyPI) — implements A2A v0.3.0 with JSON-RPC, HTTP, gRPC
- **Key concepts:** Tasks, Messages, Parts, contextId (session), Agent Cards
- **Transport:** JSON-RPC 2.0 over HTTP, with SSE streaming support

## Research Summary

See `~/openclaw/memory/2026-02-28-a2a-sdk-research.md` for full research.

**Decision:** Use official `a2a-sdk[http-server]` instead of building from scratch.

---

## Dependencies

Add to `pyproject.toml`:
```toml
"a2a-sdk[http-server,sqlite]>=0.3.0",
```

---

## Files to Create/Modify

### 1. `nanobot/channels/a2a.py` — A2A Channel Wrapper

Thin wrapper around `a2a-sdk` that bridges to Nanobot's message bus.

```python
# nanobot/channels/a2a.py

import asyncio
from typing import Any

from a2a.server import A2AServer
from a2a.types import AgentCard, Task, TaskStatus, Message, Part
from loguru import logger

from nanobot.channels.base import BaseChannel
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


class A2AChannel(BaseChannel):
    """
    A2A Protocol channel using the official a2a-sdk.
    
    Bridges A2A Tasks to Nanobot's message bus:
    - A2A contextId → Nanobot session_key
    - A2A Task → Single agent turn
    - A2A artifacts → OutboundMessage content
    """
    
    name = "a2a"
    
    def __init__(self, config: Any, bus: MessageBus, session_manager=None):
        super().__init__(config, bus)
        
        self._session_manager = session_manager
        self._pending_tasks: dict[str, asyncio.Future] = {}
        
        # Build agent card from config
        self._agent_card = AgentCard(
            name=getattr(config, 'agent_name', 'Nanobot'),
            url=getattr(config, 'agent_url', 'http://localhost:8000'),
            description=getattr(config, 'agent_description', 'Nanobot AI Agent'),
            version="1.0.0",
            capabilities={"streaming": True, "pushNotifications": False},
            skills=getattr(config, 'skills', []),
            defaultInputModes=["text/plain"],
            defaultOutputModes=["text/plain"],
            supportsAuthenticatedExtendedCard=False,
        )
        
        # Create A2A server
        self._server = A2AServer(self._agent_card)
        self._register_handlers()
    
    def _register_handlers(self):
        """Register A2A task handlers."""
        
        @self._server.handle_task
        async def handle_task(task: Task) -> Task:
            return await self._process_task(task)
    
    async def _process_task(self, task: Task) -> Task:
        """
        Process an A2A task by routing to Nanobot's agent loop.
        
        1. Extract message content from task
        2. Create InboundMessage and publish to bus
        3. Wait for agent response
        4. Update task with artifacts
        """
        context_id = task.contextId
        
        # Extract text from message parts
        content = self._extract_content(task.message)
        
        # Create future for response
        response_future = asyncio.Future()
        self._pending_tasks[task.id] = response_future
        
        # Publish to Nanobot bus
        inbound = InboundMessage(
            channel="a2a",
            sender_id=task.message.role if task.message else "a2a-client",
            chat_id=context_id,
            content=content,
            metadata={"task_id": task.id, "a2a_context_id": context_id},
            session_key_override=context_id,  # contextId = session_key
        )
        
        await self.bus.publish_inbound(inbound)
        logger.debug(f"A2A task {task.id} published to bus")
        
        # Update status to working
        task.status = TaskStatus.WORKING
        
        try:
            # Wait for response (with timeout)
            response_content = await asyncio.wait_for(
                response_future,
                timeout=300.0  # 5 minutes
            )
            
            # Update task with response
            task.artifacts = [
                Part(type="text", text=response_content)
            ]
            task.status = TaskStatus.COMPLETED
            logger.debug(f"A2A task {task.id} completed")
            
        except asyncio.TimeoutError:
            task.status = TaskStatus.FAILED
            task.error = "Task timed out"
            logger.warning(f"A2A task {task.id} timed out")
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"A2A task {task.id} failed: {e}")
            
        finally:
            self._pending_tasks.pop(task.id, None)
        
        return task
    
    def _extract_content(self, message: Message | None) -> str:
        """Extract text content from A2A Message."""
        if not message or not message.parts:
            return ""
        
        texts = []
        for part in message.parts:
            if part.type == "text" and part.text:
                texts.append(part.text)
            elif part.type == "data" and part.data:
                import json
                texts.append(json.dumps(part.data))
        
        return "\n".join(texts)
    
    async def start(self) -> None:
        """Start the A2A channel."""
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_responses())
        logger.info("A2A channel started")
    
    async def stop(self) -> None:
        """Stop the A2A channel."""
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
        logger.info("A2A channel stopped")
    
    async def send(self, msg: OutboundMessage) -> None:
        """
        Send response from agent back to A2A task.
        
        Called by _dispatch_responses when agent produces output.
        """
        task_id = msg.metadata.get("task_id") if msg.metadata else None
        
        if not task_id:
            # Try to find pending task for this context
            context_id = msg.chat_id
            for tid, future in self._pending_tasks.items():
                # Check if this future's task matches context
                # (simplified - in production, track context→task mapping)
                if not future.done():
                    task_id = tid
                    break
        
        if task_id and task_id in self._pending_tasks:
            future = self._pending_tasks[task_id]
            if not future.done():
                future.set_result(msg.content)
                logger.debug(f"A2A response delivered to task {task_id}")
    
    async def _dispatch_responses(self) -> None:
        """Background task: route outbound messages to A2A tasks."""
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0
                )
                if msg.channel == "a2a":
                    await self.send(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"A2A dispatch error: {e}")
    
    def get_asgi_app(self):
        """Get the ASGI application for HTTP deployment."""
        return self._server.app
    
    @property
    def agent_card(self) -> AgentCard:
        """Get the agent card."""
        return self._agent_card
```

### 2. `nanobot/config/schema.py` — Add A2AConfig

```python
@dataclass
class A2AChannelConfig(Base):
    """A2A channel configuration."""
    enabled: bool = False
    agent_name: str = "Nanobot"
    agent_url: str = "http://localhost:8000"
    agent_description: str = "Nanobot AI Agent"
    skills: list[str] = field(default_factory=list)
    allow_from: list[str] = field(default_factory=list)
```

Add to `ChannelsConfig`:
```python
@dataclass
class ChannelsConfig(Base):
    # ... existing channels ...
    a2a: A2AChannelConfig = field(default_factory=A2AChannelConfig)
```

### 3. `nanobot/channels/manager.py` — Register Channel

```python
# In _init_channels(), add:

# A2A channel (using official a2a-sdk)
if self.config.channels.a2a.enabled:
    try:
        from nanobot.channels.a2a import A2AChannel
        self.channels["a2a"] = A2AChannel(
            self.config.channels.a2a,
            self.bus,
            session_manager=self.session_manager,
        )
        logger.info("A2A channel enabled")
    except ImportError as e:
        logger.warning("A2A channel not available (install a2a-sdk): {}", e)
```

### 4. `examples/a2a_openfaas_handler.py` — OpenFaaS Deployment

```python
"""
OpenFaaS handler for Nanobot A2A channel.

Deploy as a function that exposes the A2A ASGI app.
"""

import asyncio
import os

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount

from nanobot.config.loader import load_config
from nanobot.bus.queue import MessageBus
from nanobot.channels.a2a import A2AChannel
from nanobot.agent.loop import AgentLoop
from nanobot.session.manager import SessionManager
from nanobot.providers.registry import ProviderRegistry

_state = None


async def get_state():
    """Lazy-initialize Nanobot components."""
    global _state
    if _state is None:
        config = load_config()
        bus = MessageBus()
        
        # Create session manager
        session_manager = SessionManager(config.workspace_path)
        
        # Create A2A channel
        a2a_channel = A2AChannel(
            config.channels.a2a,
            bus,
            session_manager=session_manager
        )
        await a2a_channel.start()
        
        # Create agent
        provider = ProviderRegistry.create_provider(config)
        agent = AgentLoop(
            provider=provider,
            bus=bus,
            workspace=config.workspace_path,
            session_manager=session_manager,
        )
        asyncio.create_task(agent.run())
        
        _state = {
            "channel": a2a_channel,
            "bus": bus,
            "agent": agent,
        }
    
    return _state


async def handle_a2a(request):
    """Handle A2A requests."""
    state = await get_state()
    channel = state["channel"]
    
    # Delegate to A2A server's ASGI app
    return await channel.get_asgi_app()(request.scope, request.receive, request.send)


async def health(request):
    """Health check endpoint."""
    return JSONResponse({"status": "healthy"})


# OpenFaaS expects a "handle" function
async def handle(scope, receive, send):
    """OpenFaaS ASGI entrypoint."""
    state = await get_state()
    channel = state["channel"]
    app = channel.get_asgi_app()
    await app(scope, receive, send)


# Alternative: Starlette app for direct deployment
app = Starlette(
    routes=[
        Route("/health", health),
        Mount("/", app=lambda scope: handle(scope, None, None)),
    ]
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
```

---

## API Endpoints

Once deployed, the A2A channel exposes:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/.well-known/agent-card.json` | GET | Agent Card (discovery) |
| `/` | POST | JSON-RPC 2.0 endpoint |
| `/message/send` | POST | Send message (async) |
| `/message/stream` | POST | Send message (SSE stream) |
| `/tasks/{id}` | GET | Get task status |
| `/tasks` | GET | List tasks |

---

## Configuration Example

```yaml
# nanobot.config.yaml
channels:
  a2a:
    enabled: true
    agent_name: "Nanobot Assistant"
    agent_url: "https://my-agent.example.com"
    agent_description: "AI assistant powered by Nanobot"
    skills:
      - "General conversation"
      - "Task management"
      - "Information lookup"
    allow_from:
      - "agent:*"  # Allow all agents
```

---

## Benefits of Using Official SDK

1. **Protocol Compliance** — Guaranteed A2A v0.3.0 compatibility
2. **Less Code** — ~200 lines vs ~600 lines custom implementation
3. **Maintenance** — SDK updates handle protocol changes
4. **Transport Options** — JSON-RPC, HTTP, gRPC all supported
5. **Tested** — Official SDK has comprehensive tests

---

## Test Files

### 5. `tests/test_a2a_channel.py` — Unit Tests

```python
"""Unit tests for A2AChannel."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nanobot.channels.a2a import A2AChannel
from nanobot.bus.events import InboundMessage, OutboundMessage


@pytest.fixture
def mock_bus():
    """Create a mock message bus."""
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    bus.consume_outbound = AsyncMock()
    return bus


@pytest.fixture
def mock_config():
    """Create a mock A2A config."""
    config = MagicMock()
    config.agent_name = "Test Agent"
    config.agent_url = "http://localhost:8000"
    config.agent_description = "Test description"
    config.skills = []
    return config


@pytest.fixture
def a2a_channel(mock_config, mock_bus):
    """Create an A2A channel instance."""
    return A2AChannel(mock_config, mock_bus)


class TestA2AChannel:
    """Tests for A2AChannel."""
    
    def test_channel_name(self, a2a_channel):
        """Test channel name is 'a2a'."""
        assert a2a_channel.name == "a2a"
    
    def test_agent_card_created(self, a2a_channel):
        """Test agent card is created from config."""
        card = a2a_channel.agent_card
        assert card.name == "Test Agent"
    
    @pytest.mark.asyncio
    async def test_extract_content_from_text(self, a2a_channel):
        """Test text extraction from message parts."""
        from a2a.types import Message, Part
        
        message = Message(parts=[Part(type="text", text="Hello")])
        content = a2a_channel._extract_content(message)
        assert content == "Hello"
    
    @pytest.mark.asyncio
    async def test_context_id_maps_to_session_key(self, a2a_channel, mock_bus):
        """Test that A2A contextId maps to Nanobot session_key."""
        # This would be tested via _process_task
        # Verify session_key_override is set correctly
        pass
    
    @pytest.mark.asyncio
    async def test_outbound_message_updates_task(self, a2a_channel):
        """Test outbound messages complete pending tasks."""
        # Set up a pending task with a future
        # Send outbound message
        # Verify future is resolved
        pass
```

### 6. `tests/integration/test_a2a_integration.py` — Integration Tests

```python
"""Integration tests for A2A channel with a2a-sdk."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, MagicMock

from nanobot.channels.a2a import A2AChannel
from nanobot.bus.queue import MessageBus


@pytest.fixture
async def a2a_server(mock_config):
    """Create a running A2A server for testing."""
    bus = MessageBus()
    channel = A2AChannel(mock_config, bus)
    await channel.start()
    
    from starlette.testclient import TestClient
    client = TestClient(channel.get_asgi_app())
    
    yield client, channel
    
    await channel.stop()


class TestA2AIntegration:
    """Integration tests for A2A protocol."""
    
    @pytest.mark.asyncio
    async def test_agent_card_endpoint(self, a2a_server):
        """Test /.well-known/agent-card.json returns valid card."""
        client, _ = a2a_server
        
        response = client.get("/.well-known/agent-card.json")
        assert response.status_code == 200
        
        card = response.json()
        assert "name" in card
        assert "capabilities" in card
    
    @pytest.mark.asyncio
    async def test_message_send_creates_task(self, a2a_server):
        """Test message/send creates a task and routes to bus."""
        client, channel = a2a_server
        
        response = client.post("/", json={
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "contextId": "test-ctx",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Hello"}]
                }
            },
            "id": 1
        })
        
        assert response.status_code == 200
        result = response.json()
        assert "result" in result
        assert result["result"]["status"] in ["pending", "working"]
    
    @pytest.mark.asyncio
    async def test_full_message_flow(self, a2a_server):
        """Test complete flow: send → bus → agent → response."""
        # This requires mocking the agent loop
        pass
```

## Manual Testing

```bash
# Run the A2A agent
cd ~/nanobot
python examples/a2a_openfaas_handler.py

# Check agent card
curl http://localhost:8000/.well-known/agent-card.json

# Send a message
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "params": {
      "contextId": "test-session",
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "Hello!"}]
      }
    },
    "id": 1
  }'

# Stream a message
curl -N http://localhost:8000/message/stream \
  -H "Content-Type: application/json" \
  -d '{
    "contextId": "test-session",
    "message": {
      "role": "user",
      "parts": [{"type": "text", "text": "Tell me a story"}]
    }
  }'
```

---

## References

- A2A Protocol: https://a2a-protocol.org/
- a2a-sdk PyPI: https://pypi.org/project/a2a-sdk/
- a2a-sdk GitHub: https://github.com/a2aproject/a2a-python
- A2A Samples: https://github.com/a2aproject/a2a-samples
