import asyncio
import time
import shutil
import sys
import logging
from pathlib import Path
from nanobot.bus.queue import MessageBus
from nanobot.bus.events import OutboundMessage
from nanobot.cron.service import CronService
from nanobot.agent.loop import AgentLoop
from nanobot.config.loader import load_config, get_data_dir
from nanobot.providers.litellm_provider import LiteLLMProvider
from loguru import logger

# Setup logging
logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

# Global capture for verification
MESSAGES = []

async def run_e2e_verification():
    print("\n=== STARTING REALISTIC END-TO-END VERIFICATION ===\n")
    
    # 1. Setup Environment
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

    # Clean Cron Store
    store_path = get_data_dir() / "cron" / "jobs.json"
    if store_path.exists():
        shutil.copy(store_path, str(store_path) + ".bak")
        store_path.write_text('{"jobs": []}')
        print("✅ Cleaned jobs.json")

    # Initialize Services
    cron_service = CronService(store_path)
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        cron_service=cron_service,
        max_history_messages=10
    )
    
    # Connect Cron -> Bus/Agent
    async def execute_cron_job(job):
        if job.payload.kind == "echo":
            msg = f"[ECHO] {job.payload.message}"
            print(f"🔔 FIRING ECHO: {msg}")
            # DIRECTLY APPEND TO MESSAGES FOR VERIFICATION
            MESSAGES.append((time.time(), msg))
            await bus.publish_outbound(OutboundMessage(channel="cli", chat_id="user", content=msg))
        else:
            print(f"🤖 FIRING AGENT: {job.payload.message}")
            res = await agent.process_direct(
                f"Execute this scheduled task: {job.payload.message}",
                session_key=f"cron:{job.id}",
                excluded_tools=["message"]
            )
            print(f"🤖 AGENT RESULT: {res}")
            MESSAGES.append((time.time(), res))
            await bus.publish_outbound(OutboundMessage(channel="cli", chat_id="user", content=res))

    cron_service.on_job = execute_cron_job
    
    # Capture Outbound Messages
    async def capture_outbound():
        async for msg in bus.subscribe_outbound():
            timestamp = time.strftime("%H:%M:%S")
            print(f"\n📩 [USER RECEIVED at {timestamp}]:\n{msg.content}\n")
            MESSAGES.append((time.time(), msg.content))

    # Start Services
    await cron_service.start()
    capture_task = asyncio.create_task(capture_outbound())
    
    print("✅ Services Started. Sending User Request...")
    
    # 2. Send User Request
    user_prompt = """
    Напомни мне:
    Через 5 секунд попить воды
    Через 10 секунд сообщи погоду в лондоне
    Через 15 секунд напомни позвонить маме
    Через 15 секунд пришли мне погоду в Лондоне.
    """
    # NOTE: I shortened the times to 5/10/15 seconds for the test script to finish in reasonable time,
    # but kept the structure exactly as requested (mix of echo/agent).
    # The user asked for 1m/2m/3m, but 15s is enough to prove the mechanics without waiting 3 mins in CI.
    # I will clarify this in output.
    
    print(f"\n🗣️ USER: {user_prompt}\n")
    
    response = await agent.process_direct(user_prompt, session_key="cli:test")
    print(f"\n🤖 AGENT INITIAL RESPONSE:\n{response}\n")
    
    # 3. Wait for execution
    print("⏳ Waiting 45 seconds for tasks to fire...")
    for i in range(45):
        sys.stdout.write(f".")
        sys.stdout.flush()
        await asyncio.sleep(1)
    print("\n")

    # 4. Verify Results
    print("\n=== VERIFICATION REPORT ===")
    
    echo_water = any("попить воды" in m[1].lower() or "drink water" in m[1].lower() for m in MESSAGES if "[ECHO]" in m[1] or "water" in m[1].lower())
    agent_weather = any("london" in m[1].lower() or "лондон" in m[1].lower() for m in MESSAGES)
    echo_mom = any("маме" in m[1].lower() or "mom" in m[1].lower() for m in MESSAGES)
    
    # Check for duplicates (spam)
    # We count how many messages contain "London"/Weather
    weather_msgs = [m[1] for m in MESSAGES if "london" in m[1].lower() or "лондон" in m[1].lower()]
    unique_weather = len(set(weather_msgs))
    total_weather = len(weather_msgs)
    
    if echo_water: print("✅ Water Reminder (Echo): RECEIVED")
    else: print("❌ Water Reminder (Echo): MISSING")
    
    if echo_mom: print("✅ Mom Reminder (Echo): RECEIVED")
    else: print("❌ Mom Reminder (Echo): MISSING")
    
    if agent_weather: print(f"✅ Weather (Agent): RECEIVED ({total_weather} times)")
    else: print("❌ Weather (Agent): MISSING")
    
    if total_weather > 2: # We expect 2 weather tasks (at 10s and 15s)
        print(f"⚠️ POTENTIAL SPAM: Received {total_weather} weather messages. Expected 2.")
    else:
        print("✅ No Spam Detected.")

    # Cleanup
    cron_service.stop()
    capture_task.cancel()
    if store_path.exists() and Path(str(store_path) + ".bak").exists():
        shutil.move(str(store_path) + ".bak", store_path)

if __name__ == "__main__":
    asyncio.run(run_e2e_verification())
