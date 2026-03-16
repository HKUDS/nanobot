# Project Documentation

- **Generated at:** 2026-03-16 23:11:04
- **Root Dir:** `nanobot/heartbeat`
- **File Count:** 2
- **Total Size:** 6.15 KB
 claude解读；

 *Thinking...*

> The user wants a detailed explanation of this codebase. Let me provide a thorough walkthrough of the HeartbeatService module.

# HeartbeatService 详细解释

## 概览

这是一个**心跳服务**模块，属于 `nanobot` 项目的一部分。它的核心职责是：**定期唤醒一个 AI agent，让它检查是否有待办任务，如果有就执行并通知用户。**

整个设计分为两个阶段（Phase 1 决策 + Phase 2 执行），下面逐层拆解。

---

## `__init__.py`

这个文件非常简单，只是把 `HeartbeatService` 类从 `service.py` 中导出，使外部可以通过 `from nanobot.heartbeat import HeartbeatService` 直接引用。

---

## `service.py` 逐段解析

### 1. 虚拟工具定义 `_HEARTBEAT_TOOL`

```python
_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],
                    },
                    "tasks": {
                        "type": "string",
                    },
                },
                "required": ["action"],
            },
        },
    }
]
```

这是一个 OpenAI 风格的 **function calling / tool use** 定义。它不是一个真正会被执行的外部工具，而是一个"虚拟工具"——目的是**强迫 LLM 以结构化 JSON 的形式返回决策结果**，而不是自由文本。LLM 被要求调用这个工具，传入两个参数：`action`（`"skip"` 或 `"run"`）和 `tasks`（任务的自然语言摘要）。这比解析自由文本或依赖特定 token（文档中提到的 `HEARTBEAT_OK`）要可靠得多。

### 2. 构造函数 `__init__`

```python
def __init__(self, workspace, provider, model, on_execute, on_notify, interval_s, enabled):
```

各参数的含义：

**`workspace: Path`** — 工作目录路径，`HEARTBEAT.md` 文件就放在这个目录下。这个文件是 agent 的"任务清单"或"状态文件"，外部系统或用户往里写入待办事项。

**`provider: LLMProvider`** — LLM 提供者的抽象接口（比如 OpenAI、Anthropic 等）。通过 `TYPE_CHECKING` 条件导入来避免循环引用，运行时只用于类型提示。

**`model: str`** — 使用的模型名称，如 `"gpt-4"` 等。

**`on_execute: Callable[[str], Coroutine]`** — 一个异步回调函数。当 Phase 1 判定有任务时，Phase 2 会调用它，传入任务摘要字符串，由它驱动完整的 agent 循环来执行任务。返回值是执行结果字符串。

**`on_notify: Callable[[str], Coroutine]`** — 另一个异步回调，用于把执行结果"投递"给用户（比如发送消息到 Discord、Telegram 等）。

**`interval_s: int`** — 心跳间隔，默认 1800 秒（30 分钟）。

**`enabled: bool`** — 是否启用心跳。

内部状态方面，`_running` 是一个布尔标志控制循环是否继续，`_task` 保存 `asyncio.Task` 的引用以便取消。

### 3. 读取心跳文件

```python
@property
def heartbeat_file(self) -> Path:
    return self.workspace / "HEARTBEAT.md"

def _read_heartbeat_file(self) -> str | None:
```

这里很直接：拼出 `HEARTBEAT.md` 的完整路径，尝试读取其文本内容。如果文件不存在或读取失败，返回 `None`。`HEARTBEAT.md` 是整个心跳机制的**输入源**——它记录了当前有哪些待办任务、定时提醒、周期性工作等信息。

### 4. Phase 1：决策 `_decide`

```python
async def _decide(self, content: str) -> tuple[str, str]:
```

这是心跳的第一阶段。它把 `HEARTBEAT.md` 的内容发给 LLM，同时附上 `_HEARTBEAT_TOOL` 工具定义。System prompt 告诉 LLM "你是一个心跳 agent，调用 heartbeat 工具来报告你的决策"。

LLM 阅读任务文件后，有两种情况：如果文件里没有需要执行的任务，它会调用 `heartbeat(action="skip")`；如果有活跃任务，它会调用 `heartbeat(action="run", tasks="...")`，其中 `tasks` 是任务的自然语言摘要。

如果 LLM 出于某种原因没有产生 tool call（`response.has_tool_calls` 为 `False`），则默认视为 `"skip"`。这是一种安全的降级策略。

### 5. 启动与停止

```python
async def start(self) -> None:
def stop(self) -> None:
```

`start()` 创建一个 `asyncio.Task` 来运行 `_run_loop`，这是标准的异步后台任务模式。它有防重入保护（`if self._running`）。`stop()` 设置 `_running = False` 并取消任务。

### 6. 主循环 `_run_loop`

```python
async def _run_loop(self) -> None:
    while self._running:
        await asyncio.sleep(self.interval_s)
        if self._running:
            await self._tick()
```

每隔 `interval_s` 秒执行一次 `_tick()`。注意 `sleep` 之后会再次检查 `_running`，因为在等待期间可能已经被 `stop()` 了。`CancelledError` 被捕获后直接 `break` 退出循环，其他异常则记录日志但不中断循环——这保证了心跳服务的鲁棒性，单次失败不会导致整个服务崩溃。

