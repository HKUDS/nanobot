# Project Documentation

- **Generated at:** 2026-03-16 23:10:57
- **Root Dir:** `nanobot/cron`
- **File Count:** 3
- **Total Size:** 14.57 KB

claude 解读
*Thinking...*

> The user has shared a project documentation file for a `nanobot/cron` module and asked for a detailed explanation (详细解读). Let me analyze the code thoroughly and explain it in Chinese since the document uses Chinese headers and the request is in Chinese.
> 
> Let me break down the architecture and explain each component.

# nanobot/cron 模块详细解读

## 整体架构

这是一个轻量级的异步定时任务调度服务，设计目标是为 AI Agent 提供定时执行能力。整个模块由三个文件组成，职责划分清晰：`types.py` 定义数据结构，`service.py` 实现核心调度逻辑，`__init__.py` 暴露公共接口。

---

## types.py — 数据模型层

这个文件用纯 dataclass 定义了五个核心数据结构，没有任何业务逻辑，完全是数据载体。

**CronSchedule** 是调度策略的抽象，通过 `kind` 字段区分三种模式："at" 表示在某个精确时间点执行一次（一次性定时器），"every" 表示按固定间隔重复执行（周期定时器），"cron" 表示使用标准 cron 表达式进行复杂的周期调度（如"每天早上9点"）。时间统一使用毫秒级时间戳，`tz` 字段仅对 cron 表达式生效，用于处理时区问题。

**CronPayload** 定义了任务触发时要做什么。`kind` 有两种取值："agent_turn" 表示触发一次 Agent 对话轮次，"system_event" 表示系统事件。`message` 是发给 Agent 的消息内容，`deliver`、`channel`、`to` 三个字段组合起来控制是否将 Agent 的回复投递到外部渠道（比如 WhatsApp）。

**CronJobState** 是运行时状态，记录下次执行时间、上次执行时间、上次执行结果及错误信息。这个状态会随任务执行不断更新并持久化。

**CronJob** 是核心实体，将上述三者组合在一起，加上 id、name、enabled 等元数据。`delete_after_run` 标记是否在执行完后自动删除（用于一次性任务的清理）。

**CronStore** 是持久化容器，包含一个 version 字段（预留给未来的数据迁移）和 jobs 列表。

---

## service.py — 核心调度引擎

### 辅助函数

`_now_ms()` 返回当前毫秒级时间戳，作为全局时间源。

`_compute_next_run(schedule, now_ms)` 是调度算法的核心，根据不同的 schedule kind 计算下一次执行时间。对于 "at" 类型，如果目标时间已过则返回 None（不再执行）；对于 "every" 类型，直接在当前时间上加间隔；对于 "cron" 类型，使用第三方库 `croniter` 解析 cron 表达式并计算下一个匹配时刻，同时支持通过 `zoneinfo` 处理时区。值得注意的是 croniter 和 zoneinfo 都是延迟导入的（lazy import），这意味着如果不使用 cron 表达式，这两个依赖就不需要安装。

`_validate_schedule_for_add(schedule)` 在添加任务时做前置校验，确保 tz 只用于 cron 类型，以及时区名称合法。

### CronService 类

**初始化与持久化机制：** 构造函数接收一个 `store_path`（JSON 文件路径）和一个可选的 `on_job` 回调。`_load_store()` 负责从磁盘读取任务数据，其中有一个巧妙的设计——它会检查文件的 `st_mtime`（修改时间），如果文件被外部修改过（比如人工编辑 JSON），就会自动重新加载。这使得运维人员可以直接修改 JSON 文件来调整任务，而不必通过 API。`_save_store()` 将内存中的状态序列化回磁盘，JSON 使用了 `indent=2` 美化输出，方便人类阅读。

序列化格式采用 camelCase（如 `nextRunAtMs`、`everyMs`），而 Python 内部用 snake_case，两者在 `_load_store` 和 `_save_store` 中做手动映射。这种设计说明 JSON 文件可能会被前端或其他非 Python 组件消费。

**调度引擎的核心循环：** 这个服务没有使用传统的 polling（轮询）模式，而是采用了事件驱动的 timer-based 架构。`_arm_timer()` 方法计算出所有任务中最近的一个执行时间，然后创建一个 `asyncio.Task`，用 `asyncio.sleep` 精确等待到那个时刻再唤醒。这种设计比固定间隔轮询高效得多——如果下一个任务在一小时后，进程在这一小时内不会有任何无意义的唤醒。

当 timer 到期时，`_on_timer()` 被调用，它重新加载 store（处理外部修改的情况），找出所有到期的任务，逐个执行，然后保存状态并重新 arm 下一个 timer。

