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

## Explicit over magical

Configuration must be declared explicitly in `config/schema.py` Pydantic models. Error handling should raise clear exceptions rather than silently correcting bad input. Provider auto-detection exists, but every resolution path must be traceable from the factory to the concrete provider class.

## Configuration has an explicit owner

`FileConfigRepository` owns config-file reads, validation, revisions, and atomic writes. Process entry points may use the explicit functions in `config/loader.py`; components with an explicit config path should keep their own repository instance instead of importing a mutable global config object.

Persisted and runtime views are separate: `load_raw_config()` / `load_raw()` preserve `${VAR}` references for editing, while `load_effective_config()` / `load_effective()` return an isolated snapshot with references resolved. Read-modify-write flows must use `update()` / `update_config()` so a stale object cannot silently overwrite a newer change. Loading config is side-effect free; process-wide policies are applied explicitly during runtime startup.
