
import asyncio
import time
import shutil
import sys
import logging
import json
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path.cwd()))

from nanobot.bus.queue import MessageBus
from nanobot.bus.events import OutboundMessage
from nanobot.cron.service import CronService
from nanobot.agent.loop import AgentLoop
from nanobot.config.loader import load_config, get_data_dir, save_config
from nanobot.providers.litellm_provider import LiteLLMProvider
from loguru import logger

# Setup logging
logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

async def run_timezone_verification():
    print("\n=== STARTING TIMEZONE PROMPT E2E VERIFICATION ===\n")
    
    # 1. Setup Environment
    # We need to LOAD config, REMOVE timezone, SAVE it, then run test.
    # Afterwards, RESTORE it.
    original_config = load_config()
    backup_tz = original_config.agents.defaults.timezone
    
    print(f"ℹ️ Original Timezone: {backup_tz}")
    
    # Temporarily clear timezone
    original_config.agents.defaults.timezone = None
    save_config(original_config)
    print("✅ Cleared timezone from config for test duration.")

    # Temporarily clear MEMORY.md
    workspace_dir = Path(original_config.workspace_path)
    memory_file = workspace_dir / "memory" / "MEMORY.md"
    backup_memory = None
    
    if memory_file.exists():
        backup_memory = memory_file.read_text(encoding="utf-8")
        memory_file.write_text("# Long-term Memory\n\n(Clean slate for test)\n", encoding="utf-8")
        print("✅ Cleared MEMORY.md for test duration.")

    try:
        # Reload to ensure we have the fresh state
        config = load_config()
        bus = MessageBus()
        
        # Use real provider from config
        provider = None
        if config.providers.openrouter and config.providers.openrouter.api_key:
            print(f"✅ Using Real LLM: {config.agents.defaults.model}")
            provider = LiteLLMProvider(
                api_key=config.providers.openrouter.api_key,
                api_base="https://openrouter.ai/api/v1",
                provider_name="openrouter",
                default_model=config.agents.defaults.model
            )
        else:
            print("❌ No API Key found! Cannot run realistic test.")
            return

        # Clean Cron Store (optional, but good for hygiene)
        store_path = get_data_dir() / "cron" / "jobs.json"
        if store_path.exists():
            store_path.unlink()
            print("✅ Cleared old jobs.json")
        
        # Initialize Services
        cron_service = CronService(store_path)
        agent = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=config.workspace_path,
            cron_service=cron_service,
            max_history_messages=10
        )
        
        # --- DEBUG: PRINT SYSTEM PROMPT ---
        print("\n🔎 DEBUG: INSPECTING SYSTEM PROMPT...")
        # Access the context builder directly to see what the agent sees
        from nanobot.agent.context import ContextBuilder
        cb = ContextBuilder(config.workspace_path)
        sys_prompt = cb.build_system_prompt()
        print("-" * 40)
        print(sys_prompt)
        print("-" * 40)
        # ----------------------------------
        
        print("✅ Services Started. Sending User Request...")
        
        # 2. Send User Request (Absolute Time, No TZ)
        user_prompt = "Remind me to call Mom at 17:00."
        
        # Use a random session ID to ensure no history leakage
        session_id = f"cli:test_tz_{int(time.time())}"
        
        print(f"\n🗣️ USER: {user_prompt}\n")
        
        response = await agent.process_direct(user_prompt, session_key=session_id)
        print(f"\n🤖 AGENT RESPONSE:\n{response}\n")
        
        # 3. Verify Response and CONTINUE
        # We expect the agent to ask about the timezone or location.
        keywords = ["timezone", "time zone", "location", "where are you", "city"]
        passed = any(k in response.lower() for k in keywords)
        
        if not passed:
            print("\n❌❌❌ TEST FAILED: Agent did not ask for timezone! ❌❌❌")
            print("Expected one of:", keywords)
            return

        print("\n✅ Agent correctly asked for timezone. Continuing conversation...\n")
        
        # 4. Provide Timezone
        user_reply = "I am in Europe/Moscow"
        print(f"🗣️ USER: {user_reply}\n")
        
        response_2 = await agent.process_direct(user_reply, session_key=session_id)
        print(f"\n🤖 AGENT RESPONSE 2:\n{response_2}\n")
        
        # 5. Verify Job Creation
        print("🔍 Verifying Cron Job Creation...")
        jobs = await cron_service.list_jobs()
        
        mom_jobs = [j for j in jobs if "mom" in j.name.lower() or "mom" in j.payload.message.lower()]
        
        if not mom_jobs:
            print("❌ TEST FAILED: No job created after providing timezone!")
            # Debug: what happened?
            print(f"Total jobs in system: {len(jobs)}")
        else:
            job = mom_jobs[0]
            print(f"✅ Job Created: {job.name} (ID: {job.id})")
            print(f"   Schedule: {job.schedule}")
            print(f"   Timezone: {job.schedule.tz}")
            
            if job.schedule.tz == "Europe/Moscow":
                print("\n✅✅✅ FULL E2E TEST PASSED: Timezone correctly applied! ✅✅✅")
            else:
                print(f"\n❌ TEST FAILED: Job created but timezone is wrong! Got: {job.schedule.tz}")

    finally:
        # Restore Config
        config = load_config()
        config.agents.defaults.timezone = backup_tz
        save_config(config)
        print(f"\n✅ Restored timezone to: {backup_tz}")
        
        # Restore MEMORY.md
        if backup_memory and memory_file.exists():
            memory_file.write_text(backup_memory, encoding="utf-8")
            print("✅ Restored MEMORY.md")

if __name__ == "__main__":
    asyncio.run(run_timezone_verification())
