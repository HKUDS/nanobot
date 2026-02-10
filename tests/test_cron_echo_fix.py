
import asyncio
import shutil
import json
import os
from pathlib import Path
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.cron.service import CronService
from nanobot.config.loader import load_config
from nanobot.providers.litellm_provider import LiteLLMProvider
from loguru import logger

# Disable logger for cleaner output
logger.remove()

async def run_test():
    print("🚀 Starting Cron Echo Fix Verification Test...")

    # 1. Setup paths
    base_dir = Path("tests/temp_workspace")
    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir(parents=True)
    
    workspace = base_dir / "workspace"
    workspace.mkdir()
    
    cron_dir = base_dir / "data" / "cron"
    cron_dir.mkdir(parents=True)
    cron_store_path = cron_dir / "jobs.json"
    
    # 2. Load Config & Provider
    # We assume the user has a valid config in ~/.nanobot/config.json or we use the one we just wrote locally
    # We'll try to load from local directory first (where we fixed it)
    config = load_config(Path("config.json")) 
    
    # Setup Provider
    p_config = config.get_provider()
    if not p_config or not p_config.api_key:
        print("❌ No API Key found in config. Cannot run real agent test.")
        return

    provider = LiteLLMProvider(
        api_key=p_config.api_key,
        provider_name=config.get_provider_name(),
        default_model=config.agents.defaults.model,
        extra_headers=p_config.extra_headers,
    )
    
    # 3. Setup Infrastructure
    bus = MessageBus()
    cron_service = CronService(cron_store_path)
    
    # 4. Initialize Agent
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        max_history_messages=10,
        max_history_tokens=10000,
        exec_config=config.tools.exec,
        cron_service=cron_service, # <--- This is what we are testing!
        restrict_to_workspace=False, # Allow it to run commands if needed
    )
    
    # 5. Run Test
    prompt = "Напомни мне попить воды через 1 минуту"
    print(f"👤 User: {prompt}")
    
    response = await agent.process_direct(prompt)
    print(f"🤖 Agent: {response}")
    
    # 6. Verify Results
    if not cron_store_path.exists():
        print("❌ FAILED: jobs.json was not created.")
        return

    try:
        data = json.loads(cron_store_path.read_text(encoding='utf-8'))
        jobs = data.get("jobs", [])
        
        if not jobs:
            print("❌ FAILED: No jobs found in jobs.json")
            return
            
        # Get the latest job
        job = jobs[-1]
        print(f"📋 Created Job: {job['name']} (ID: {job['id']})")
        print(f"   Type: {job['payload']['kind']}")
        print(f"   Message: {job['payload']['message']}")
        
        if job['payload']['kind'] == 'echo':
            print("✅ SUCCESS: Job created with type='echo'")
        else:
            print(f"❌ FAILED: Job created with type='{job['payload']['kind']}' (Expected 'echo')")
            
    except Exception as e:
        print(f"❌ Error verifying jobs: {e}")

    # Cleanup
    # shutil.rmtree(base_dir)

if __name__ == "__main__":
    asyncio.run(run_test())
