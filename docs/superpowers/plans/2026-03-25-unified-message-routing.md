# Unified Message Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the `process_direct` routing bypass by extracting a `MessageRouter` into `coordination/` and making routing a step inside `MessageProcessor._process_message()` — the single call site for all entry points.

**Architecture:** Extract coordination logic from `AgentLoop._classify_and_route()` into a new `MessageRouter` class in `coordination/router.py`. Inject it into `MessageProcessor` via the composition root. The processor calls `router.route()` as the first step of `_process_message()`, applies the role via `TurnRoleManager`, and resets in a `try/finally`. Both `AgentLoop.run()` and `process_direct()` become thin shells.

**Tech Stack:** Python 3.10+, dataclasses, pytest, pytest-asyncio, ruff, mypy

**Spec:** `docs/superpowers/specs/2026-03-25-unified-message-routing-design.md`

---

### Task 1: Add `forced_role` field to `InboundMessage`

**Files:**
- Modify: `nanobot/bus/events.py:10-22`
- Test: `tests/contract/test_routing_invariant.py` (new)

- [ ] **Step 1: Write test for the new field**

Create `tests/contract/test_routing_invariant.py`:

```python
"""Contract tests: routing applies uniformly across all entry points."""

from __future__ import annotations

from nanobot.bus.events import InboundMessage


def test_inbound_message_has_forced_role_field():
    """InboundMessage accepts forced_role with None default."""
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hello")
    assert msg.forced_role is None

    msg2 = InboundMessage(
        channel="cli", sender_id="user", chat_id="direct",
        content="hello", forced_role="code",
    )
    assert msg2.forced_role == "code"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:/Users/C95071414/Documents/nanobot-unified-routing
pytest tests/contract/test_routing_invariant.py::test_inbound_message_has_forced_role_field -v
```

Expected: FAIL — `InboundMessage.__init__() got an unexpected keyword argument 'forced_role'`

- [ ] **Step 3: Add the field to InboundMessage**

In `nanobot/bus/events.py`, add after `session_key_override` (line 21):

```python
    forced_role: str | None = None  # Set by process_direct(); skips classification
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/contract/test_routing_invariant.py::test_inbound_message_has_forced_role_field -v
```

Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 6: Commit**

```bash
git add nanobot/bus/events.py tests/contract/test_routing_invariant.py
git commit -m "feat: add forced_role field to InboundMessage for routing passthrough"
```

---

### Task 2: Create `MessageRouter` in `coordination/router.py`

**Files:**
- Create: `nanobot/coordination/router.py`
- Modify: `nanobot/coordination/__init__.py`
- Test: `tests/contract/test_routing_invariant.py` (append)

- [ ] **Step 1: Write tests for MessageRouter**

Append to `tests/contract/test_routing_invariant.py`:

