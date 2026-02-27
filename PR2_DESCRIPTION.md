# PR2: FIT-Sec SecureToolRegistry — Audit correctness + emergency gating

## Suggested PR title

**SecureToolRegistry: enforce emergency gate + fix audit semantics**

## What this PR changes

This PR hardens the opt-in `SecureToolRegistry` middleware and the FIT-Sec runtime so that audit logs remain decision-accurate under failure modes.

### Behavioral fixes

- **Emergency gate is now enforced** in `SecureToolRegistry.execute()`:
  - When active, **all** `O1/O2` calls are blocked (only `O0` allowed), and the block is audited.
- **Emptiness Window blocks are logged as DENY**, not as an “ALLOW” decision that happens to be blocked later.
- **Audit `executed` flag is now truthful**:
  - If a tool executor raises, the entry records `executed=false` (previously some paths recorded `executed=true` despite failure).

### Audit/query correctness

- `AuditLogger.get_entries(limit=...)` now treats `limit=0` correctly and validates negative values (previously `limit=0` behaved like “no limit”).

### Test reliability

- Removed `time.sleep()` from the omega-2 approval expiry test; replaced with `monkeypatch` over `time.time()` for deterministic, non-flaky behavior.
- Adjusted one async test to avoid requiring `pytest-asyncio` (keeps test suite minimal in CI environments without async plugins).

## Why it matters

FIT-Sec is designed around **auditable governance**: if the audit trail can say “executed” when nothing actually executed, or records an “ALLOW” decision when an emergency/emptiness gate blocked the action, downstream analysis (and operator trust) breaks.

This PR ensures:

- **Gates are authoritative** (emergency/emptiness cannot be bypassed in the middleware path).
- **Audit logs reflect reality** (execution status and decision semantics match observed behavior).

## How to test locally

From repo root:

```bash
PYTHONPATH=. pytest -q
```

## Notes / scope

- This PR does **not** wire FIT-Sec into the default agent loop (still opt-in).
- Documentation is updated to avoid referencing non-existent classes and to reflect current integration status.