**任务执行：** `_execute_job()` 调用外部传入的 `on_job` 回调，捕获异常并记录到任务状态中。执行完成后，对于 "at" 类型的一次性任务，要么删除（`delete_after_run=True`），要么禁用并清空 next_run；对于重复任务，则重新计算下一次执行时间。

**公共 API：** 提供了五个操作：`list_jobs` 列出任务（默认只显示启用的，按下次执行时间排序），`add_job` 添加任务，`remove_job` 删除任务，`enable_job` 启用/禁用任务，`run_job` 手动触发执行。每个写操作之后都会调用 `_save_store()` 和 `_arm_timer()`，确保持久化和调度器状态一致。`run_job` 的 `force` 参数允许强制执行已禁用的任务，这在调试时很有用。

---

## 设计特点与潜在问题

**优点方面：** 整体设计简洁且实用。使用文件系统 JSON 作为存储，避免了数据库依赖，适合单实例部署的轻量场景。mtime 检测机制让手动编辑成为可能。延迟导入 croniter 减少了必需依赖。事件驱动的 timer 机制比轮询高效。

**值得注意的点：** 第一，`_execute_job` 中调用了两次 `_now_ms()`——一次在开始时记录 `start_ms`，一次在结束时计算下次执行时间。如果 `on_job` 回调执行时间很长（比如 Agent 思考了30秒），那么 "every" 类型任务的间隔实际上是 `every_ms + 执行耗时`，而不是严格的 `every_ms` 间隔。这可能是有意为之（避免任务堆积），但没有文档说明。

第二，所有到期任务是顺序执行的（`for job in due_jobs: await self._execute_job(job)`），不是并发执行。如果同一时刻有多个任务到期，且每个任务执行较慢，后面的任务会被延迟。

第三，`id` 使用 `uuid4()[:8]`（只取前8个字符），在任务数量很少时碰撞概率极低，但理论上不保证唯一性。

第四，没有并发保护。如果多个协程同时调用 `add_job` 和 `_on_timer`，可能出现竞态条件。不过在单个 asyncio event loop 中，由于 GIL 和协程调度的特性，只要没有 await 穿插，这通常不是问题。

第五，store 的 `version` 字段目前硬编码为1，加载时也没有版本检查逻辑，说明这是为未来数据迁移预留的扩展点。