```python
import pytest

from nanobot.config.schema import AgentRoleConfig
from nanobot.coordination.coordinator import ClassificationResult


@pytest.mark.asyncio
async def test_router_classifies_and_resolves_role():
    """MessageRouter.route() calls coordinator.classify and returns a RoutingDecision."""
    from nanobot.coordination.router import MessageRouter, RoutingDecision

    # Stub coordinator
    class StubCoordinator:
        classify_called = False

        async def classify(self, message):
            self.classify_called = True
            return ClassificationResult(
                role_name="pm", confidence=0.9,
                needs_orchestration=True, relevant_roles=["research", "writing"],
            )

        def route_direct(self, name):
            return AgentRoleConfig(name=name, description="test")

        class registry:
            @staticmethod
            def get_default():
                return AgentRoleConfig(name="general", description="fallback")

    class StubRoutingConfig:
        confidence_threshold = 0.6
        default_role = "general"

    class StubDispatcher:
        traces = []

        def record_route_trace(self, event, **kwargs):
            self.traces.append((event, kwargs))

    coord = StubCoordinator()
    dispatcher = StubDispatcher()
    router = MessageRouter(
        coordinator=coord,
        routing_config=StubRoutingConfig(),
        dispatcher=dispatcher,
    )

    decision = await router.route("multi-domain task", "web")
    assert isinstance(decision, RoutingDecision)
    assert decision.role.name == "pm"
    assert decision.classification.confidence == 0.9
    assert coord.classify_called


@pytest.mark.asyncio
async def test_router_forced_role_skips_classification():
    """When forced_role is provided, classification is skipped."""
    from nanobot.coordination.router import MessageRouter

    class StubCoordinator:
        classify_called = False

        async def classify(self, message):
            self.classify_called = True
            return ClassificationResult(role_name="general", confidence=1.0)

        def route_direct(self, name):
            return AgentRoleConfig(name=name, description="test")

        class registry:
            @staticmethod
            def get_default():
                return None

    class StubRoutingConfig:
        confidence_threshold = 0.6
        default_role = "general"

    class StubDispatcher:
        def record_route_trace(self, event, **kwargs):
            pass

    coord = StubCoordinator()
    router = MessageRouter(
        coordinator=coord,
        routing_config=StubRoutingConfig(),
        dispatcher=StubDispatcher(),
    )

    decision = await router.route("hello", "cli", forced_role="code")
    assert decision is not None
    assert decision.role.name == "code"
    assert not coord.classify_called  # classification was skipped


@pytest.mark.asyncio
async def test_router_unknown_forced_role_raises():
    """Unknown forced_role raises UnknownRoleError."""
    from nanobot.coordination.router import MessageRouter, UnknownRoleError

    class StubCoordinator:
        async def classify(self, message):
            return ClassificationResult(role_name="general", confidence=1.0)

        def route_direct(self, name):
            return None  # role not found

        class registry:
            @staticmethod
            def get_default():
                return None

    class StubRoutingConfig:
        confidence_threshold = 0.6
        default_role = "general"

    class StubDispatcher:
        def record_route_trace(self, event, **kwargs):
            pass

    router = MessageRouter(
        coordinator=StubCoordinator(),
        routing_config=StubRoutingConfig(),
        dispatcher=StubDispatcher(),
    )

    with pytest.raises(UnknownRoleError, match="nonexistent"):
        await router.route("hello", "cli", forced_role="nonexistent")


@pytest.mark.asyncio
async def test_router_system_channel_skips_routing():
    """System channel messages return None (no routing)."""
    from nanobot.coordination.router import MessageRouter

    class StubCoordinator:
        classify_called = False

        async def classify(self, message):
            self.classify_called = True
            return ClassificationResult(role_name="general", confidence=1.0)

        def route_direct(self, name):
            return AgentRoleConfig(name=name, description="test")

        class registry:
            @staticmethod
            def get_default():
                return None

    class StubRoutingConfig:
        confidence_threshold = 0.6
        default_role = "general"

    class StubDispatcher:
        def record_route_trace(self, event, **kwargs):
            pass

    coord = StubCoordinator()
    router = MessageRouter(
        coordinator=coord,
        routing_config=StubRoutingConfig(),
        dispatcher=StubDispatcher(),
    )

    decision = await router.route("hello", "system")
    assert decision is None
    assert not coord.classify_called


@pytest.mark.asyncio
async def test_router_low_confidence_uses_default_role():
    """When confidence is below threshold, default role is used."""
    from nanobot.coordination.router import MessageRouter

    class StubCoordinator:
        async def classify(self, message):
            return ClassificationResult(role_name="code", confidence=0.3)

        def route_direct(self, name):
            return AgentRoleConfig(name=name, description="test")

        class registry:
            @staticmethod
            def get_default():
                return AgentRoleConfig(name="general", description="fallback")

    class StubRoutingConfig:
        confidence_threshold = 0.6
        default_role = "general"

    class StubDispatcher:
        traces = []

        def record_route_trace(self, event, **kwargs):
            self.traces.append((event, kwargs))

    router = MessageRouter(
        coordinator=StubCoordinator(),
        routing_config=StubRoutingConfig(),
        dispatcher=StubDispatcher(),
    )

    decision = await router.route("hello", "web")
    assert decision is not None
    assert decision.role.name == "general"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/contract/test_routing_invariant.py -v -k "not inbound_message"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'nanobot.coordination.router'`

