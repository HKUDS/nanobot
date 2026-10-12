# Design Constraints

Consult this document when changing ownership boundaries, extension points, abstractions, or dynamic types. These constraints apply to implementation choices on those paths.

## Core stays small; extend at the edges

New capabilities should be added via `channels/`, `tools/`, skills, or MCP servers. The files `agent/loop.py` and `agent/runner.py` form the critical core path; changes there should be minimal and justified. If a feature can live in a channel adapter, a tool, or an external MCP server, it should not be inlined into the agent loop.

Runtime state fan-out follows the same boundary. `MessageBus.publish` awaits local subscribers for turn/run/model/goal state changes; `MessageBus.publish_event` queues routed channel delivery without waiting for network sends. Both carry `AgentEvent` values. Runner hooks publish typed output through the turn's scoped `EventSink`; direct-call callbacks are adapted at the execution boundary. WebUI/WebSocket wire details, title refreshes, and goal-state sync belong in `nanobot.session.webui_turns.WebuiTurnCoordinator` or the relevant channel adapter.

## Executable import boundaries

Run `python -m scripts.check_import_boundaries` from the repository root. The Python CI job runs this command on the coverage matrix entry. Rules live in `scripts/check_import_boundaries.py` and protect direct imports by module responsibility:

| Rule | Protected sources | Boundary |
| --- | --- | --- |
| `core-execution` | `agent/loop.py`, `agent/runner.py` | No imports from API, channel, CLI, gateway startup, or WebUI adapters. |
| `session-storage` | `session/manager.py`, `session/history.py`, `session/summary.py` | No imports from those adapters or `agent/` modules. |
| `security-primitives` | `security/` | No imports from those adapters, `agent/`, or `session/`. |
| `websocket-transport` | `channels/websocket/runtime.py` | Application command, mutation, and projection dependencies listed in the rule stay behind the owning coordinators. |
| `tool-config-base` | `agent/tools/` | Direct imports of `Base` use `nanobot.config_base`, not the aggregate `config.schema`. |

Static imports, including relative and function-local imports, are checked together with literal `import_module` calls and absolute `__import__` module arguments. Import aliases are recognized; relative `import_module` names require a literal package or `__package__`. Imports under `TYPE_CHECKING` are checked. The WebSocket transport may import `nanobot.bus.outbound_events.ProgressEvent` only under a recognized `TYPE_CHECKING` guard.

These rules do not assign whole directories to layers. `session/webui_turns.py` owns WebUI coordination, and `cli/gateway_runtime.py` assembles runtime and adapters. Computed import strings, plugin entry points, re-export origins, transitive dependencies, and module-attribute access are outside this source check. Execution, state ownership, and security behavior still require behavioral verification.

## Prefer duplication over premature abstraction

Channels and providers are allowed to repeat similar logic (send retries, media handling, message splitting). Do not introduce complex base classes or shared helpers just to eliminate duplication across channel files. Each channel file should remain self-contained and readable on its own. The same applies to provider implementations.

## Type dynamic boundaries at the edge

Wire payloads, persisted records, and third-party SDK objects are untrusted dynamic boundaries. Prefer a parser or small normalizer at the owning edge, and use `TypedDict` for stable dictionary shapes, so validation happens once and internal code receives a concrete type. Do not spread raw dynamic dictionaries or SDK objects through the core.

Stable first-party dependencies must be typed where they are stored or passed. Do not declare an internal service, context field, or callback result as `Any` and then recover its real type with consumer-side casts. Use the concrete type or a narrow `Protocol`; reserve `Any` for genuinely dynamic boundaries.

Every new cast must be supported by a boundary check or an invariant established by construction and control flow. Do not add redundant checks inside a validated path or use `cast` only to silence BasedPyright.

## Explicit over magical

Configuration belongs in `config/schema.py` Pydantic models. Provider auto-detection must remain traceable from the factory to the concrete provider class.
