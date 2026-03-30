# ADR-001: Modular Monolith Strategy

## Status

Accepted

## Date

2026-03-11

## Context

Nanobot is a ~4,000-line single-process Python agent framework. As the codebase grows the
main risk is coupling — modules depending on each other's internals, making changes
expensive and error-prone.

Two common strategies exist for managing growth:

1. **Microservices** — split into separately deployed services with network boundaries.
2. **Modular monolith** — keep a single deployable unit but enforce explicit module
   boundaries, contracts, and import rules.

Nanobot's scale (single developer, single process, <10k lines) does not justify the
operational complexity of microservices (service discovery, distributed tracing, deployment
orchestration, network latency). The current package structure (`agent/`, `channels/`,
`providers/`, `config/`, `session/`, `bus/`) already maps to logical bounded contexts.

## Decision

We adopt a **modular monolith** architecture with the following rules:

1. **Keep the current package structure.** Do not rename top-level packages. Refactor
   within existing boundaries.

2. **Define explicit module boundaries.** Each top-level package documents what it owns,
   what public API it exposes, and what it must never import from. See
   `.claude/rules/architecture.md` for the module ownership map.

3. **Enforce import rules.** CI checks prevent cross-boundary violations (e.g.,
   `channels/` must never import from `agent/loop`, `tools/` must never import from
   `channels/`).

4. **Refactor by seams, not by folders.** Extract internal sub-services (e.g.,
   `ToolExecutor`, `MissionManager`) within `agent/` before considering package
   splits.

5. **No microservices or separate deployments** unless a specific scaling or isolation
   need is demonstrated and documented in a new ADR.

## Consequences

### Positive

- Single deployment unit — simple ops, fast startup, no network overhead.
- Existing code keeps working — no mass renames or import rewrites.
- Module boundaries enforced incrementally via CI, not a big-bang rewrite.
- Clear path to microservices later if needed (extract a package into its own service).

### Negative

- Requires discipline to maintain boundaries without compiler-level enforcement.
- Import rule checks add CI complexity.
- "Modular monolith" is less fashionable than microservices in some circles.

### Neutral

- ADRs become the mechanism for proposing boundary changes.
- Each major refactor should be a small, PR-sized change with tests.
