# How to Run a Long-Running AI Agent with nanobot

nanobot can keep agent work alive across turns through sustained goals, persistent sessions, scheduled automations, local triggers, and a gateway process that stays running.

## What you will build

- a working local agent
- a persistent chat session
- a long-running goal or automation
- a gateway process for background delivery

## When to use this

Use this when the task is not a one-shot answer: project work, recurring checks, scheduled summaries, file maintenance, multi-step research, or local triggers from scripts and build jobs.

## Before you start

Use an installation with a configured model that has already returned a reply. If this is your first setup, follow [Quick Start](../quick-start.md), then return here. Existing WebUI users can continue in the current instance.

## Minimal working example

Your running WebUI or TUI already uses a gateway. In that chat, start a sustained goal:

```text
/goal Review this workspace, identify missing tests, and propose the smallest next fix.
```

For scheduled or trigger-based runs, create the automation from the target chat so nanobot can link it to the correct session and project context.

To keep work running after closing the interactive launcher, promote the existing gateway from a terminal:

```bash
nanobot gateway --background
nanobot gateway status
```

Use the same `--config` and explicit `--workspace` selectors as your instance. In the TUI, `/detach` also keeps the gateway running while closing the client. A background gateway does not survive a machine shutdown by itself; see [Deployment](../deployment.md) for service management. Review [schedule restart behavior](../automations.md#delivery-and-reliability) before relying on a timed task.

## Production notes

- Keep the gateway running for chat apps, WebUI sessions, automations, and local triggers.
- Use stable session keys or chat sessions for work that should preserve context.
- Keep goals bounded and explicit about done-ness.
- Review Automations in the WebUI before relying on a schedule.

## Security notes

- Treat long-running goals as delegated work with real tool access.
- Restrict workspaces and shell execution before scheduling unattended tasks.
- Keep chat access narrow so unknown users cannot create goals or automations.

## Troubleshooting

- If a goal appears stuck, inspect the active session and gateway logs.
- If an automation does not run, check that it is linked to a chat/session and that the gateway is still running.
- If a local trigger fails, check the command copied from the WebUI Automations view.

## Related nanobot docs

- [Automations](../automations.md)
- [WebUI Automations](../webui.md#automations)
- [Chat Commands](../chat-commands.md)
- [Memory](../memory.md)
- [Deployment](../deployment.md)
