
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
    print("🚀 Starting REAL Agent Verification Test...")
    print("🤖 Model: google/gemini-3-pro-preview")

    # 1. Setup paths
    base_dir = Path("tests/temp_real_test")
    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir(parents=True)
    
    workspace = base_dir / "workspace"
    workspace.mkdir()
    
    cron_dir = base_dir / "data" / "cron"
    cron_dir.mkdir(parents=True)
    cron_store_path = cron_dir / "jobs.json"
    
    # 2. Load Config & Provider
    # Load from default user location (~/.nanobot/config.json)
    try:
        config = load_config() 
        print(f"📂 Loaded config from: {config.agents.defaults.workspace}")
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        return

    # Setup Provider with REAL KEY
    # We use the key from 'openrouter' provider in config, as per user context
    p_config = config.providers.openrouter
    if not p_config or not p_config.api_key:
        # Fallback to finding ANY key
        p_config = config.get_provider()
        
    if not p_config or not p_config.api_key:
        print("❌ No API Key found in config. Cannot run real agent test.")
        return

    print(f"🔑 Using API Key: {p_config.api_key[:5]}...")

    provider = LiteLLMProvider(
        api_key=p_config.api_key,
        provider_name="openrouter", 
        default_model="google/gemini-3-pro-preview", # EXACTLY AS REQUESTED
        extra_headers=p_config.extra_headers,
    )
    
    # Override model if needed, but LiteLLMProvider takes default_model.
    # The AgentLoop also takes a model.
    TEST_MODEL = "google/gemini-3-pro-preview" 

    # 3. Setup Infrastructure
    bus = MessageBus()
    cron_service = CronService(cron_store_path)
    
    # 4. Initialize Agent
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=TEST_MODEL,
        max_history_messages=10,
        max_history_tokens=10000,
        exec_config=config.tools.exec,
        cron_service=cron_service,
        restrict_to_workspace=False,
    )
    
    # 5. Run Test Case 1: ECHO
    prompt1 = "Remind me to drink water in 1 minute"
    print(f"\n🧪 Test 1: Simple Reminder (Expect ECHO)")
    print(f"👤 User: {prompt1}")
    
    response1 = await agent.process_direct(prompt1)
    print(f"🤖 Agent: {response1}")
    
    # Verify Job 1
    jobs = await cron_service.list_jobs()
    if not jobs:
        print("❌ FAILED: No jobs created.")
    else:
        job1 = jobs[-1]
        print(f"📋 Job: {job1.name} | Type: {job1.payload.kind}")
        if job1.payload.kind == 'echo':
            print("✅ SUCCESS: Correctly used 'echo' mode.")
        else:
            print(f"❌ FAILED: Used '{job1.payload.kind}' instead of 'echo'.")

    # 6. Run Test Case 2: AGENT
    prompt2 = "Check the weather in London every morning at 9am"
    print(f"\n🧪 Test 2: Complex Task (Expect AGENT)")
    print(f"👤 User: {prompt2}")
    
    response2 = await agent.process_direct(prompt2)
    print(f"🤖 Agent: {response2}")
    
    # Verify Job 2
    jobs = await cron_service.list_jobs()
    if len(jobs) < 2:
        print("❌ FAILED: Second job not created.")
    else:
        job2 = jobs[-1]
        print(f"📋 Job: {job2.name} | Type: {job2.payload.kind}")
        if job2.payload.kind == 'agent': # or 'agent_turn'
            print("✅ SUCCESS: Correctly used 'agent' mode.")
        else:
            print(f"❌ FAILED: Used '{job2.payload.kind}' instead of 'agent'.")

    # Cleanup
    shutil.rmtree(base_dir)

if __name__ == "__main__":
    asyncio.run(run_test())
