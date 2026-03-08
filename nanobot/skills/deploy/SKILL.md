---
name: deploy
description: "Coordinate deployments via Paperclip. Track release progress, delegate build/test/deploy tasks to appropriate agents, monitor CI/CD status, and communicate deployment status to stakeholders. Use when asked to deploy, release, ship, or coordinate a rollout."
---

# Deployment Coordination

Coordinate deployments across agents and track progress.

## Deployment Flow

### 1. Pre-deploy Checklist

Before initiating a deploy:
- [ ] All CI checks passing on the target branch
- [ ] No open critical/high issues blocking release
- [ ] Changelog or release notes prepared
- [ ] Relevant stakeholders notified

Verify CI status:
```bash
gh run list --repo <owner>/<repo> --branch <branch> --limit 5
```

### 2. Create Deploy Task

```
mcp_paperclip_create_issue(
  title="Deploy <repo> <version>",
  description="Release <version> to <environment>.\n\nChecklist:\n- [ ] CI green\n- [ ] Tests passed\n- [ ] Deploy executed\n- [ ] Smoke tests passed\n- [ ] Stakeholders notified",
  priority="high",
  labels=["deploy", "<environment>"]
)
```

### 3. Delegate

| Step | Delegate To | Tool |
|------|-------------|------|
| Build and test | Claude Code / CI | `mcp_paperclip_wake_agent` or monitor CI |
| Run deploy script | DevOps agent or self (if simple) | `exec` tool or delegation |
| Smoke test | Self or QA agent | Direct verification |
| Notify stakeholders | Self | `message` tool to channels |

### 4. Monitor

- Watch CI/CD pipeline progress
- Report status updates to the deploy issue
- If failure: escalate using the incident skill

### 5. Post-deploy

- Update the Paperclip issue with results
- Announce completion to relevant channels
- Report any cost incurred during deploy

## Rollback

If issues are detected post-deploy:
1. Assess severity (use incident skill if SEV-1/SEV-2)
2. Decide: fix-forward vs rollback
3. If rolling back: delegate to the agent that performed the deploy
4. Communicate rollback status to stakeholders

## Environment Labels

Use consistent labels: `production`, `staging`, `development`.