- [ ] **Step 3: Create `nanobot/coordination/router.py`**

```python
"""Message routing: classify → threshold → resolve role.

Extracted from ``AgentLoop._classify_and_route()`` so that routing is
coordination logic owned by ``coordination/``, not orchestration logic
scattered across entry points in ``agent/``.

See also ``nanobot.coordination.coordinator`` for the LLM classifier and
``nanobot.coordination.role_switching`` for per-turn role application.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.config.schema import AgentRoleConfig
from nanobot.coordination.coordinator import ClassificationResult

if TYPE_CHECKING:
    from nanobot.coordination.coordinator import Coordinator
    from nanobot.coordination.delegation import DelegationDispatcher


class UnknownRoleError(Exception):
    """Raised when a forced_role name does not match any registered role."""

    def __init__(self, role_name: str) -> None:
        self.role_name = role_name
        super().__init__(f"Unknown role: {role_name}")


@dataclass(slots=True)
class RoutingDecision:
    """Result of message routing — a data object, not a side effect."""

    role: AgentRoleConfig
    classification: ClassificationResult


class MessageRouter:
    """Classifies messages and resolves the target role.

    Pure coordination logic extracted from ``AgentLoop._classify_and_route()``.
    No state mutation — returns a ``RoutingDecision`` data object.
    """

    def __init__(
        self,
        *,
        coordinator: Any,  # Coordinator (runtime import avoided for boundary safety)
        routing_config: Any,  # RoutingConfig
        dispatcher: Any,  # DelegationDispatcher (for trace recording)
    ) -> None:
        self._coordinator = coordinator
        self._routing_config = routing_config
        self._dispatcher = dispatcher

    async def route(
        self,
        content: str,
        channel: str,
        *,
        forced_role: str | None = None,
    ) -> RoutingDecision | None:
        """Classify a message and resolve the target role.

        Returns ``None`` when the channel is ``"system"`` (system messages
        skip routing).

        Raises ``UnknownRoleError`` when *forced_role* is provided but not
        found in the registry — callers must surface this to the user.

        When *forced_role* is provided, classification is skipped and the
        named role is resolved directly.
        """
        if channel == "system":
            return None

        if forced_role:
            role = self._coordinator.route_direct(forced_role)
            if role is None:
                raise UnknownRoleError(forced_role)
            cls_result = ClassificationResult(
                role_name=forced_role,
                confidence=1.0,
                needs_orchestration=False,
                relevant_roles=[forced_role],
            )
            self._dispatcher.record_route_trace(
                "route_forced",
                role=role.name,
                confidence=1.0,
                message_excerpt=content,
            )
            return RoutingDecision(role=role, classification=cls_result)

        t0 = time.monotonic()
        cls_result = await self._coordinator.classify(content)
        role_name = cls_result.role_name
        confidence = cls_result.confidence
        latency_ms = (time.monotonic() - t0) * 1000

        threshold = self._routing_config.confidence_threshold
        if confidence < threshold:
            role_name = self._routing_config.default_role
            logger.info(
                "Low confidence ({:.2f} < {:.2f}), using default role '{}'",
                confidence,
                threshold,
                role_name,
            )

        role = (
            self._coordinator.route_direct(role_name)
            or self._coordinator.registry.get_default()
            or AgentRoleConfig(name=role_name, description="General assistant")
        )
        self._dispatcher.record_route_trace(
            "route",
            role=role.name,
            confidence=confidence,
            latency_ms=latency_ms,
            message_excerpt=content,
        )
        return RoutingDecision(role=role, classification=cls_result)


__all__ = ["MessageRouter", "RoutingDecision", "UnknownRoleError"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/contract/test_routing_invariant.py -v
```

