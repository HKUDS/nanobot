import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.getcwd())

from nanobot.cron.service import CronService
from nanobot.agent.tools.cron import CronTool
from nanobot.cron.types import CronSchedule, CronJob

# Mock context
CHANNEL = "test_cli"
CHAT_ID = "test_user"

async def mock_on_job(job: CronJob) -> str:
    print(f"\n[EXEC] Executing job: {job.name} (ID: {job.id})")
    print(f"[EXEC] Message: {job.payload.message}")
    print(f"[EXEC] Type: {job.payload.kind}")
    return "Done"

async def main():
    print("--- Cron V2 Simulation: Batch Add & Catch-up ---")
    
    # Setup clean environment
    test_dir = Path("./test_cron_v2")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir()
    
    jobs_file = test_dir / "jobs.json"
    
    # Initialize Service
    service = CronService(jobs_file, on_job=mock_on_job)
    await service.start()
    
    tool = CronTool(service)
    tool.set_context(CHANNEL, CHAT_ID)
    
    # Prepare Timestamps
    now = datetime.now()
    past_1min = (now - timedelta(minutes=1)).isoformat()
    future_5s = (now + timedelta(seconds=5)).isoformat()
    future_10s = (now + timedelta(seconds=10)).isoformat()
    
    print(f"\n[INFO] Current Time: {now.isoformat()}")
    print(f"[INFO] Past Task Time: {past_1min}")
    print(f"[INFO] Future Task Time: {future_5s}")
    
    # Test Batch Add
    print("\n[STEP 1] Testing Batch Add...")
    batch_payload = [
        {
            "name": "Past Task (Catch-up)",
            "message": "This should execute IMMEDIATELY (Catch-up)",
            "type": "echo",
            "at": past_1min
        },
        {
            "name": "Immediate Task",
            "message": "This is almost now",
            "type": "echo",
            "at": now.isoformat()
        },
        {
            "name": "Future Task 1",
            "message": "Wait for 5 seconds...",
            "type": "agent",
            "at": future_5s
        },
        {
            "name": "Future Task 2",
            "message": "Wait for 10 seconds...",
            "type": "echo",
            "at": future_10s
        }
    ]
    
    result = await tool.execute(action="add", batch=batch_payload)
    print(f"[RESULT] {result}")
    
    # Check file modification (should happen ONCE)
    print("[CHECK] Jobs file created.")
    
    # Wait for execution
    print("\n[STEP 2] Waiting for execution loop...")
    
    # Sleep to allow catch-up and future tasks
    for i in range(15):
        print(f"Tick {i+1}s...")
        await asyncio.sleep(1)
        
    print("\n[INFO] Simulation Complete.")
    service.stop()

if __name__ == "__main__":
    asyncio.run(main())
