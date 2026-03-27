---
name: agent-router
description: Routes prompts to specialized agents defined in AGENT.md files.
always: true
---

# Agent Router

You have access to specialized agents defined as AGENT.md files. Use them to delegate tasks to the best-fit agent.

## Auto-Routing

When a user sends a message, check the agents summary in your system prompt. If an agent's description matches the user's intent:

1. Read the agent's AGENT.md file using `read_file` to get its full instructions
2. Parse the `allowed_tools` and `agent` from the frontmatter
3. Spawn a subagent with:
   - `task`: The user's request, plus any relevant conversation context (subagents have no history)
   - `label`: `"<agent-name>: <brief description>"`
   - `system_prompt`: The body of the AGENT.md (everything after the frontmatter)
   - `allowed_tools`: The tools list from the frontmatter
   - `agent`: The agent config name from the frontmatter (if specified) — this lets each agent use a fully configured provider with its own model, API key, temperature, etc.
4. Tell the user you've delegated the task (e.g., "I've sent this to the researcher agent...")

## Explicit Routing with @mention

If the user's message starts with `@agent-name` (e.g., `@coder fix the login bug`):
- Route directly to that agent, skipping auto-routing
- Strip the `@agent-name` prefix from the task string

## When NOT to Route

Do not spawn an agent for:
- Simple greetings or conversational messages
- Quick factual questions you can answer directly
- Tasks that don't match any agent's description
- Follow-up questions about a previous agent's result (summarize it yourself)

## Context Forwarding

Subagents don't have access to conversation history. When spawning, include relevant context in the `task` string:
- Key details from the conversation that the agent needs
- File paths or resources already discussed
- Any constraints or preferences the user mentioned