Expected: all PASS

- [ ] **Step 5: Run lint and typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 6: Update `nanobot/coordination/__init__.py` exports**

The current `__init__.py` has no `__all__`. Add the new exports (total: 3, well within ≤12 limit):

```python
"""Multi-agent coordination: routing, delegation, and mission management."""

from __future__ import annotations

__all__ = ["MessageRouter", "RoutingDecision", "UnknownRoleError"]

from nanobot.coordination.router import MessageRouter, RoutingDecision, UnknownRoleError
```

- [ ] **Step 7: Commit**

```bash
git add nanobot/coordination/router.py nanobot/coordination/__init__.py tests/contract/test_routing_invariant.py
git commit -m "feat: extract MessageRouter into coordination/router.py"
```

---

### Task 3: Inject `MessageRouter` into `MessageProcessor` via composition root

**Files:**
- Modify: `nanobot/agent/message_processor.py:40-50` (constructor)
- Modify: `nanobot/agent/agent_factory.py:362-380,448-455` (construction + injection)

- [ ] **Step 1: Add `router` parameter to MessageProcessor constructor**

In `nanobot/agent/message_processor.py`, make these edits as a single coherent change:

First, add to the `TYPE_CHECKING` import block (around line 33-35):

```python
if TYPE_CHECKING:
    from nanobot.coordination.coordinator import ClassificationResult
    from nanobot.coordination.role_switching import TurnContext, TurnRoleManager
    from nanobot.coordination.router import MessageRouter
    from nanobot.providers.base import LLMProvider
```

(Note: `TurnContext` is added here too — it will be needed in Task 4.)

Then modify the `__init__` signature (line 40-49) to add the typed `router` parameter:

```python
    def __init__(
        self,
        *,
        services: _ProcessorServices,
        config: AgentConfig,
        workspace: Path,
        role_name: str,
        provider: LLMProvider,
        model: str,
        router: MessageRouter | None = None,
    ) -> None:
```

Add after `self._active_role_name` initialization (after line 80):

```python
        # Message router (injected by composition root when routing is enabled).
        self._router = router
```

- [ ] **Step 2: Construct MessageRouter in agent_factory.py and pass to processor**

In `nanobot/agent/agent_factory.py`, after the coordinator construction block (after line 381), add:

```python
    # 8.6 Construct MessageRouter (if routing is enabled)
    router = None
    if coordinator is not None:
        from nanobot.coordination.router import MessageRouter

        router = MessageRouter(
            coordinator=coordinator,
            routing_config=routing_config,
            dispatcher=dispatcher,
        )
```

Then modify the `MessageProcessor` construction (around line 448) to pass `router`:

```python
    processor = MessageProcessor(
        services=services,
        config=config,
        workspace=config.workspace_path,
        role_name=role_config.name if role_config else "",
        provider=provider,
        model=model,
        router=router,
    )
```

- [ ] **Step 3: Run lint and typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 4: Run existing tests to verify no regressions**

```bash
make test
```

Expected: all existing tests PASS (router is None for tests that don't configure routing)

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/message_processor.py nanobot/agent/agent_factory.py
git commit -m "feat: inject MessageRouter into MessageProcessor via composition root"
```

---

### Task 4: Move routing into `MessageProcessor._process_message()`

This is the core change. Routing becomes the first step in `_process_message()`.

**Files:**
- Modify: `nanobot/agent/message_processor.py:115-129` (process_direct), `131-140` (_process_message)

- [ ] **Step 1: Update `process_direct` to pass `forced_role` via InboundMessage**

In `nanobot/agent/message_processor.py`, modify `process_direct()` (lines 115-129):

```python
    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: ProgressCallback | None = None,
        forced_role: str | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        msg = InboundMessage(
            channel=channel, sender_id="user", chat_id=chat_id, content=content,
            forced_role=forced_role,
        )
        response = await self._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )
        return response.content if response else ""
