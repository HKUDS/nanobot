"""Cron service for scheduling agent tasks."""

# 模块作用：定时任务服务，管理智能体的计划任务执行
# 设计目的：支持多种调度方式（定时、周期、cron表达式），持久化存储
# 好处：自动化任务执行，减少人工干预，支持复杂调度需求
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore


# 作用：获取当前时间戳（毫秒）
# 设计目的：统一时间单位，支持精确调度
def _now_ms() -> int:
    return int(time.time() * 1000)


# 作用：根据调度配置计算下次执行时间
# 设计目的：支持at（定点）、every（周期）、cron（表达式）三种调度类型
# 好处：灵活的任务调度，满足各种定时需求
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
            from croniter import croniter
            cron = croniter(schedule.expr, time.time())
            next_time = cron.get_next()
            return int(next_time * 1000)
        except Exception:
            return None
    
    return None


# 作用：定时任务服务核心类，管理任务生命周期和执行
# 设计目的：基于异步定时器的任务调度，支持持久化存储
# 好处：精确的任务调度，自动恢复，错误处理
class CronService:
    """Service for managing and executing scheduled jobs."""
    
    # 作用：初始化定时任务服务，设置存储路径和回调
    # 设计目的：依赖注入执行回调，支持自定义任务处理
    # 好处：灵活的任务执行，可测试性，解耦设计
    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None
    ):
        self.store_path = store_path
        self.on_job = on_job  # Callback to execute job, returns response text
        self._store: CronStore | None = None
        self._timer_task: asyncio.Task | None = None
        self._running = False
    
    # 作用：从磁盘加载任务存储，解析JSON格式
    # 设计目的：支持任务持久化，程序重启后恢复
    # 好处：任务不丢失，支持长期调度计划
    def _load_store(self) -> CronStore:
        """Load jobs from disk."""
        if self._store:
            return self._store
        
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text())
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
                logger.warning(f"Failed to load cron store: {e}")
                self._store = CronStore()
        else:
            self._store = CronStore()
        
        return self._store
    
    # 作用：将任务存储保存到磁盘，JSON格式
    # 设计目的：任务状态持久化，支持跨会话保持
    # 好处：任务状态同步，崩溃恢复，便于管理
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
        
        self.store_path.write_text(json.dumps(data, indent=2))
    
    # 作用：启动定时任务服务，加载任务并启动定时器
    # 设计目的：初始化服务状态，计算下次执行时间
    # 好处：自动恢复任务，精确调度，资源管理
    async def start(self) -> None:
        """Start the cron service."""
        self._running = True
        self._load_store()
        self._recompute_next_runs()
        self._save_store()
        self._arm_timer()
        logger.info(f"Cron service started with {len(self._store.jobs if self._store else [])} jobs")
    
    # 作用：停止定时任务服务，取消定时器
    # 设计目的：优雅关闭，防止任务泄漏
    # 好处：资源清理，可控关闭，状态保存
    def stop(self) -> None:
        """Stop the cron service."""
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
    
    # 作用：重新计算所有启用任务的下次执行时间
    # 设计目的：服务启动时校准任务时间
    # 好处：时间同步，防止任务遗漏
    def _recompute_next_runs(self) -> None:
        """Recompute next run times for all enabled jobs."""
        if not self._store:
            return
        now = _now_ms()
        for job in self._store.jobs:
            if job.enabled:
                job.state.next_run_at_ms = _compute_next_run(job.schedule, now)
    
    # 作用：获取所有任务中最早的下次执行时间
    # 设计目的：优化定时器唤醒时间，减少空转
    # 好处：精确唤醒，节省资源，高效调度
    def _get_next_wake_ms(self) -> int | None:
        """Get the earliest next run time across all jobs."""
        if not self._store:
            return None
        times = [j.state.next_run_at_ms for j in self._store.jobs 
                 if j.enabled and j.state.next_run_at_ms]
        return min(times) if times else None
    
    # 作用：设置下次定时器唤醒
    # 设计目的：基于最早执行时间计算延迟，创建异步任务
    # 好处：精确调度，自动重新设定，支持取消
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
    
    # 作用：定时器触发时执行到期的任务
    # 设计目的：查找并执行所有到期任务，重新设定定时器
    # 好处：批量处理，状态更新，连续调度
    async def _on_timer(self) -> None:
        """Handle timer tick - run due jobs."""
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
    
    # 作用：执行单个任务，处理回调和状态更新
    # 设计目的：封装任务执行逻辑，错误处理，状态管理
    # 好处：任务隔离，错误恢复，状态追踪
    async def _execute_job(self, job: CronJob) -> None:
        """Execute a single job."""
        start_ms = _now_ms()
        logger.info(f"Cron: executing job '{job.name}' ({job.id})")
        
        try:
            response = None
            if self.on_job:
                response = await self.on_job(job)
            
            job.state.last_status = "ok"
            job.state.last_error = None
            logger.info(f"Cron: job '{job.name}' completed")
            
        except Exception as e:
            job.state.last_status = "error"
            job.state.last_error = str(e)
            logger.error(f"Cron: job '{job.name}' failed: {e}")
        
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
    
    # 作用：列出所有任务，可选包含已禁用任务
    # 设计目的：提供任务概览，支持管理界面
    # 好处：任务管理，状态查看，排序展示
    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """List all jobs."""
        store = self._load_store()
        jobs = store.jobs if include_disabled else [j for j in store.jobs if j.enabled]
        return sorted(jobs, key=lambda j: j.state.next_run_at_ms or float('inf'))
    
    # 作用：添加新任务，生成ID并计算下次执行时间
    # 设计目的：支持多种调度类型，自动持久化
    # 好处：灵活的任务创建，立即生效，自动调度
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
        
        logger.info(f"Cron: added job '{name}' ({job.id})")
        return job
    
    # 作用：根据ID移除任务
    # 设计目的：支持任务删除，清理不需要的任务
    # 好处：任务生命周期管理，资源释放
    def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        store = self._load_store()
        before = len(store.jobs)
        store.jobs = [j for j in store.jobs if j.id != job_id]
        removed = len(store.jobs) < before
        
        if removed:
            self._save_store()
            self._arm_timer()
            logger.info(f"Cron: removed job {job_id}")
        
        return removed
    
    # 作用：启用或禁用任务
    # 设计目的：支持任务暂停和恢复，不删除任务
    # 好处：灵活的任务控制，临时停用，保留配置
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
    
    # 作用：手动立即执行任务
    # 设计目的：支持测试和立即执行需求
    # 好处：调试便利，紧急执行，任务验证
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
    
    # 作用：获取服务状态摘要
    # 设计目的：提供服务运行状态监控
    # 好处：健康检查，监控集成，故障排查
    def status(self) -> dict:
        """Get service status."""
        store = self._load_store()
        return {
            "enabled": self._running,
            "jobs": len(store.jobs),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }


