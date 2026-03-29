# Add Timeout Protection and RAW Archive Fallback for Memory Consolidation

## Problem Statement

The current memory consolidation mechanism in `nanobot/agent/memory.py` has a **critical flaw** that can cause **complete session blocking**:

- When `MemoryStore.consolidate()` is triggered (typically after session grows large), it makes LLM API calls via `provider.chat_with_retry()`
- **There is no timeout protection** on these HTTP requests
- If the LLM provider is slow, overloaded, or unresponsive, the consolidation call hangs indefinitely
- This blocks the entire session, making the agent unresponsive to user messages
- In production environments with multiple nanobot instances, this can cause cascading failures

### Real-World Impact

In our deployment with 7 concurrent nanobot instances:
- Sessions would randomly "freeze" during long conversations
- Users would receive no response until manual restart
- Logs showed consolidation attempts hanging for 30+ minutes
- No error messages or fallback behavior - just silent failure

## Solution Overview

This PR implements a **two-layer defense mechanism**:

### Layer 1: HTTP Timeout Protection (Immediate)
- Wraps all LLM consolidation calls with `asyncio.wait_for(timeout=120.0)`
- On timeout: gracefully degrades to RAW archive (preserves data, doesn't block)
- Returns `True` to indicate "handled" (via RAW fallback), allowing session to continue

### Layer 2: Daily RAW Archive Reconciliation (Background)
- New `scripts/raw_compactor.py` for daily re-processing of RAW archives
- Runs as a background cron job (recommended: 2:00 AM daily)
- Attempts to consolidate RAW archives when system is idle
- Prevents HISTORY.md from accumulating too many RAW blocks

## Key Benefits

| Aspect | Before | After |
|--------|--------|-------|
| **Session Blocking** | Yes - indefinite hangs possible | No - 120s timeout with fallback |
| **Data Loss** | Risk of losing unconsolidated messages | RAW archive preserves all data |
| **User Experience** | Silent freezes | Graceful degradation |
| **Operational** | Manual restarts needed | Self-healing with cron job |
| **Multi-Instance** | Cascading failures possible | Isolated per-instance handling |

## Implementation Details

### Changes to `nanobot/agent/memory.py`

```python
# Before: No timeout - can hang indefinitely
response = await provider.chat_with_retry(...)

# After: 120s timeout with graceful fallback
response = await asyncio.wait_for(
    provider.chat_with_retry(...),
    timeout=120.0
)
```

Timeout handling:
```python
except asyncio.TimeoutError:
    logger.warning("Memory consolidation timeout (120s), forcing raw archive")
    self._raw_archive(messages)  # Preserve data without blocking
    self._consecutive_failures = 0
    return True  # Session continues normally
```

### New `scripts/raw_compactor.py`

A standalone utility for daily RAW archive maintenance:

```bash
# Basic usage
python scripts/raw_compactor.py --workspace ~/.nanobot/workspace

# For multiple instances (staggered to avoid resource contention)
0 2 * * * python raw_compactor.py --workspace ~/.nanobot/workspace
5 2 * * * python raw_compactor.py --workspace ~/.nanobot-agent1/workspace
10 2 * * * python raw_compactor.py --workspace ~/.nanobot-agent2/workspace
```

**Note**: The script now fully implements LLM consolidation by directly calling `MemoryStore.consolidate()` with the same logic as the nanobot runtime.

## Usage Instructions

### For Single Instance

No additional configuration needed. The timeout protection works automatically.

### For Multiple Instances

Each instance needs its own cron job configuration:

```bash
# Edit crontab
crontab -e

# Add entries for each instance (stagger by 5 minutes to avoid API rate limits)
0 2 * * * /usr/bin/python3 /path/to/nanobot/scripts/raw_compactor.py --workspace ~/.nanobot/workspace >> ~/.nanobot/workspace/logs/raw_compactor.log 2>&1
5 2 * * * /usr/bin/python3 /path/to/nanobot/scripts/raw_compactor.py --workspace ~/.nanobot-agent1/workspace >> ~/.nanobot-agent1/workspace/logs/raw_compactor.log 2>&1
```

### Log Monitoring

Check for timeout events:
```bash
grep "Memory consolidation timeout" ~/.nanobot/workspace/logs/*.log
```

Check RAW archive count:
```bash
grep -c "\[RAW\]" ~/.nanobot/workspace/memory/HISTORY.md
```

## Testing

### Manual Timeout Test

1. Temporarily set `timeout=1.0` in the code
2. Run a long conversation that triggers consolidation
3. Verify that:
   - Session doesn't block
   - RAW archive is created
   - User can continue chatting

### Cron Job Test

```bash
# Test the compactor script manually
python scripts/raw_compactor.py --workspace ~/.nanobot/workspace

# Verify it reports "No RAW blocks found" or processes existing blocks
```

## Backward Compatibility

- ✅ No breaking changes to existing APIs
- ✅ Default behavior improved (was broken due to blocking)
- ✅ RAW archives are forward-compatible with future consolidation improvements
- ✅ Existing HISTORY.md files are unaffected until new RAW blocks are added

## Future Work

1. **Configurable Timeout**: Make `120.0` seconds configurable via settings
2. **Metrics Export**: Add Prometheus metrics for consolidation success/failure rates
3. **Smart Scheduling**: Detect idle periods and consolidate proactively instead of waiting for session size threshold
4. **Batch Processing**: Optimize `raw_compactor.py` to process multiple small RAW blocks in a single LLM call

## Related Issues

- Prevents session blocking during memory consolidation
- Improves reliability in multi-instance deployments
- Addresses silent failures when LLM providers are slow

---

**Checklist:**
- [x] Code follows project style guidelines
- [x] Added/updated docstrings and comments
- [x] No breaking changes
- [x] Tested in multi-instance deployment
- [x] Documentation updated (this PR description)
