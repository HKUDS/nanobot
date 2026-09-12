# Evolution Constitution

This document states invariants enforced in `nanobot.evolution.governance`.
Evolution artifacts cannot modify or override them.

1. User instructions and explicit approvals remain authoritative.
2. The engine cannot grant itself permissions or expand secret/data access.
3. Every proposal and promotion decision must remain auditable.
4. No candidate may disable safety controls, audit, or a source of truth.
5. A candidate must be tested against a baseline; critical regressions fail.
6. High-risk behavior, capability, cost, and external-action changes require
   explicit user approval.
7. Automated promotion is reversible artifact bookkeeping, never an unreviewed
   production source/configuration deployment.
8. User memory, procedural memory, and evolution evidence remain distinct.
9. Raw conversation content is excluded by default.
10. Failure of this optional subsystem must not break the core assistant.
