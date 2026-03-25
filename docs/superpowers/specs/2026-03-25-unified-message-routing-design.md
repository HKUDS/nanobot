# Unified Message Routing — Design Spec

**Date:** 2026-03-25
**Topic:** Eliminate the process_direct routing bypass by making routing a step in message processing, not a step in the loop's run method
**Status:** Draft
**Depends on:** `2026-03-24-role-switch-propagation-design.md` (per-turn parameter passing)

---

## Problem Statement

There are two entry points into the agent:

1. **Bus path** (`AgentLoop.run()`) — messages from channels arrive via the message bus.
   Classification and routing happen at `loop.py:294` via `_classify_and_route()`.

2. **Direct path** (`AgentLoop.process_direct()`) — CLI, cron, heartbeat, and tests call
   this method directly. Classification **never happens** unless `forced_role` is explicitly
   provided.

This means CLI users, cron jobs, and heartbeat tasks silently skip routing. When a user
types a multi-domain question via `nanobot agent -m`, the coordinator never classifies it,
the PM role is never selected, and delegation never triggers — even when `routing.enabled`
is `true` in config.

### Root cause

`_classify_and_route()` lives in `AgentLoop` (`loop.py:366-402`). It was added to the bus
path in `run()` but never integrated into `process_direct()`. The method mixes three
concerns:

1. **Coordination logic** — call `coordinator.classify()`, apply confidence threshold,
   resolve role. This belongs in `coordination/`.
2. **Orchestration wiring** — forward classification result to processor, record trace.
3. **State mutation** — `_role_manager.apply(role)` mutates loop-level fields.

Because this method is on the loop, it only runs when the loop is the caller. Adding it
to `process_direct` would create a second call site that must be kept in sync. Any future
third entry point would need the same manual wiring.

### Why this is structural

The problem is not "we forgot to add a line." The problem is that **routing is implemented
as a step in the loop's run method rather than as a step in message processing**. Any fix
that adds routing to `process_direct` without changing the architecture creates a
maintenance trap — the next entry point will have the same gap.

---

## Design: MessageRouter in coordination/ + single call site in MessageProcessor

### Principle

**Routing is a property of message processing, not of how the message arrived.** All entry
points converge into `MessageProcessor._process_message()` before the first processing
step. Routing happens once, inside the processor, at a single call site.

### Architecture

```
AgentLoop.run()          ──→ _process_message(msg) ──→ [route → build context → orchestrate]
AgentLoop.process_direct() ──→ _process_message(msg) ──→ [route → build context → orchestrate]
Future entry point         ──→ _process_message(msg) ──→ [route → build context → orchestrate]
```

---

## Section 1: Extract MessageRouter into coordination/

### New file: `nanobot/coordination/router.py`

A stateless coordination component that owns the classify → threshold → resolve pipeline.
No state mutation, no side effects beyond trace recording.

```python
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

    Pure coordination logic extracted from AgentLoop._classify_and_route().
    No state mutation — returns a RoutingDecision data object.
    """

    def __init__(
        self,
        *,
        coordinator: Coordinator,
        routing_config: RoutingConfig,
        dispatcher: DelegationDispatcher,
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

        Returns None when:
        - Channel is "system" (system messages skip routing)

        Raises UnknownRoleError when forced_role is provided but not found
        in the registry — callers must surface this to the user.

        When forced_role is provided, classification is skipped and the
        named role is resolved directly.
        """
        if channel == "system":
            return None

        if forced_role:
            role = self._coordinator.route_direct(forced_role)
            if role is None:
                raise UnknownRoleError(forced_role)
            # Build a synthetic classification result for forced roles
            cls_result = ClassificationResult(
                role_name=forced_role,
                confidence=1.0,
                needs_orchestration=False,
                relevant_roles=[forced_role],
            )
            self._dispatcher.record_route_trace(
                "route_forced", role=role.name, confidence=1.0,
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
                confidence, threshold, role_name,
            )

        role = (
            self._coordinator.route_direct(role_name)
            or self._coordinator.registry.get_default()
            or AgentRoleConfig(name=role_name, description="General assistant")
        )
        self._dispatcher.record_route_trace(
            "route", role=role.name, confidence=confidence,
            latency_ms=latency_ms, message_excerpt=content,
        )
        return RoutingDecision(role=role, classification=cls_result)
```

### Import direction