```

- [ ] **Step 2: Add routing as first step in `_process_message()`**

In `nanobot/agent/message_processor.py`, add routing logic at the top of `_process_message()` (after line 138, before the existing `t0_request` line). The full method start becomes:

```python
    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        t0_request = time.monotonic()

        # --- ROUTE: classify and resolve role (single call site) ---
        turn_ctx: TurnContext | None = None
        if self._router:
            from nanobot.coordination.router import UnknownRoleError

            try:
                decision = await self._router.route(
                    msg.content, msg.channel, forced_role=msg.forced_role,
                )
            except UnknownRoleError as exc:
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id, content=str(exc),
                )
            if decision:
                self.classification_result = decision.classification
                assert self._role_manager is not None
                turn_ctx = self._role_manager.apply(decision.role)
                # Sync active settings after role switch
                self.set_active_settings(
                    model=self._role_manager._loop.model,
                    temperature=self._role_manager._loop.temperature,
                    max_iterations=self._role_manager._loop.max_iterations,
                    role_name=self._role_manager._loop.role_name,
                )
```

Add the import for `TurnContext` at the top of the file (inside `TYPE_CHECKING`):

```python
    from nanobot.coordination.role_switching import TurnContext, TurnRoleManager
```

(Update the existing `TurnRoleManager` import line to also import `TurnContext`.)

- [ ] **Step 3: Wrap existing processing in try/finally for role reset**

The existing body of `_process_message` (everything after the routing block, starting from the `effective_model` computation) must be wrapped in a `try/finally` to reset the role:

```python
        try:
            effective_model = self._active_model if self._active_model is not None else self.model
            # ... rest of existing _process_message body unchanged ...
        finally:
            if self._role_manager and turn_ctx is not None:
                self._role_manager.reset(turn_ctx)
```

- [ ] **Step 4: Run lint and typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 5: Run tests**

```bash
make test
```

Expected: existing tests PASS. The routing code path is only active when `self._router` is not None, which only happens when routing is enabled in config. Most tests don't configure routing, so they won't exercise this path yet.

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/message_processor.py
git commit -m "feat: move routing into MessageProcessor._process_message() as first step"
```

---

### Task 5: Simplify `AgentLoop` — remove routing from loop

**Files:**
- Modify: `nanobot/agent/loop.py:290-302,366-402,464-518`

- [ ] **Step 1: Remove routing and role management from `run()`**

In `nanobot/agent/loop.py`, in the `run()` method, delete ALL of these (the processor now owns the full lifecycle):

1. The `_classify_and_route` call (line ~294):
```python
                            turn_ctx = await self._classify_and_route(msg)
```

2. The `set_active_settings` call (lines ~297-302):
```python
                            self._processor.set_active_settings(
                                model=self.model,
                                temperature=self.temperature,
                                max_iterations=self.max_iterations,
                                role_name=self.role_name,
                            )
```

3. The `turn_ctx` variable declaration (line ~260):
```python
                    turn_ctx: TurnContext | None = None
```

4. **Both** `_role_manager.reset(turn_ctx)` calls — one in the normal path (line ~340) and one in the `except Exception` crash-barrier (line ~363). Both are safe to remove because `_process_message()` wraps the entire processing in its own `try/finally` with `_role_manager.reset()`, which fires even when exceptions propagate.

Verify with grep after editing:
```bash
grep -n "turn_ctx\|_classify_and_route\|set_active_settings\|_role_manager.reset" nanobot/agent/loop.py
```
Expected: no matches inside `run()` (matches in `process_direct` will be handled in Step 4).

