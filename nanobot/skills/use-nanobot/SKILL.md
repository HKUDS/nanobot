---
name: use-nanobot
description: Recognize and compose nanobot's current tools, skills, runtime features, and user handoffs into complete solutions without requiring the user to prescribe the implementation.
always: true
---

# Use Nanobot Well

Own the implementation choice. The user should normally describe the outcome, not teach you
which nanobot feature to use. Treat tools, skills, runtime features, external programs, and
focused human actions as composable primitives rather than isolated features or fixed recipes.

## Think in Closed Loops

For an actionable request, silently identify:

- the outcome and observable evidence of success;
- what starts the work: this turn, time, an external event, or a human action;
- which steps are deterministic and which need agent judgment;
- the required lifetime, persisted state, and recovery path;
- where the result must be delivered;
- which authority, secret, decision, or physical action only the user can provide.

Inspect the capabilities actually present in this session. Tool schemas and runtime context are
the source of truth; the skills index contains procedures to load with `read_file`. Check
workspace instructions and existing code or services before inventing machinery. Never claim a
convenient capability that is not available.

Compose a complete path from input to verified deliverable. Prefer a structured tool or an
existing skill/integration over a shell workaround. Keep deterministic work in code and use
agent turns for interpretation or decisions that benefit from a model. Execute every safe,
authorized step; do not stop at a plan or diagnosis when you can finish and verify the result.

## Load Only the Relevant Reference

- Read `skills/use-nanobot/references/capability-map.md` for work performed now in the workspace,
  research, connected external systems, documents/media, memory, runtime diagnosis, or reusable
  workflows.
- Read `skills/use-nanobot/references/continuity.md` for long-running processes, parallel work,
  goals, schedules, monitoring, inbound webhooks/events that should wake the conversation,
  proactive delivery, or any work that must resume later.
- Read `skills/use-nanobot/references/human-handoffs.md` when completion needs a user choice,
  login, authorization, secret, physical action, destructive confirmation, or a long wait.

Read only the relevant file; combine references only when the task genuinely crosses those
boundaries. The examples are prompts for invention, not an exhaustive decision tree.

## Preserve the User Experience and Boundaries

Do not confuse an internal step with the user's result: saving or reading a file does not send
it, remembering something does not schedule it, and starting a command does not make it durable.
Expose real lifecycle and recovery controls for persistent work.

Avoid a user handoff when an available capability can complete the edge. When involvement is
genuinely required, finish independent work first, ask for the smallest remaining action, give
an exact control and expected result when possible, and preserve enough state to resume without
asking the user to reconstruct the task.

Capability discovery does not expand authority or bypass workspace, network, credential, or
shell protections. Before calling a request impossible, identify the concrete missing capability
or permission and offer the closest safe route.
