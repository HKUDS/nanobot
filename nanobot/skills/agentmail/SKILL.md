---
name: agentmail
description: "Send and receive email programmatically using the AgentMail CLI. Use for reading inboxes, sending messages, replying to threads, and managing drafts."
metadata: {"nanobot":{"emoji":"📧","requires":{"bins":["agentmail"],"env":["AGENTMAIL_API_KEY"]}}}
---

# AgentMail Skill

Use the `agentmail` CLI to send and receive email. The binary is at `/usr/local/bin/agentmail` and `AGENTMAIL_API_KEY` is pre-configured in the environment.

## Your Inboxes

| Inbox ID | Email | Purpose |
|----------|-------|---------|
| `david-3609@agentmail.to` | david-3609@agentmail.to | kids-school |
| `davidzzz-2687@agentmail.to` | davidzzz-2687@agentmail.to | ZR |

## Read Email

```bash
# List recent messages in an inbox
agentmail inboxes:messages list --inbox-id david-3609@agentmail.to

# Read a specific message (get full body)
agentmail inboxes:messages retrieve --inbox-id david-3609@agentmail.to --message-id <message_id>

# List threads (grouped conversations)
agentmail inboxes:threads list --inbox-id david-3609@agentmail.to

# Read a full thread
agentmail inboxes:threads retrieve --inbox-id david-3609@agentmail.to --thread-id <thread_id>
```

## Send Email

```bash
# Send a new email
agentmail inboxes:messages send --inbox-id david-3609@agentmail.to \
  --to "recipient@example.com" \
  --subject "Hello" \
  --text "Message body"

# Reply to a message (keeps thread context)
agentmail inboxes:messages reply --inbox-id david-3609@agentmail.to \
  --message-id <message_id> \
  --text "Reply body"

# Forward a message
agentmail inboxes:messages forward --inbox-id david-3609@agentmail.to \
  --message-id <message_id> \
  --to "someone@example.com"
```

## Drafts

```bash
# Create a draft (review before sending)
agentmail inboxes:drafts create --inbox-id david-3609@agentmail.to \
  --to "recipient@example.com" \
  --subject "Draft subject" \
  --text "Draft body"

# Send a draft
agentmail inboxes:drafts send --inbox-id david-3609@agentmail.to --draft-id <draft_id>
```

## Output Format

Use `--format json` for structured output when parsing results:

```bash
agentmail inboxes:messages list --inbox-id david-3609@agentmail.to --format json
```

## Workflow Tips

- Always use `--format json` when you need to extract IDs from responses.
- To check for new mail, list messages and sort by `created_at`.
- For multi-turn conversations, use threads — `inboxes:threads retrieve` gives the full context.
- Draft first if the user wants to review before sending; confirm, then `drafts send`.