- [ ] **Step 2: Delete `_classify_and_route()` method**

Delete the entire method at lines 366-402.

- [ ] **Step 3: Delete `_last_classification_result` field and its usages**

In `__init__` (around line 111), remove:
```python
        self._last_classification_result: ClassificationResult | None = None
```

In `process_direct()` (around line 477), remove:
```python
        self._last_classification_result = None
```

In the legacy shim `_run_agent_loop` (around line 187), remove:
```python
        self._processor.set_classification_result(self._last_classification_result)
```

**Verify the shim is safe to change:** The `_run_agent_loop` shim is only called by tests that also call `_process_message()` first (which sets `classification_result` via the router). Verify with:
```bash
grep -rn "_run_agent_loop" tests/ nanobot/ --include="*.py"
```
Confirm all callers either (a) go through the normal message path first, or (b) don't depend on `classification_result`.

Check for any other references to `_last_classification_result` and remove them:
```bash
grep -rn "_last_classification_result" nanobot/ --include="*.py"
```

- [ ] **Step 4: Simplify `process_direct()`**

Replace the current `process_direct()` body with a thin shell. Remove forced_role handling (lines ~482-489), the `set_active_settings` call (lines ~492-497), and `_role_manager.reset` (line ~518). The processor handles all of this internally now:

```python
    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: ProgressCallback | None = None,
        forced_role: str | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        assert self._role_manager is not None, "build_agent() must wire _role_manager"
        await self._connect_mcp()
        self._wire_coordinator()

        async with trace_request(
            name="request",
            input=content[:200],
            session_id=session_key,
            user_id="cli",
            tags=[channel],
            metadata={
                "channel": channel,
                "sender": "user",
                "session_key": session_key,
                "model": self.model,
                "role": self.role_name,
            },
        ):
            return await self._processor.process_direct(
                content, session_key, channel, chat_id, on_progress, forced_role
            )
```

- [ ] **Step 5: Run lint and typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 6: Run full test suite**

```bash
make test
```

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/loop.py
git commit -m "refactor: remove routing from AgentLoop — processor owns the full pipeline"
```

---

### Task 6: Update existing tests for the new architecture

**Files:**
- Modify: `tests/test_message_processor.py`
- Modify: `tests/test_agent_loop.py`
- Modify: `tests/test_process_direct_forced_role.py`

- [ ] **Step 1: Update message processor tests**

Any test that constructs `MessageProcessor` directly needs the new `router` parameter (default `None` is fine for existing tests). Check with:

```bash
grep -n "MessageProcessor(" tests/
```

Add `router=None` if the constructor call doesn't use keyword-only syntax that would pick up the default.

- [ ] **Step 2: Update forced_role tests**

`tests/test_process_direct_forced_role.py` tests the forced_role flow via `loop.process_direct()`. After the refactor, forced_role handling moved into the processor via the router. Update these tests to verify the new flow still works — the external behavior (error on unknown role, role applied on valid role) should be identical.

- [ ] **Step 3: Update agent loop tests**

Any test that mocks or patches `_classify_and_route` needs to be updated since the method is deleted. Replace with router-level mocking if needed.

- [ ] **Step 4: Run full test suite**

```bash
make check
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: update tests for unified routing architecture"
```

---

### Task 7: Add integration-level contract tests for routing invariant

The unit tests in Task 2 test the router in isolation. These integration tests verify that routing actually fires through both entry points end-to-end.

**Files:**
- Modify: `tests/contract/test_routing_invariant.py` (append)

- [ ] **Step 1: Add end-to-end routing tests**

Append to `tests/contract/test_routing_invariant.py`. These tests require a real `MessageProcessor` with a router wired in, not just stub objects:

```python
@pytest.mark.asyncio
async def test_process_direct_classifies_when_routing_enabled():
    """process_direct() must trigger coordinator classification."""
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.coordination.router import MessageRouter, RoutingDecision

    # Build a minimal processor with a mock router
    mock_router = MagicMock(spec=MessageRouter)
    mock_router.route = AsyncMock(return_value=None)  # No routing decision

    # Use the existing processor test fixture pattern from test_message_processor.py
    # to construct a processor with router=mock_router, then call process_direct().
    # Assert mock_router.route was called with the message content.
    # (Exact fixture setup depends on test helpers available — adapt to project patterns.)