<a name="toc"></a>
## 📂 扫描目录
- [__init__.py](#📄-__init__py) (6 lines, 0.19 KB)
- [service.py](#📄-servicepy) (376 lines, 12.83 KB)
- [types.py](#📄-typespy) (59 lines, 1.55 KB)

---

## 📄 __init__.py

````python
"""Cron service for scheduled agent tasks."""

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronSchedule

__all__ = ["CronService", "CronJob", "CronSchedule"]

````

[⬆ 回到目录](#toc)

## 📄 service.py

````python
"""Cron service for scheduling agent tasks."""

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """Compute next run time in ms."""
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None

    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        # Next interval from now
        return now_ms + schedule.every_ms

    if schedule.kind == "cron" and schedule.expr:
        try:
            from zoneinfo import ZoneInfo

            from croniter import croniter
            # Use caller-provided reference time for deterministic scheduling
            base_time = now_ms / 1000
            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
            base_dt = datetime.fromtimestamp(base_time, tz=tz)
            cron = croniter(schedule.expr, base_dt)
            next_dt = cron.get_next(datetime)
            return int(next_dt.timestamp() * 1000)
        except Exception:
            return None

    return None


def _validate_schedule_for_add(schedule: CronSchedule) -> None:
    """Validate schedule fields that would otherwise create non-runnable jobs."""
    if schedule.tz and schedule.kind != "cron":
        raise ValueError("tz can only be used with cron schedules")

    if schedule.kind == "cron" and schedule.tz:
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(schedule.tz)
        except Exception:
            raise ValueError(f"unknown timezone '{schedule.tz}'") from None


class CronService:
    """Service for managing and executing scheduled jobs."""

    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None
    ):
        self.store_path = store_path
        self.on_job = on_job
        self._store: CronStore | None = None
        self._last_mtime: float = 0.0
        self._timer_task: asyncio.Task | None = None
        self._running = False

    def _load_store(self) -> CronStore:
        """Load jobs from disk. Reloads automatically if file was modified externally."""
        if self._store and self.store_path.exists():
            mtime = self.store_path.stat().st_mtime
            if mtime != self._last_mtime:
                logger.info("Cron: jobs.json modified externally, reloading")
                self._store = None
        if self._store:
            return self._store

        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
                jobs = []
                for j in data.get("jobs", []):
                    jobs.append(CronJob(
                        id=j["id"],
                        name=j["name"],
                        enabled=j.get("enabled", True),
                        schedule=CronSchedule(
                            kind=j["schedule"]["kind"],
                            at_ms=j["schedule"].get("atMs"),
                            every_ms=j["schedule"].get("everyMs"),
                            expr=j["schedule"].get("expr"),
                            tz=j["schedule"].get("tz"),
                        ),
                        payload=CronPayload(
                            kind=j["payload"].get("kind", "agent_turn"),
                            message=j["payload"].get("message", ""),
                            deliver=j["payload"].get("deliver", False),
                            channel=j["payload"].get("channel"),
                            to=j["payload"].get("to"),
                        ),
                        state=CronJobState(
                            next_run_at_ms=j.get("state", {}).get("nextRunAtMs"),
                            last_run_at_ms=j.get("state", {}).get("lastRunAtMs"),
                            last_status=j.get("state", {}).get("lastStatus"),
                            last_error=j.get("state", {}).get("lastError"),
                        ),
                        created_at_ms=j.get("createdAtMs", 0),
                        updated_at_ms=j.get("updatedAtMs", 0),
                        delete_after_run=j.get("deleteAfterRun", False),
                    ))
                self._store = CronStore(jobs=jobs)
            except Exception as e:
                logger.warning("Failed to load cron store: {}", e)
                self._store = CronStore()
        else:
            self._store = CronStore()

        return self._store

    def _save_store(self) -> None:
        """Save jobs to disk."""
        if not self._store:
            return

        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": self._store.version,
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "enabled": j.enabled,
                    "schedule": {
                        "kind": j.schedule.kind,
                        "atMs": j.schedule.at_ms,
                        "everyMs": j.schedule.every_ms,
                        "expr": j.schedule.expr,
                        "tz": j.schedule.tz,
                    },
                    "payload": {
                        "kind": j.payload.kind,
                        "message": j.payload.message,
                        "deliver": j.payload.deliver,
                        "channel": j.payload.channel,
                        "to": j.payload.to,
                    },
                    "state": {
                        "nextRunAtMs": j.state.next_run_at_ms,
                        "lastRunAtMs": j.state.last_run_at_ms,
                        "lastStatus": j.state.last_status,
                        "lastError": j.state.last_error,
                    },
                    "createdAtMs": j.created_at_ms,
                    "updatedAtMs": j.updated_at_ms,
                    "deleteAfterRun": j.delete_after_run,
                }
                for j in self._store.jobs
            ]
        }

        self.store_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self._last_mtime = self.store_path.stat().st_mtime
    
    async def start(self) -> None:
        """Start the cron service."""
        self._running = True
        self._load_store()
        self._recompute_next_runs()
        self._save_store()
        self._arm_timer()
        logger.info("Cron service started with {} jobs", len(self._store.jobs if self._store else []))

    def stop(self) -> None:
        """Stop the cron service."""
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    def _recompute_next_runs(self) -> None:
        """Recompute next run times for all enabled jobs."""
        if not self._store:
            return
        now = _now_ms()
        for job in self._store.jobs:
            if job.enabled:
                job.state.next_run_at_ms = _compute_next_run(job.schedule, now)

    def _get_next_wake_ms(self) -> int | None:
        """Get the earliest next run time across all jobs."""
        if not self._store:
            return None
        times = [j.state.next_run_at_ms for j in self._store.jobs
                 if j.enabled and j.state.next_run_at_ms]
        return min(times) if times else None

    def _arm_timer(self) -> None:
        """Schedule the next timer tick."""
        if self._timer_task:
            self._timer_task.cancel()

        next_wake = self._get_next_wake_ms()
        if not next_wake or not self._running:
            return

        delay_ms = max(0, next_wake - _now_ms())
        delay_s = delay_ms / 1000

        async def tick():
            await asyncio.sleep(delay_s)
            if self._running:
                await self._on_timer()

        self._timer_task = asyncio.create_task(tick())

    async def _on_timer(self) -> None:
        """Handle timer tick - run due jobs."""
        self._load_store()
        if not self._store:
            return

        now = _now_ms()
        due_jobs = [
            j for j in self._store.jobs
            if j.enabled and j.state.next_run_at_ms and now >= j.state.next_run_at_ms
        ]

        for job in due_jobs:
            await self._execute_job(job)

        self._save_store()
        self._arm_timer()

    async def _execute_job(self, job: CronJob) -> None:
        """Execute a single job."""
        start_ms = _now_ms()
        logger.info("Cron: executing job '{}' ({})", job.name, job.id)

        try:
            response = None
            if self.on_job:
                response = await self.on_job(job)

            job.state.last_status = "ok"
            job.state.last_error = None
            logger.info("Cron: job '{}' completed", job.name)

        except Exception as e:
            job.state.last_status = "error"
            job.state.last_error = str(e)
            logger.error("Cron: job '{}' failed: {}", job.name, e)

        job.state.last_run_at_ms = start_ms
        job.updated_at_ms = _now_ms()

        # Handle one-shot jobs
        if job.schedule.kind == "at":
            if job.delete_after_run:
                self._store.jobs = [j for j in self._store.jobs if j.id != job.id]
            else:
                job.enabled = False
                job.state.next_run_at_ms = None
        else:
            # Compute next run
            job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())

    # ========== Public API ==========

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """List all jobs."""
        store = self._load_store()
        jobs = store.jobs if include_disabled else [j for j in store.jobs if j.enabled]
        return sorted(jobs, key=lambda j: j.state.next_run_at_ms or float('inf'))

    def add_job(
        self,
        name: str,
        schedule: CronSchedule,
        message: str,
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        delete_after_run: bool = False,
    ) -> CronJob:
        """Add a new job."""
        store = self._load_store()
        _validate_schedule_for_add(schedule)
        now = _now_ms()

        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            enabled=True,
            schedule=schedule,
            payload=CronPayload(
                kind="agent_turn",
                message=message,
                deliver=deliver,
                channel=channel,
                to=to,
            ),
            state=CronJobState(next_run_at_ms=_compute_next_run(schedule, now)),
            created_at_ms=now,
            updated_at_ms=now,
            delete_after_run=delete_after_run,
        )

        store.jobs.append(job)
        self._save_store()
        self._arm_timer()

        logger.info("Cron: added job '{}' ({})", name, job.id)
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        store = self._load_store()
        before = len(store.jobs)
        store.jobs = [j for j in store.jobs if j.id != job_id]
        removed = len(store.jobs) < before

        if removed:
            self._save_store()
            self._arm_timer()
            logger.info("Cron: removed job {}", job_id)

        return removed

    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        """Enable or disable a job."""
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                job.enabled = enabled
                job.updated_at_ms = _now_ms()
                if enabled:
                    job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
                else:
                    job.state.next_run_at_ms = None
                self._save_store()
                self._arm_timer()
                return job
        return None

    async def run_job(self, job_id: str, force: bool = False) -> bool:
        """Manually run a job."""
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                if not force and not job.enabled:
                    return False
                await self._execute_job(job)
                self._save_store()
                self._arm_timer()
                return True
        return False

    def status(self) -> dict:
        """Get service status."""
        store = self._load_store()
        return {
            "enabled": self._running,
            "jobs": len(store.jobs),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }

````

[⬆ 回到目录](#toc)

## 📄 types.py

````python
"""Cron types."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CronSchedule:
    """Schedule definition for a cron job."""
    kind: Literal["at", "every", "cron"]
    # For "at": timestamp in ms
    at_ms: int | None = None
    # For "every": interval in ms
    every_ms: int | None = None
    # For "cron": cron expression (e.g. "0 9 * * *")
    expr: str | None = None
    # Timezone for cron expressions
    tz: str | None = None


@dataclass
class CronPayload:
    """What to do when the job runs."""
    kind: Literal["system_event", "agent_turn"] = "agent_turn"
    message: str = ""
    # Deliver response to channel
    deliver: bool = False
    channel: str | None = None  # e.g. "whatsapp"
    to: str | None = None  # e.g. phone number


@dataclass
class CronJobState:
    """Runtime state of a job."""
    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_status: Literal["ok", "error", "skipped"] | None = None
    last_error: str | None = None


@dataclass
class CronJob:
    """A scheduled job."""
    id: str
    name: str
    enabled: bool = True
    schedule: CronSchedule = field(default_factory=lambda: CronSchedule(kind="every"))
    payload: CronPayload = field(default_factory=CronPayload)
    state: CronJobState = field(default_factory=CronJobState)
    created_at_ms: int = 0
    updated_at_ms: int = 0
    delete_after_run: bool = False


@dataclass
class CronStore:
    """Persistent store for cron jobs."""
    version: int = 1
    jobs: list[CronJob] = field(default_factory=list)

````

[⬆ 回到目录](#toc)

---
### 📊 最终统计汇总
- **文件总数:** 3
- **代码总行数:** 441
- **物理总大小:** 14.57 KB
