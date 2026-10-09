# How to Run a Long-Running AI Agent with nanobot

nanobot can keep agent work alive across turns through sustained goals,
persistent sessions, scheduled automations, local triggers, and a gateway
process that stays running.

## What you will build

- a working local agent
- a persistent chat session
- a long-running goal or automation
- a gateway process for background delivery

## When to use this

Use this when the task is not a one-shot answer: project work, recurring checks,
scheduled summaries, file maintenance, multi-step research, or local triggers
from scripts and build jobs.

## Install

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

## Minimal working example

Start a gateway:

```bash
nanobot gateway
```

From the WebUI or a chat session, start a sustained goal:

```text
/goal Review this workspace, identify missing tests, and propose the smallest next fix.
```

For scheduled or trigger-based runs, create the automation from the target chat
so nanobot can link it to the correct session and workspace.

## Review task completion

For work with concrete deliverables, ask for independent completion review and
state the acceptance criteria in your `/goal` request. The agent records these
in the optional `acceptance_criteria` field of `create_goal`. For example:

```text
/goal Create report.csv with one row per input record. Require independent
completion review: read the saved file, check its row count against the input,
and show that its required columns are present before marking the goal complete.
```

Delegated work supports the same option on `subagent` with `action="create"`.
The task and criteria are fixed at creation. A follow-up message does not weaken
them. Replacing a goal requires a new explicit user request.

The review uses a separate context with the same configured model, the proposed
result, and tool calls and results observed in the current run. It excludes the
executor's reasoning and prior conversation. Collect fresh evidence after changing
the deliverable; a claim that a file exists or a test passed is not a tool receipt.
The reviewer has no tools and cannot independently open files or external services.
This is a semantic assessment of observed evidence, not a guarantee that the model
is correct or that external state cannot change afterward.

There are at most two review attempts per goal or child task, each limited to
30 seconds and 1024 output tokens (or the model's smaller configured limit).
Provider retries remain subject to that timeout. Evidence exceeding 64,000
serialized characters is rejected rather than silently trimmed. Review usage is
included in run totals. A rejected child result can be revised within its original
iteration budget; review attempts do not reset that budget.

| Review result | Behavior |
| --- | --- |
| `verified` | Accept the result. A goal returns its reviewed recap immediately, with no further tools in that run. |
| `needs_revision` | Continue with specific feedback while review and execution budgets remain. |
| `blocked` | Do not claim completion when review is unavailable, invalid, or lacks sufficient evidence. |
| `exhausted` | Stop without a completion claim when the review or execution budget is spent. |

Child status and notifications include the verdict, evidence references, and a
SHA-256 fingerprint of the reviewed objective, candidate, and evidence. An
unfinished or unverified child cannot establish that dependent work is complete.
The fingerprint identifies that review snapshot; it is not a file integrity monitor.
Check delivery receipts for follow-ups sent while a child is being reviewed.
An `accepted` message may remain `undelivered` if the task ends before consuming
it; submit that follow-up as new work rather than treating it as verified.

Ordinary chat and tasks without `acceptance_criteria` make no extra review requests.
Their existing execution status is preserved; a child marked `done` without a
review means its run ended, not that its objective was independently accepted.
Model refusals, content filtering, and unrecovered output truncation are reported
as distinct stop reasons and cannot mark a child successful.

## Production notes

- Keep the gateway running for chat apps, WebUI sessions, automations, and local
  triggers.
- Use stable session keys or chat sessions for work that should preserve context.
- Keep goals bounded and explicit about done-ness.
- Review Automations in the WebUI before relying on a schedule.

## Security notes

- Treat long-running goals as delegated work with real tool access.
- Restrict workspaces and shell execution before scheduling unattended tasks.
- Keep chat access narrow so unknown users cannot create goals or automations.

## Troubleshooting

- If a goal appears stuck, inspect the active session and gateway logs.
- If an automation does not run, check that it is linked to a chat/session and
  that the gateway is still running.
- If a local trigger fails, check the command copied from the WebUI Automations
  view.

## Related nanobot docs

- [Automations](../automations.md)
- [WebUI Automations](../webui.md#automations)
- [Chat Commands](../chat-commands.md)
- [Memory](../memory.md)
- [Deployment](../deployment.md)
