# Startup Verification System

This system ensures the AGENTS.md startup sequence is followed correctly every session.

## Files

### `verify-startup.py`
**Purpose:** Checkpoint script that verifies all required startup steps were completed.

**Usage:**
```bash
python3 scripts/verify-startup.py
```

**Exit codes:**
- `0` - All steps verified successfully
- `1` - One or more required steps were skipped (fails loudly with red error messages)

**When to run:** After loading all core files, before greeting (Step 5 in AGENTS.md)

### `mark-startup-step.py`
**Purpose:** Mark individual startup steps as completed.

**Usage:**
```bash
python3 scripts/mark-startup-step.py <step>
```

**Valid steps:**
- `soul` - Marks SOUL.md as loaded
- `user` - Marks USER.md as loaded
- `memory` - Marks MEMORY.md as loaded
- `diary` - Marks diary context as loaded

**When to run:** Immediately after reading each core file (Step 4 in AGENTS.md)

### `.startup-state.json`
**Purpose:** Tracks which startup steps have been completed for the current session.

**Auto-created by:** `load-context.py --check-sessions`

**Structure:**
```json
{
  "timestamp": "2026-02-01T12:00:00.000000",
  "load_context_executed": true,
  "sessions_checked": true,
  "soul_loaded": true,
  "user_loaded": true,
  "memory_loaded": true,
  "diary_loaded": true
}
```

**Auto-updated by:**
- `load-context.py` (sets `load_context_executed`, `sessions_checked`, `diary_loaded`)
- `mark-startup-step.py` (sets individual file load flags)

## Integration with AGENTS.md

The startup sequence now includes verification checkpoints:

**Step 4:** After reading each core file:
```bash
# After reading SOUL.md
exec python3 scripts/mark-startup-step.py soul

# After reading USER.md
exec python3 scripts/mark-startup-step.py user

# After reading MEMORY.md
exec python3 scripts/mark-startup-step.py memory
```

**Step 5:** Before greeting:
```bash
exec python3 scripts/verify-startup.py
# If this fails (exit code 1), DO NOT GREET
# Go back and complete the missing steps
```

## Why This Matters

**Problem:** The startup sequence is critical for memory continuity, but it's easy to skip steps accidentally or take shortcuts when debugging/testing.

**Solution:** Automated verification that fails loudly if steps are skipped, making it impossible to proceed without following the correct sequence.

**Benefits:**
- Prevents incomplete startups
- Ensures SOUL/USER/MEMORY are always loaded in main sessions
- Validates diary context was loaded before greeting
- Makes debugging easier (clear error messages show what was skipped)
- Enforces discipline: no shortcuts, no partial loads

## Error Example

If you skip steps, you'll see:

```
🚨 STARTUP SEQUENCE VIOLATION 🚨
=====================================================
REQUIRED STARTUP STEPS WERE SKIPPED!

Missing steps:
  ❌ SOUL.md was loaded
  ❌ USER.md was loaded

You MUST complete ALL startup steps from AGENTS.md before greeting.
DO NOT SKIP STEPS. DO NOT TAKE SHORTCUTS.

Go back and run the complete startup sequence.
=====================================================
```

The script exits with code 1, which should prevent the greeting step from executing.
