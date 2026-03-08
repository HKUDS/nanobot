---
name: onboard
description: "Onboard nanobot into a Paperclip company. Register agent identity, discover colleagues and their capabilities, configure communication protocols, and verify connectivity. Use when setting up nanobot as a new Paperclip employee or when joining a new company."
---

# Paperclip Onboarding

Set up nanobot as an employee in a Paperclip company.

## Onboarding Flow

### 1. Register Identity

On first startup with Paperclip config present, register this agent:
```
mcp_paperclip_register(
  agent_name="<configured name>",
  capabilities=["communications", "triage", "scheduling", "cost-reporting"],
  channels=["<list of active channels>"],
  status="online"
)
```

### 2. Discover Colleagues

Query Paperclip for other active agents:
```
mcp_paperclip_list_agents()
```

For each colleague, note:
- Name and role
- Capabilities (coding, devops, testing, etc.)
- Current status (online, busy, offline)
- Preferred delegation method

Store this in memory for future delegation decisions.

### 3. Understand Directives

Read company directives from Paperclip config:
- Company name and mission
- This agent's role and responsibilities
- Budget constraints and cost awareness rules
- Escalation policies
- Communication tone and style guidelines

### 4. Verify Connectivity

Test each integration:
- [ ] Can create Paperclip issues
- [ ] Can query agent status
- [ ] Can receive events from Paperclip
- [ ] All configured channels are connected
- [ ] Heartbeat is being sent

### 5. Announce

Send a brief status message to the designated channel:
> {agent_name} is online and ready. Connected to {N} channels. {M} colleagues discovered.

## Re-onboarding

When restarting or reconnecting:
1. Re-register with current status
2. Refresh colleague list (agents may have changed)
3. Resume any in-progress tasks from last session
4. Report any missed events during downtime

## Health Maintenance

After onboarding, maintain presence via heartbeat:
- Send heartbeat at configured interval
- Include current status, active task count, channel health
- If heartbeat fails: log warning and retry with backoff