@pytest.mark.asyncio
async def test_unknown_forced_role_returns_error():
    """process_direct(forced_role='bad') must return an error, not silently use defaults."""
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.coordination.router import MessageRouter, UnknownRoleError

    mock_router = MagicMock(spec=MessageRouter)
    mock_router.route = AsyncMock(side_effect=UnknownRoleError("bad"))

    # Construct processor with router=mock_router.
    # Call process_direct(forced_role="bad").
    # Assert the returned string contains "Unknown role: bad".
```

The exact processor construction will follow the patterns in `tests/test_message_processor.py`. The implementer should adapt these skeletons to match the project's test helper infrastructure.

- [ ] **Step 2: Run tests**

```bash
pytest tests/contract/test_routing_invariant.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_routing_invariant.py
git commit -m "test: add integration-level contract tests for routing invariant"
```

---

### Task 8: Add CLAUDE.md guardrail rule

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add "Message Processing — Single Pipeline" constraint**

In `CLAUDE.md`, under "Non-Negotiable Architectural Constraints", after the "No Architectural Debt by Design" section, add:

```markdown
### Message Processing — Single Pipeline

All message entry points (`run()`, `process_direct()`, future entry points) must
converge into `MessageProcessor._process_message()` before the first processing step.
Processing steps — routing, context building, orchestration, verification — must have
a single code path inside the processor. Entry points must not duplicate or skip
processing steps.

**Why this rule exists:** `process_direct()` was written as a "lightweight" path that
predated routing. When routing was added to the bus path, it was not added to
`process_direct()`, silently disabling routing for CLI, cron, and heartbeat callers.
The gap went undetected because each path was tested in isolation.

**Detection:** Contract tests in `tests/contract/test_routing_invariant.py` verify
that all entry points produce the same routing behavior. Run `make test` — these tests
are not optional.

**If you need a new entry point:** Route through `MessageProcessor._process_message()`.
Do not add processing logic to the loop or the new caller.
```

- [ ] **Step 2: Add prohibited pattern**

Under "Prohibited Patterns > Wiring violations", add:

```markdown
- Processing steps (routing, context building, orchestration) implemented at the
  entry-point level (`AgentLoop.run()`, `process_direct()`) rather than inside
  `MessageProcessor._process_message()`. Entry points must be thin shells that
  delegate to the processor.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Message Processing Single Pipeline constraint to CLAUDE.md"
```

---

### Task 9: Final validation and cleanup

**Files:**
- All modified files

- [ ] **Step 1: Run full CI pipeline**

```bash
make check
```

Expected: lint + typecheck + import-check + prompt-check + test all PASS

- [ ] **Step 2: Verify import boundaries**

```bash
make import-check
```

Expected: no violations. `agent/message_processor.py` imports from `coordination/router.py` (outer → inner, allowed). `coordination/router.py` imports from `coordination/coordinator.py` (same package).

- [ ] **Step 3: Verify file counts**

```bash
find nanobot/coordination -maxdepth 1 -name '*.py' ! -name '__init__.py' | wc -l
```

Expected: 10 (within ≤15 limit)

- [ ] **Step 4: Verify no stale references to deleted code**

```bash
grep -rn "_classify_and_route\|_last_classification_result" nanobot/ tests/ --include="*.py"
```

Expected: no matches (or only in docs/comments)

- [ ] **Step 5: Commit any final fixups**

```bash
git add -A
git commit -m "chore: final cleanup for unified message routing"
```
