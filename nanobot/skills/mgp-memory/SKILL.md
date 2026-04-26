---
name: mgp-memory
description: Cross-session long-term memory via MGP. Call recall_memory when you need user-specific past context.
always: true
---

# Long-term Memory (MGP)

You have access to a governed long-term memory store via the `recall_memory` tool.
It contains facts about the current user that were learned across previous sessions
and channels (e.g. preferences, decisions, project context). The store is
maintained automatically — your job is only to **read** from it when relevant.

## When to call `recall_memory`

Call it when ALL of these are true:

- The current question would benefit from past context not visible in your system prompt
- The likely-relevant fact is user-specific (preferences, decisions, history)
- You can express the relevant fact as a short search query

Strong triggers (call without hesitation):

- User says "remember", "I told you", "as I mentioned before", "我之前说过", "还记得吗"
- User asks "what is my X", "what did I say about Y"
- User references a project / setting / preference by name without context

Weak triggers (consider but don't always call):

- A new request might benefit from prior preferences ("write me an email" → maybe recall communication style)
- Cross-channel continuation (user just switched from one channel to another)

## When NOT to call

- The information is already in your system prompt (`MEMORY.md` / `SOUL.md` / `USER.md` / Recent History)
- The question is general knowledge ("what is python")
- Pure code/tool task with no user-specific context needed
- You already called `recall_memory` this turn and got results — don't loop

## Calling pattern

`recall_memory(query="<concise topic>", scope="user", limit=5)`

- `query`: write the **topic**, NOT a full question.
  - Good: `"indentation preference"`, `"project codename"`, `"deployment style"`
  - Bad: `"what indentation do I prefer?"`, `"can you tell me my project name?"`
- `scope`: usually `"user"`. Use `"agent"` only for stable facts about the bot itself.
- `limit`: defaults to 5; ask for more (up to 20) only when the topic is broad.
- `types`: optional filter (`preference` / `semantic_fact` / `profile` / `episodic_event`)

Cite recalled facts naturally in your reply; do NOT quote tool output verbatim.

## Examples

User: `Help me write a deployment script`
Action: skip recall (no clear past-context need)

User: `Use my usual deployment style`
Action: `recall_memory(query="deployment style preferences")`

User: `我之前说过的项目代号是什么？`
Action: `recall_memory(query="project codename")`

User: `Why did we pick postgres again?`
Action: `recall_memory(query="postgres decision rationale")`

User: `What's my favorite IDE?`
Action: `recall_memory(query="IDE preference", types=["preference"])`

## Notes

- Recall is fail-open: if the MGP gateway is unreachable the tool returns
  `[recall_memory degraded: ...]`. Treat that as "no extra context available"
  and answer based on what you do know.
- Recall is read-only. Memories are written automatically by background
  consolidation — you do not need (and cannot) call any "remember" tool.
- `/mgp-status` shows the latest recall outcome and connection state for
  troubleshooting.