### 7. 单次心跳 `_tick`

这是整个模块最核心的方法，完整的两阶段流程在这里串联：

**步骤一**：读取 `HEARTBEAT.md`。如果文件不存在或为空，直接返回，记录 debug 日志。

**步骤二（Phase 1）**：调用 `_decide(content)` 让 LLM 判断是否有活跃任务。如果 `action != "run"`，记录日志后返回——这次心跳什么也不做。

**步骤三（Phase 2）**：如果有任务，调用 `self.on_execute(tasks)` 让完整的 agent 循环去执行任务，得到执行结果 `response`。

**步骤四（后评估）**：这里引入了一个有趣的机制——`evaluate_response`。它是从 `nanobot.utils.evaluator` 延迟导入的（放在方法内部而非文件顶部，可能是为了避免循环导入或加快模块加载）。这个评估器会再次用 LLM 判断执行结果是否值得通知用户。如果评估通过（`should_notify` 为 `True`），才调用 `self.on_notify(response)` 投递结果；否则静默丢弃，记录"silenced by post-run evaluation"。这个设计防止了低质量或无意义的响应打扰用户。

### 8. 手动触发 `trigger_now`

```python
async def trigger_now(self) -> str | None:
```

提供了一个不等待定时器、立即执行一次心跳的接口。注意它**不经过后评估和通知流程**，只返回执行结果给调用者。这适合调试或手动触发场景。

---

## 设计亮点总结

**Tool Call 代替文本解析**：用 function calling 机制让 LLM 输出结构化 JSON，避免了正则匹配或特殊 token 的脆弱性。这是当前 LLM 应用开发中的最佳实践。

**两阶段架构**：先用轻量的 Phase 1 判断是否需要行动，只在必要时才触发昂贵的 Phase 2 全量 agent 执行。这在成本控制上非常合理——大多数心跳周期可能都是"无事发生"，只需一次简短的 LLM 调用即可。

**后评估门控**：即使 agent 执行了任务并产生了结果，还有一道"质量关卡"决定是否通知用户。这种多层过滤的设计减少了误报和噪音。

**回调解耦**：`on_execute` 和 `on_notify` 都是外部注入的回调，心跳服务本身不关心任务怎么执行、结果怎么投递。这使得它可以被不同的上层系统复用（Discord bot、Telegram bot、Web 应用等）。

**容错性**：主循环中异常不会终止服务，文件读取失败有优雅降级，LLM 不返回 tool call 时有默认行为。整体是一个健壮的后台服务设计。

<a name="toc"></a>
## 📂 扫描目录
- [__init__.py](#📄-__init__py) (5 lines, 0.14 KB)
- [service.py](#📄-servicepy) (182 lines, 6.01 KB)

---

## 📄 __init__.py

````python
"""Heartbeat service for periodic agent wake-ups."""

from nanobot.heartbeat.service import HeartbeatService

__all__ = ["HeartbeatService"]

````

[⬆ 回到目录](#toc)

## 📄 service.py

````python
"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],
                        "description": "skip = nothing to do, run = has active tasks",
                    },
                    "tasks": {
                        "type": "string",
                        "description": "Natural-language summary of active tasks (required for run)",
                    },
                },
                "required": ["action"],
            },
        },
    }
]


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    Phase 1 (decision): reads HEARTBEAT.md and asks the LLM — via a virtual
    tool call — whether there are active tasks.  This avoids free-text parsing
    and the unreliable HEARTBEAT_OK token.

    Phase 2 (execution): only triggered when Phase 1 returns ``run``.  The
    ``on_execute`` callback runs the task through the full agent loop and
    returns the result to deliver.
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,
        enabled: bool = True,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    async def _decide(self, content: str) -> tuple[str, str]:
        """Phase 1: ask LLM to decide skip/run via virtual tool call.

        Returns (action, tasks) where action is 'skip' or 'run'.
        """
        response = await self.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision."},
                {"role": "user", "content": (
                    "Review the following HEARTBEAT.md and decide whether there are active tasks.\n\n"
                    f"{content}"
                )},
            ],
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            return "skip", ""

        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", "")

    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return
        if self._running:
            logger.warning("Heartbeat already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)

    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: {}", e)

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        from nanobot.utils.evaluator import evaluate_response

        content = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            return

        logger.info("Heartbeat: checking for tasks...")

        try:
            action, tasks = await self._decide(content)

            if action != "run":
                logger.info("Heartbeat: OK (nothing to report)")
                return

            logger.info("Heartbeat: tasks found, executing...")
            if self.on_execute:
                response = await self.on_execute(tasks)

                if response:
                    should_notify = await evaluate_response(
                        response, tasks, self.provider, self.model,
                    )
                    if should_notify and self.on_notify:
                        logger.info("Heartbeat: completed, delivering response")
                        await self.on_notify(response)
                    else:
                        logger.info("Heartbeat: silenced by post-run evaluation")
        except Exception:
            logger.exception("Heartbeat execution failed")

    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        content = self._read_heartbeat_file()
        if not content:
            return None
        action, tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None
        return await self.on_execute(tasks)

````

[⬆ 回到目录](#toc)

---
### 📊 最终统计汇总
- **文件总数:** 2
- **代码总行数:** 187
- **物理总大小:** 6.15 KB
