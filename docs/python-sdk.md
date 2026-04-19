# Python SDK

Use nanobot as a library — no CLI, no gateway, just Python:

```python
from nanobot import Nanobot

bot = Nanobot.from_config()
result = await bot.run("Summarize the README")
print(result.content)
```

Each call carries a `session_key` for conversation isolation — different keys get independent history:

```python
await bot.run("hi", session_key="user-alice")
await bot.run("hi", session_key="task-42")
```

Add lifecycle hooks to observe or customize the agent:

```python
from nanobot.agent import AgentHook, AgentHookContext

class AuditHook(AgentHook):
    async def before_execute_tools(self, ctx: AgentHookContext) -> None:
        for tc in ctx.tool_calls:
            print(f"[tool] {tc.name}")

result = await bot.run("Hello", hooks=[AuditHook()])
```