- `coordination/router.py` imports from `coordination/coordinator.py`,
  `coordination/delegation.py`, `config/schema.py` — all within `coordination/` or
  infrastructure. No boundary violations.

### Package placement

`coordination/` owns routing, delegation, missions. `MessageRouter` is routing logic.
Correct placement per CLAUDE.md.

### Placement gate check

Current `coordination/` top-level `.py` files (excluding `__init__.py`): 9
(`coordinator.py`, `delegation.py`, `delegation_advisor.py`, `delegation_contract.py`,
`mission.py`, `registry.py`, `role_switching.py`, `scratchpad.py`, `task_types.py`).
Adding `router.py` → 10. Within the ≤15 hard limit. No `__init__.py` export overflow
(current exports + 2 new = well under 12).

---

## Section 2: MessageProcessor calls the router

### Changes to `nanobot/agent/message_processor.py`

The processor receives `MessageRouter | None` via constructor injection (composition root).
No post-construction setter is needed — unlike `set_role_manager()` (which exists due to
a circular dependency between loop and manager), there is no circularity between the
processor and router. Direct constructor injection is preferred per the composition root
pattern.

```python
class MessageProcessor:
    def __init__(self, *, services, config, workspace, role_name, provider, model,
                 router: MessageRouter | None = None):
        # ... existing fields ...
        self._router = router
```

At the top of `_process_message()`, before session lookup:

```python
async def _process_message(self, msg, session_key=None, on_progress=None):
    t0_request = time.monotonic()

    # --- ROUTE: classify and resolve role (single call site) ---
    turn_ctx: TurnContext | None = None
    if self._router:
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

    try:
        # ... existing processing (session lookup, context build, orchestrate) ...
        ...
    finally:
        if self._role_manager:
            self._role_manager.reset(turn_ctx)
```

### Why `_process_message` and not `process_direct`

`process_direct()` on the processor is a thin wrapper that constructs an `InboundMessage`
and calls `_process_message()`. By putting routing in `_process_message`, both
`process_direct()` and `process()` (the bus path) get routing automatically. There is
no second call site.

### TurnContext lifecycle

The `apply/reset` pair now lives entirely within `_process_message`, in a
`try/finally` block. This is cleaner than the current split where `apply` happens in
`_classify_and_route` and `reset` happens later in `run()`.

---

## Section 3: Simplify AgentLoop entry points

### `AgentLoop.run()` — bus path

Remove `_classify_and_route()` call and **both `_role_manager.reset(turn_ctx)` calls**
(currently at `loop.py:332` and `loop.py:355`). The processor handles routing and reset
internally via try/finally. Remove the `turn_ctx` variable from `run()` entirely.

```python
async with trace_request(...):
    # _classify_and_route removed — processor routes internally
    # _role_manager.reset removed — processor handles apply/reset lifecycle
    if timeout:
        response = await asyncio.wait_for(
            self._process_message(msg), timeout=timeout,
        )
    else:
        response = await self._process_message(msg)
```

**Known limitation — trace span metadata:** The `trace_request` span opens with
`model=self.model` and `role=self.role_name` BEFORE `_process_message` runs routing.
After routing, these values change on the loop but the span metadata is stale. This is
a pre-existing issue (the current code has the same gap — `_classify_and_route` runs
inside the already-open span). Fixing this is out of scope; the span could be updated
after routing via `update_current_span()` in a follow-up.

### `AgentLoop.process_direct()` — direct path

Remove all `forced_role` handling from the loop. Instead, pass `forced_role` through
to the processor so the router can handle it:

```python
async def process_direct(self, content, session_key="cli:direct",
                         channel="cli", chat_id="direct",
                         on_progress=None, forced_role=None) -> str:
    assert self._role_manager is not None
    await self._connect_mcp()
    self._wire_coordinator()

    try:
        async with trace_request(...):
            return await self._processor.process_direct(
                content, session_key, channel, chat_id,
                on_progress, forced_role,
            )
    finally:
        pass  # reset handled inside processor._process_message
```

### Delete `AgentLoop._classify_and_route()`

This method is fully replaced by `MessageRouter.route()` called from within
`_process_message()`. Delete it from `loop.py`.

### Delete `AgentLoop._last_classification_result`

The processor owns `classification_result` directly. The loop no longer needs its
own copy. Any code that reads `loop._last_classification_result` should read from
the processor instead, or receive it as a return value.

---

## Section 4: Composition root wiring

