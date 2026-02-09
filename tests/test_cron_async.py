import asyncio
import json
import time
from pathlib import Path
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule

async def test_async_cron():
    tmp_store = Path("tests/temp_jobs.json")
    if tmp_store.exists():
        tmp_store.unlink()
    
    # Create service
    service = CronService(tmp_store)
    
    # Track execution times
    start_times = {}
    
    async def mock_on_job(job):
        start_times[job.name] = time.time()
        print(f"Starting {job.name} at {start_times[job.name]}")
        if job.name == "slow_job":
            await asyncio.sleep(1.0)
        return f"Result for {job.name}"

    service.on_job = mock_on_job
    
    # Add jobs
    now_ms = int(time.time() * 1000)
    future_ms = now_ms + 200 # 200ms in future
    
    # Job 1: Slow
    await service.add_job(
        name="slow_job",
        schedule=CronSchedule(kind="at", at_ms=future_ms),
        message="slow"
    )
    
    # Job 2: Fast
    await service.add_job(
        name="fast_job",
        schedule=CronSchedule(kind="at", at_ms=future_ms),
        message="fast"
    )
    
    # Wait for time to pass
    await asyncio.sleep(0.5)

    # Run due jobs
    print("Running due jobs...")
    await service._check_and_run_due_jobs()
    
    # Wait for tasks to complete (since they are background tasks now)
    await asyncio.sleep(1.5)
    
    # Check results
    t_slow = start_times.get("slow_job", 0)
    t_fast = start_times.get("fast_job", 0)
    
    if t_slow == 0 or t_fast == 0:
        print("FAILURE: One or both jobs did not start")
        return

    print(f"Slow job started at: {t_slow}")
    print(f"Fast job started at: {t_fast}")
    
    diff = abs(t_fast - t_slow)
    print(f"Start time difference: {diff:.4f}s")
    
    # If async, difference should be very small (<< 0.1s)
    # If sync, difference would be >= 1.0s
    if diff < 0.2:
        print("SUCCESS: Jobs started concurrently")
    else:
        print("FAILURE: Jobs ran sequentially")

    # Clean up
    if tmp_store.exists():
        tmp_store.unlink()

if __name__ == "__main__":
    asyncio.run(test_async_cron())