# ============================================
# 示例说明：CronService 使用示例
# ============================================
#
# 1. 基本使用示例：
# ```python
# from pathlib import Path
# from nanobot.cron.service import CronService
# from nanobot.cron.types import CronSchedule
# import asyncio
#
# async def example():
#     # 定义任务执行回调
#     async def on_job(job):
#         print(f"执行任务: {job.name}")
#         print(f"消息内容: {job.payload.message}")
#         return "任务执行成功"
#     
#     # 创建定时任务服务
#     store_path = Path("/path/to/cron_store.json")
#     cron = CronService(store_path, on_job=on_job)
#     
#     # 启动服务
#     await cron.start()
#     
#     # 添加定点执行任务（at）
#     from nanobot.cron.types import CronSchedule
#     job1 = cron.add_job(
#         name="每日提醒",
#         schedule=CronSchedule(kind="at", at_ms=time.time() * 1000 + 60000),  # 1分钟后
#         message="记得喝水！",
#         deliver=True,
#         channel="telegram",
#         to="user123"
#     )
#     print(f"添加任务: {job1.id}")
#     
#     # 添加周期执行任务（every）
#     job2 = cron.add_job(
#         name="定期备份",
#         schedule=CronSchedule(kind="every", every_ms=3600000),  # 每小时
#         message="执行数据库备份",
#         deliver=False
#     )
#     
#     # 添加cron表达式任务
#     job3 = cron.add_job(
#         name="每日报告",
#         schedule=CronSchedule(kind="cron", expr="0 9 * * *"),  # 每天9点
#         message="生成昨日工作报告",
#         deliver=True,
#         channel="email",
#         to="admin@example.com"
#     )
#     
#     # 列出所有任务
#     jobs = cron.list_jobs()
#     for job in jobs:
#         print(f"任务: {job.name}, 下次执行: {job.state.next_run_at_ms}")
#     
#     # 手动执行任务
#     await cron.run_job(job1.id)
#     
#     # 禁用任务
#     cron.enable_job(job2.id, enabled=False)
#     
#     # 删除任务
#     cron.remove_job(job3.id)
#     
#     # 获取服务状态
#     status = cron.status()
#     print(f"服务状态: {status}")
#     
#     # 停止服务
#     cron.stop()
#
# # 运行示例
# asyncio.run(example())
# ```
#
# 2. 调度类型说明：
# | 类型 | 说明 | 示例 |
# |------|------|------|
# | at | 定点执行，只执行一次 | at_ms=1705312800000 |
# | every | 周期执行，间隔毫秒 | every_ms=3600000 (1小时) |
# | cron | Cron表达式 | expr="0 9 * * *" (每天9点) |
#
# 3. 定时器工作原理：
# ```
# 1. start() 启动服务：
#    - 加载任务存储
#    - 重新计算所有任务的下次执行时间
#    - 调用 _arm_timer() 设置定时器
# 
# 2. _arm_timer() 设置定时器：
#    - 找出最早执行的任务时间
#    - 计算延迟时间（next_wake - now）
#    - 创建异步任务，sleep后触发
# 
# 3. _on_timer() 定时器触发：
#    - 找出所有到期的任务
#    - 执行每个到期任务
#    - 保存状态
#    - 重新设置定时器
# 
# 4. 任务执行：
#    - 调用 on_job 回调
#    - 更新任务状态（成功/失败）
#    - 计算下次执行时间（周期任务）
#    - 处理一次性任务（禁用或删除）
# ```
#
# 4. 任务持久化存储：
# ```json
# {
#   "version": 1,
#   "jobs": [
#     {
#       "id": "abc123",
#       "name": "每日提醒",
#       "enabled": true,
#       "schedule": {
#         "kind": "cron",
#         "expr": "0 9 * * *",
#         "tz": "Asia/Shanghai"
#       },
#       "payload": {
#         "kind": "agent_turn",
#         "message": "生成日报",
#         "deliver": true,
#         "channel": "telegram",
#         "to": "user123"
#       },
#       "state": {
#         "nextRunAtMs": 1705312800000,
#         "lastRunAtMs": 1705226400000,
#         "lastStatus": "ok"
#       }
#     }
#   ]
# }
# ```
#
# 5. 使用场景：
# - **定时提醒**: 每日/每周提醒任务
# - **定期维护**: 数据备份、日志清理
# - **报告生成**: 定时生成和发送报告
# - **监控检查**: 周期性健康检查
# - **自动化工作流**: 复杂的定时业务流程
#
# 6. 最佳实践：
# - 使用有意义的任务名称
# - 设置合理的执行间隔，避免过于频繁
# - 处理任务执行错误，避免失败循环
# - 定期清理已完成的一次性任务
# - 监控任务执行状态和耗时