### `nanobot/agent/agent_factory.py`

Construct `MessageRouter` in `build_agent()` when routing is enabled:

```python
# After constructing coordinator (existing code at ~line 358)
router: MessageRouter | None = None
if coordinator is not None:
    from nanobot.coordination.router import MessageRouter
    router = MessageRouter(
        coordinator=coordinator,
        routing_config=routing_config,
        dispatcher=dispatcher,
    )

# Pass router to processor at construction time (no post-construction setter)
processor = MessageProcessor(
    services=..., config=..., ...,
    router=router,
)
```

This follows the composition root pattern — `agent_factory.py` is the only place where
subsystems are constructed and wired.

---

## Section 5: Forced role propagation

Currently `forced_role` is a parameter on `process_direct()` that the loop handles.
After the refactor, it needs to reach the router inside `_process_message()`.

**Approach:** Add a typed `forced_role` field to `InboundMessage` (precedent:
`session_key_override` already exists on `InboundMessage` for similar pass-through use).
Do NOT use `metadata` piggybacking — metadata is freeform `dict[str, Any]` populated by
channels, and an undocumented `_forced_role` key would create a side channel where any
external bus message could silently force a role.

### Change to `nanobot/bus/events.py`

```python
@dataclass(slots=True)
class InboundMessage:
    channel: str
    sender_id: str
    chat_id: str
    content: str
    # ... existing fields ...
    forced_role: str | None = None  # Set by process_direct(); skip classification
```

### Change to `MessageProcessor.process_direct()`

```python
async def process_direct(self, content, session_key, channel, chat_id,
                         on_progress, forced_role):
    msg = InboundMessage(
        channel=channel, sender_id="user", chat_id=chat_id, content=content,
        forced_role=forced_role,
    )
    response = await self._process_message(msg, session_key=session_key,
                                           on_progress=on_progress)
    return response.content if response else ""
```

### In `_process_message()`

```python
if self._router:
    try:
        decision = await self._router.route(
            msg.content, msg.channel, forced_role=msg.forced_role,
        )
    except UnknownRoleError as exc:
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id,
            content=str(exc),
        )
    if decision:
        self.classification_result = decision.classification
        assert self._role_manager is not None
        turn_ctx = self._role_manager.apply(decision.role)
```

This preserves the current behavior where an unknown `forced_role` returns an error
message to the caller, rather than silently falling back to the default role.

---

## Section 6: Contract test — routing invariant

### New file: `tests/contract/test_routing_invariant.py`

This test encodes the invariant: **routing is a property of message processing, not of
how the message arrived.**

```python
@pytest.mark.parametrize("entry_point", ["bus", "process_direct"])
async def test_routing_applies_on_all_entry_points(entry_point, tmp_path):
    """Coordinator classification must run regardless of how the message enters."""
    provider = ScriptedProvider([
        LLMResponse(content="classified"),  # coordinator classify call
        LLMResponse(content="agent response"),  # actual agent response
    ])
    loop = build_test_agent(
        tmp_path, provider,
        routing_enabled=True,
        routing_roles=[AgentRoleConfig(name="pm", model="test-pm-model", ...)],
    )

    if entry_point == "bus":
        await bus.publish_inbound(InboundMessage(
            channel="web", sender_id="user", chat_id="test",
            content="multi-domain research task",
        ))
        # run one message through the loop
    else:
        await loop.process_direct("multi-domain research task")

    # Assert: coordinator was called (classification happened)
    assert provider.call_count >= 2  # classify + process

    # Assert: the role's model was used for the agent response
    agent_call = provider.call_log[-1]
    assert agent_call["model"] == "test-pm-model"
```

### Additional test cases

