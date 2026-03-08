---
name: incident
description: "Detect and respond to production incidents. Coordinate incident response across agents via Paperclip — escalate, delegate, track status, and communicate updates to stakeholders. Use when something is broken in production, a service is down, alerts fire, or a critical bug is reported."
---

# Incident Response

Coordinate incident response when something is broken or degraded.

## Incident Detection

Trigger this workflow when any of:
- User reports a service is down or broken
- Error rates spike in logs or monitoring
- CI/CD pipeline is broken on main branch
- Security issue is reported
- Another agent reports a failure

## Response Flow

### 1. Assess

Gather facts before acting:
- What is broken? (service, feature, endpoint)
- Since when? (timestamp, recent deploy, recent change)
- Who is affected? (all users, subset, internal only)
- What is the blast radius? (one service, cascading, data loss risk)

### 2. Classify Severity

| Severity | Criteria |
|----------|----------|
| **SEV-1** | Full outage, data loss, security breach |
| **SEV-2** | Major feature broken, significant user impact |
| **SEV-3** | Degraded performance, partial outage, workaround exists |

### 3. Escalate

```
mcp_paperclip_create_issue(
  title="[INC] <brief description>",
  description="Severity: <SEV-N>\nImpact: <who/what affected>\nSince: <when>\nDetails: <facts gathered>",
  priority="critical",
  labels=["incident", "sev-<N>"]
)
```

For SEV-1 and SEV-2:
```
mcp_paperclip_wake_agent(agent="<on-call or best agent>", reason="SEV-<N> incident: <description>")
```

### 4. Communicate

- Acknowledge to the reporter immediately
- Post status update to relevant channels
- If customer-facing: send a brief, honest status message

### 5. Track

- Update the Paperclip issue with new findings
- Log each status change with timestamp
- When resolved: update issue with resolution summary and root cause

## Communication Templates

**Initial acknowledgment:**
> We're aware of {issue} and investigating. Severity: {sev}. Updates to follow.

**Status update:**
> Update on {issue}: {finding}. Current status: {investigating|mitigating|resolved}. ETA: {estimate or "assessing"}.

**Resolution:**
> {issue} is resolved. Root cause: {cause}. Fix: {what was done}. We'll follow up with a post-mortem.

## Post-Incident

After resolution:
1. Update the Paperclip issue with root cause and timeline
2. Create follow-up issues for preventive measures
3. Report costs incurred during incident response
