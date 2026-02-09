import asyncio
import json
import time
import uuid
from pathlib import Path
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronSchedule, CronPayload, CronJobState

# Global counter for executions
EXECUTION_COUNT = 0

async def mock_on_job(job: CronJob) -> str:
    global EXECUTION_COUNT
    print(f"Executing job {job.id} from process/instance...")
    # Simulate some work
    await asyncio.sleep(0.1)
    EXECUTION_COUNT += 1
    return "Executed"

async def run_race():
    global EXECUTION_COUNT
    store_path = Path("race_jobs.json")
    if store_path.exists():
        store_path.unlink()
    
    # 1. Setup initial job
    initial_data = {
        "jobs": [
            {
                "id": "job1",
                "name": "Race Job",
                "enabled": True,
                "schedule": {"kind": "at", "atMs": int(time.time() * 1000) - 1000}, # Due 1 sec ago
                "payload": {"kind": "echo", "message": "Race"},
                "state": {"nextRunAtMs": int(time.time() * 1000) - 1000},
                "createdAtMs": int(time.time() * 1000),
                "updatedAtMs": int(time.time() * 1000),
                "deleteAfterRun": False
            }
        ]
    }
    store_path.write_text(json.dumps(initial_data))
    
    # 2. Create two services pointing to same file
    s1 = CronService(store_path, on_job=mock_on_job)
    s2 = CronService(store_path, on_job=mock_on_job)
    
    # Load store for both
    s1._load_store()
    s2._load_store()
    
    print("Starting race...")
    
    # 3. Run both concurrently
    # We call _check_and_run_due_jobs directly to simulate the loop waking up
    await asyncio.gather(
        s1._check_and_run_due_jobs(),
        s2._check_and_run_due_jobs()
    )
    
    # Wait a bit for async execution to finish
    await asyncio.sleep(0.5)
    
    print(f"Total Executions: {EXECUTION_COUNT}")
    if EXECUTION_COUNT > 1:
        print("FAIL: Race condition detected! Job ran multiple times.")
    else:
        print("PASS: Job ran exactly once.")

    # Cleanup
    if store_path.exists():
        store_path.unlink()

if __name__ == "__main__":
    asyncio.run(run_race())