| Test | Entry point | Asserts |
|------|-------------|---------|
| `test_classification_runs_on_bus_path` | bus | `coordinator.classify` was called |
| `test_classification_runs_on_process_direct` | process_direct | `coordinator.classify` was called |
| `test_forced_role_skips_classification` | process_direct(forced_role="code") | classify NOT called, role applied |
| `test_no_router_skips_routing` | process_direct (routing disabled) | No error, uses defaults |
| `test_system_channel_skips_routing` | bus (channel="system") | classify NOT called |
| `test_role_reset_after_processing` | both | After first turn, send a second turn WITHOUT routing; assert provider receives the **default** model (not the role's model). Verifies reset actually restores state. |

---

## Section 7: CLAUDE.md guardrail rule

### Addition to "Non-Negotiable Architectural Constraints"

Add a new subsection after "Composition Root — Single Wiring Point":

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

### Addition to "Prohibited Patterns"

Under **Wiring violations**, add:

```markdown
- Processing steps (routing, context building, orchestration) implemented at the
  entry-point level (`AgentLoop.run()`, `process_direct()`) rather than inside
  `MessageProcessor._process_message()`. Entry points must be thin shells that
  delegate to the processor.
```

---

## Section 8: Files changed

| File | Change |
|------|--------|
| `nanobot/coordination/router.py` | **New**: `MessageRouter`, `RoutingDecision`, `UnknownRoleError` |
| `nanobot/coordination/__init__.py` | Add `MessageRouter`, `RoutingDecision`, `UnknownRoleError` to exports |
| `nanobot/bus/events.py` | Add `forced_role: str \| None = None` field to `InboundMessage` |
| `nanobot/agent/message_processor.py` | Add `router` constructor param, move routing into `_process_message()`, catch `UnknownRoleError`, `apply/reset` lifecycle in try/finally |
| `nanobot/agent/loop.py` | Delete `_classify_and_route()`, delete `_last_classification_result`, remove both `_role_manager.reset()` calls from `run()`, simplify `run()` and `process_direct()` to thin shells |
| `nanobot/agent/agent_factory.py` | Construct `MessageRouter` when routing enabled, pass to processor constructor |
| `CLAUDE.md` | Add "Message Processing — Single Pipeline" constraint and prohibited pattern |
| `tests/contract/test_routing_invariant.py` | **New**: contract tests for routing invariant |
| `tests/test_message_processor.py` | Update for router constructor injection |
| `tests/test_agent_loop.py` | Update for simplified loop (no more `_classify_and_route`, no `reset` calls) |

---

## Section 9: What this does NOT change

- **`TurnRoleManager`** — continues to mutate loop-level fields via `_LoopLike`. The
  role-switch propagation spec (`2026-03-24`) handles making those values reach components.
  This spec only changes WHERE `apply/reset` are called (processor instead of loop).

- **`Coordinator`** — no change. `MessageRouter` wraps it; the coordinator's classify/route
  interface is unchanged.

- **`DelegationDispatcher`** — no change. It receives `record_route_trace` calls from
  `MessageRouter` instead of from `_classify_and_route`, same interface.

- **Bus/channel infrastructure** — no change. Messages still flow through the bus to
  `AgentLoop.run()`. The only difference is that `run()` no longer calls
  `_classify_and_route` before processing.

---

## Interaction with role-switch propagation spec

The `2026-03-24-role-switch-propagation-design.md` spec adds `set_active_settings()` to
the processor, called from `AgentLoop` after role switching. After this spec:

- `set_active_settings()` would be called from **inside `_process_message()`** after
  `_role_manager.apply()`, not from the loop. The call site moves but the mechanism
  is the same.

- The propagation spec's "Call site 1" (bus path in `run()`) and "Call site 2"
  (`process_direct()`) collapse into a single call site inside `_process_message()`.

**Implementation order and migration:**

- **If role-switch propagation lands first:** It adds `set_active_settings()` calls at
  two sites in `loop.py` (Call site 1 in `run()`, Call site 2 in `process_direct()`).
  When this spec lands afterward, the implementer must **remove both `set_active_settings()`
  calls from `loop.py`** and add a single call inside `_process_message()` immediately
  after `_role_manager.apply(decision.role)`:
  ```python
  turn_ctx = self._role_manager.apply(decision.role)
  self.set_active_settings(
      model=self._role_manager._loop.model,
      temperature=self._role_manager._loop.temperature,
      max_iterations=self._role_manager._loop.max_iterations,
      role_name=self._role_manager._loop.role_name,
  )
  ```

- **If this spec lands first:** The propagation spec adds `set_active_settings()` inside
  `_process_message()` directly (single call site, no migration needed).

---

## Out of scope

- Replacing `TurnRoleManager`'s mutation-based approach with per-turn data passing.
  The propagation spec addresses this concern. This spec only moves the call site.

- Making `MessageProcessor` satisfy `_LoopLike`. The processor is not the loop; the
  role manager correctly targets the loop's fields.

- Adding routing to `run_tool_loop` (used by delegation/missions). Delegated agents
  have their own role resolved by the delegation dispatcher. They don't need coordinator
  classification.
