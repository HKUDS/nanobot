# FIT-Sec Integration for nanoBot

This fork integrates the **FIT Framework** security layer into nanoBot, providing policy-controlled tool execution with the Omega taxonomy.

## Overview

FIT-Sec adds three core safety primitives to nanoBot:

1. **Omega Taxonomy** - Classifies tools by blast radius (O0/O1/O2)
2. **Monitorability Gate** - Ensures estimator quality before high-risk actions
3. **Emptiness Window** - Safety mode that preserves cognition but removes commit power

## Quick Start

### Using SecureAgentLoop (Recommended)

Replace `AgentLoop` with `SecureAgentLoop` to enable FIT-Sec:

```python
from nanobot.agent.secure_loop import SecureAgentLoop

# Create secure agent loop
agent = SecureAgentLoop(
    bus=message_bus,
    provider=llm_provider,
    workspace=Path("./workspace"),
    strict_mode=True,  # Deny unknown tools
)

# Grant temporary approval for shell commands (O2)
agent.grant_tool_approval("exec", duration_seconds=300)

# Process messages with security checks
response = await agent.process_direct("List files in current directory")
```

### Using SecureToolRegistry Directly

```python
from nanobot.agent.tools.secure_registry import SecureToolRegistry
from nanobot.fitsec import OmegaLevel

registry = SecureToolRegistry(
    workspace=Path("./workspace"),
    strict_mode=True,
)

# Register custom tool with explicit Omega level
registry.register(my_tool, omega_level=OmegaLevel.OMEGA_1)

# Execute with policy checks
try:
    result = await registry.execute("my_tool", {"arg": "value"})
except PolicyDeniedError:
    print("Action blocked by policy")
```

## Omega Classifications

| Level | Risk | Default Policy | Example Tools |
|-------|------|----------------|---------------|
| **O0** | Safe | ALLOW | read_file, list_dir, web_search, message |
| **O1** | Medium | ALLOW (audited) | write_file, edit_file |
| **O2** | High | DENY | exec, spawn, cron |

### Customizing Omega Mappings

```python
from nanobot.fitsec import OmegaLevel

custom_mappings = {
    "my_safe_tool": OmegaLevel.OMEGA_0,
    "my_risky_tool": OmegaLevel.OMEGA_2,
}

registry = SecureToolRegistry(omega_mappings=custom_mappings)
```

## Safety Controls

### Granting O2 Approval

O2 tools require explicit, time-bounded approval:

```python
# Grant 5-minute approval
agent.grant_tool_approval("exec", duration_seconds=300)

# Revoke approval
agent.revoke_tool_approval("exec")
```

### Emptiness Window (Safety Mode)

Enter safety mode when uncertain or debugging:

```python
# Enter Emptiness - blocks O1/O2 tools
agent.enter_safety_mode("Investigating anomaly")

# O0 tools still work
result = await registry.execute("read_file", {"path": "log.txt"})

# O1/O2 tools are blocked
# raises EmptinessActiveError

# Exit safety mode
agent.exit_safety_mode()
```

### Emergency Stop

Immediately block all non-O0 operations:

```python
agent.emergency_stop("Critical error detected")
```

## Audit Trail

All tool executions are logged:

```python
# Get audit summary
summary = agent.get_audit_summary()
print(f"Total: {summary['total']}")
print(f"Allowed: {summary['allowed']}")
print(f"Denied: {summary['denied']}")
print(f"By Omega: {summary['by_omega_level']}")
```

Audit logs are written to `{workspace}/.nanobot/audit.jsonl` in append-only JSONL format.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    SecureAgentLoop                       │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────┐    │
│  │              SecureToolRegistry                  │    │
│  │  ┌─────────────┐    ┌─────────────────────────┐ │    │
│  │  │ ToolRegistry│ -> │    FitSecRuntime        │ │    │
│  │  │  (nanoBot)  │    │  ┌─────────────────┐    │ │    │
│  │  └─────────────┘    │  │ PolicyEngine    │    │ │    │
│  │                     │  │ MonitorGate     │    │ │    │
│  │                     │  │ EmptinessWindow │    │ │    │
│  │                     │  │ AuditLogger     │    │ │    │
│  │                     │  └─────────────────┘    │ │    │
│  │                     └─────────────────────────┘ │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## Running Tests

```bash
python test_fitsec_integration.py
```

Expected output:
```
[OK] O0 (read_file) ALLOWED
[OK] O1 (write_file) ALLOWED
[OK] O2 (exec) DENIED by default
[OK] O2 (exec) ALLOWED with approval
[OK] Emptiness blocks O1+ tools
[OK] O0 allowed during Emptiness
```

## FIT Framework Reference

For more details on the FIT Framework theory:
- Omega Taxonomy: Blast radius classification for safe defaults
- Monitorability Gate: FPR controllability before high-stakes actions
- Emptiness Window: Remove commit power while preserving cognition

## License

MIT License (same as nanoBot)
