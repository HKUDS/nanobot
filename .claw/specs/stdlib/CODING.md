## Always-On Global Rule: Vertical Slices, Single Responsibility, and Contracts

You are an AI coding agent working across many repositories.
Default to an **architecture-first, contract-driven** approach that keeps codebases legible, toolable, and safe for both humans and other agents.

This rule applies **unless the repository explicitly documents a different standard**.

---

## 1. Core Architectural Principles (Non-Negotiable)

### 1.1 Vertical Slice Architecture (VSA)

- Organize code by **feature slices**, not by technical layers alone.
- A *slice* is a cohesive unit of behavior that can be reasoned about mostly in isolation.
- Prefer **slice-local cohesion**:
  - Domain rules, workflows, and adapters that exist primarily for a feature live inside that slice.
- Avoid global dumping grounds:
  - `utils`, `helpers`, `common`, or `misc` directories are allowed only when narrowly scoped and clearly named.

**Cross-slice boundaries must be explicit.**
- One slice must not reach into another slice’s internals.
- Cross-slice interaction must go through a **small, intentional interface** owned by the providing slice.

If the repo does not yet follow VSA:
- Do **not** attempt a large reorganization.
- Apply VSA incrementally: new work goes into slices; touched areas may be moved only when it reduces complexity.

---

### 1.2 One File = One Responsibility

Each file must have **one primary reason to change**.

Heuristics (guidance, not dogma):
- If a file grows large or mixes unrelated concerns, propose a split.
- If a module exposes multiple unrelated public entrypoints, separate them.
- Prefer many small files over a few large, ambiguous ones.

Avoid “kitchen sink” files:
- `utils.*`, `helpers.*`, `common.*` are discouraged unless the scope is extremely narrow and explicit.

---

### 1.3 Public Surface Discipline

Treat a symbol as **public** if any of the following are true:
- Imported or used by another slice
- Imported by shared/core code
- Invoked by an entrypoint (CLI, HTTP route, job/worker, UI boundary)
- Explicitly marked as public in documentation

Public changes require:
- explicit contract updates
- documentation updates when behavior or guarantees change

---

## 2. Repository Layout (General Guidance)

This rule is language-agnostic but assumes a **single source root** for application code.

Recommended conceptual structure:

```
<source-root>/
slices/ <slice-name>/
slice.<doc>          # Slice contract / overview (required)
api/                 # Entry points / boundaries (optional)
domain/              # Pure rules / types (optional)
service/             # Orchestration / workflows (optional)
data/                # Persistence / I/O adapters (optional)
tests/               # Slice-local tests (optional)
shared/                  # Truly cross-slice code (minimize)

```

Rules:
- Slices are feature-first, not layer-first.
- `shared/` should be small, stable, and boring.
- Tests may live alongside slices or in a separate top-level test directory, but ownership should be clear.

---

## 3. Documentation & Contract Rules

Your goal is to make the system understandable **without reading full implementations**.

### 3.1 Slice-Level Contract (Required)

Each slice must have a short **slice contract document** that answers:

- **Purpose** — why this slice exists
- **Responsibilities** — what it owns
- **Boundaries / Non-goals** — what it does not own
- **Public API** — intended integration points
- **Dependencies** — what it depends on and why
- **Verification** — how to test it

If the repo lacks a formal slice document, add these details to the closest existing slice/module documentation.

---

### 3.2 File-Level Contract (Required for non-trivial files)

Every non-trivial source file must include a **module/file contract** at the top of the file using the language’s standard documentation comment syntax.

The contract must cover:

- **Purpose** — one sentence
- **Responsibilities** — 2–5 bullets
- **Out of scope** — what this file intentionally does not do
- **Key collaborators** — other modules/slices it interacts with
- **Invariants** — assumptions that must remain true
- **Side effects** — DB / network / filesystem / logging (explicitly state “none” if none)
- **Notes for agents** — anything easy to break or important to preserve

Keep this structured, concise, and skimmable.

---

### 3.3 Function / Class-Level Contract (Required for public symbols)

Every public function, method, class, or exported symbol must have a **symbol contract** describing:

- **Purpose**
- **Inputs** (types, constraints, meaning)
- **Outputs** (return values, error modes)
- **Side effects** (explicitly “none” if none)
- **Failure behavior** (errors, exceptions, retries)
- **Guarantees / invariants** callers can rely on

Private/internal symbols should include at least:
- purpose
- assumptions
- side effects

---

## 4. Behavior While Making Changes

### 4.1 Plan before structural change
If a change affects:
- slice boundaries
- public APIs
- multiple files
- responsibilities of a module

Then:
- propose a brief plan first (files to touch, verification steps)
- do not implement until the plan is coherent

---

### 4.2 Keep diffs small and reviewable
- Avoid reformatting unrelated code.
- Prefer additive changes and explicit moves.
- When splitting files, keep behavior identical unless explicitly requested.

---

### 4.3 When uncertain
- If you cannot identify the correct slice, propose 1–2 options with tradeoffs.
- Choose the option that minimizes cross-slice coupling.
- If a request would violate these rules, propose a compliant alternative and document the tradeoff.

---

## 5. Enforcement Heuristics (Practical Defaults)

- New feature work should almost always live in a slice.
- Adding or modifying public behavior requires contract updates.
- Introducing side effects requires documenting them explicitly.
- If a file begins accumulating unrelated logic, stop and split.

---

## Appendix A: Python (Non-Binding Guidance)

If the repository is Python-based:
- Prefer a single source root (commonly `src/`).
- Prefer a single project configuration file as the source of truth.
- Module and symbol contracts should be placed in docstrings.
- Tests may live alongside slices or in a top-level test directory.

---

## Appendix B: TypeScript / JavaScript (Non-Binding Guidance)

If the repository is JS/TS-based:
- Prefer a single source root (commonly `src/`).
- Use JSDoc/TSDoc-style comments for file and symbol contracts.
- Public exports should have explicit documentation blocks.

---

## Final Reminder

These rules exist to:
- reduce cognitive load
- enable safe automation
- make repositories easier for both humans and agents to work in

When in doubt, favor **clarity, explicit boundaries, and small units of responsibility**.
