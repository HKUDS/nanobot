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

Client rules live in `scripts/check_client_import_boundaries.mjs`. Run `bun run check:imports` and `bun run test:imports` from `webui/` or `tui/`; each project's CI runs both commands with its own TypeScript dependency. The WebUI scan includes channel-owned frontend modules, and both scans include `packages/client-events/`.

| Client rule | Protected sources | Boundary |
| --- | --- | --- |
| `shared-client-contracts` | `packages/client-events/` | Local imports stay within the shared directory; React, Radix, Lucide, and OpenTUI dependencies are forbidden. |
| `tui-client` | `tui/src/client/` | No imports from TUI app, view, rendering, composer, or menu implementations, or those UI packages. |
| `webui-lib` | `webui/src/lib/` | No imports from WebUI components, hooks, or providers. |
| `channel-ui-contracts` | `channel-plugins/types.ts`, `channel-plugins/catalog.ts` | No imports from those WebUI implementation layers. React component types are part of the contribution interface. |
| `client-app-isolation` | WebUI, channel-owned UI, and TUI source modules | WebUI and channel UI do not import TUI implementations; TUI does not import WebUI or channel UI implementations. |

The client checker parses imports, type imports, re-exports, import-type expressions, literal dynamic imports, and literal `require` calls with the TypeScript AST. It normalizes relative paths and configured TypeScript path aliases, and expands literal Vite `import.meta.glob` patterns, including exclusions. Channel UI and locale registries may compose the channel-owned modules through those globs. Test files and test directories are excluded from production scans.

These rules protect direct imports by responsibility. `session/webui_turns.py` owns WebUI coordination, and `cli/gateway_runtime.py` assembles runtime and adapters. Computed import strings, plugin entry points, re-export origins, transitive dependencies, and module-attribute access are outside these source checks. They do not establish a complete module DAG. Execution, state ownership, and security behavior still require behavioral verification.

## Prefer duplication over premature abstraction

Channels and providers are allowed to repeat similar logic (send retries, media handling, message splitting). Do not introduce complex base classes or shared helpers just to eliminate duplication across channel files. Each channel file should remain self-contained and readable on its own. The same applies to provider implementations.

## Type dynamic boundaries at the edge

Wire payloads, persisted records, and third-party SDK objects are untrusted dynamic boundaries. Prefer a parser or small normalizer at the owning edge, and use `TypedDict` for stable dictionary shapes, so validation happens once and internal code receives a concrete type. Do not spread raw dynamic dictionaries or SDK objects through the core.

Stable first-party dependencies must be typed where they are stored or passed. Do not declare an internal service, context field, or callback result as `Any` and then recover its real type with consumer-side casts. Use the concrete type or a narrow `Protocol`; reserve `Any` for genuinely dynamic boundaries.

Every new cast must be supported by a boundary check or an invariant established by construction and control flow. Do not add redundant checks inside a validated path or use `cast` only to silence BasedPyright.

## Explicit over magical

Configuration belongs in `config/schema.py` Pydantic models. Provider auto-detection must remain traceable from the factory to the concrete provider class.
