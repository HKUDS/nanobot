---
name: triage
description: "Triage incoming messages from customers and colleagues. Classify urgency, create Paperclip issues for actionable items, escalate critical problems, and acknowledge the sender. Use when a message arrives that may require action, delegation, or tracking — especially from external users or cross-agent requests."
---

# Triage

Classify incoming messages and route them to the right action.

## Urgency Classification

| Level | Criteria | Action |
|-------|----------|--------|
| **critical** | Production down, data loss, security breach, blocked deployment | Immediately escalate via `mcp_paperclip_wake_agent`. Create issue with `priority: critical`. Acknowledge sender within 1 message. |
| **high** | Feature broken for users, CI failing on main, urgent customer request | Create Paperclip issue with `priority: high`. Ping relevant agent if known. Acknowledge sender. |
| **medium** | Bug report, feature request, non-blocking question | Create Paperclip issue with `priority: medium`. Acknowledge sender with expected timeline. |
| **low** | General feedback, cosmetic issue, nice-to-have | Create Paperclip issue with `priority: low`. Acknowledge sender. |

## Triage Flow

1. **Read** the message fully before classifying.
2. **Classify** urgency using the table above.
3. **Extract** actionable information:
   - What is the problem or request?
   - Who is affected?
   - What is the expected behavior vs actual behavior?
   - Any reproduction steps or context?
4. **Create issue** via `mcp_paperclip_create_issue`:
   ```
   mcp_paperclip_create_issue(
     title="<concise title>",
     description="<structured description>",
     priority="<critical|high|medium|low>",
     labels=["triage", "<category>"],
     reporter="<sender_id>"
   )
   ```
5. **Escalate** if critical: `mcp_paperclip_wake_agent(agent="<best agent>", reason="<why>")`
6. **Acknowledge** the sender with:
   - Confirmation the message was received
   - Issue reference (if created)
   - Expected next step or timeline
   - Who will handle it (if known)

## Delegation Guidelines

| Task Type | Delegate To | Why |
|-----------|-------------|-----|
| Deep code fix, refactor, architecture | Claude Code / senior engineer agent | Requires full codebase context and coding capability |
| Infrastructure, deployment, CI/CD | DevOps agent (if available) | Specialized tooling access |
| Simple config change, docs update | Handle directly | Within nanobot's capability |
| Customer follow-up, status update | Handle directly | Communications is nanobot's role |
| Unclear or ambiguous | Ask sender for clarification | Don't guess at requirements |

## Acknowledgment Templates

**Critical:**
> Received and escalating immediately. Created issue #{id}. The team is being notified now.

**High:**
> Got it. Created issue #{id} with high priority. This will be addressed promptly.

**Medium:**
> Thanks for reporting. Tracked as issue #{id}. We'll follow up soon.

**Low:**
> Noted — tracked as issue #{id}. We'll get to it when bandwidth allows.

## Anti-patterns

- Do NOT create duplicate issues. Search existing issues first if possible.
- Do NOT escalate medium/low items as critical.
- Do NOT promise specific timelines unless you have data to back them.
- Do NOT ignore messages. Every actionable message gets an acknowledgment.
