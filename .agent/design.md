# Design Constraints

These rules govern architectural decisions. When adding a feature or fixing a bug, prefer paths that respect these boundaries.

## Core stays small; extend at the edges

New capabilities should be added via `channels/`, `tools/`, skills, or MCP servers. The files `agent/loop.py` and `agent/runner.py` form the critical core path; changes there should be minimal and justified. If a feature can live in a channel adapter, a tool, or an external MCP server, it should not be inlined into the agent loop.

Runtime state fan-out follows the same boundary. `AgentLoop` may publish generic runtime events from `nanobot.bus.runtime_events` for turn/run/model/goal state changes, but WebUI/WebSocket wire details such as `_turn_end`, `_goal_status`, title refreshes, and goal-state sync belong in `nanobot.session.webui_turns.WebuiTurnCoordinator` or the relevant channel adapter.

## Less structure, more intelligence

Prefer simple, readable code over new framework layers and indirection. Add structure only when it removes real complexity, protects an important boundary, or matches an established local pattern. The best fix is often a smaller prompt, a tighter tool contract, a channel-local change, or one focused regression test.

## Prefer duplication over premature abstraction

Channels and providers are allowed to repeat similar logic (send retries, media handling, message splitting). Do not introduce complex base classes or shared helpers just to eliminate duplication across channel files. Each channel file should remain self-contained and readable on its own. The same applies to provider implementations.

## Minimal change that solves the real problem

Fix bugs by changing only what is necessary. Do not bundle unrelated refactors or clean-ups into a feature or bugfix PR. If a refactor is genuinely required, it should be a separate, clearly scoped PR.

## Keep PRs reviewable

A bugfix should make the protected invariant clear, change the smallest surface that enforces it, and add only the closest regression test. If a diff starts changing ownership boundaries or mixing behavior changes with clean-up, split it before it becomes hard to review.

## Type dynamic boundaries at the edge

Wire payloads, persisted records, and third-party SDK objects are untrusted dynamic boundaries. Prefer a parser or small normalizer at the owning edge, and use `TypedDict` for stable dictionary shapes, so validation happens once and internal code receives a concrete type. Do not spread raw dynamic dictionaries or SDK objects through the core.

Stable first-party dependencies must be typed where they are stored or passed. Do not declare an internal service, context field, or callback result as `Any` and then recover its real type with consumer-side casts. Use the concrete type or a narrow `Protocol`; reserve `Any` for genuinely dynamic boundaries.

`typing.cast` performs no runtime validation. Every new cast must be supported by a runtime check on the same path or by an explicit invariant that is clear from construction and control flow (and documented locally when it is not obvious). If input can violate the claimed type, handle that invalid case before casting; never use `cast` only to silence BasedPyright.

## Explicit over magical

Configuration must be declared explicitly in `config/schema.py` Pydantic models. Error handling should raise clear exceptions rather than silently correcting bad input. Provider auto-detection exists, but every resolution path must be traceable from the factory to the concrete provider class.
