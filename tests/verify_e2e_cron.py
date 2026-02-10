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
    print("⏳ Waiting 90 seconds for tasks to fire...")
    for i in range(90):
        sys.stdout.write(f".")
        sys.stdout.flush()
        await asyncio.sleep(1)
    print("\n")

    # 4. Verify Results
    print("\n=== VERIFICATION REPORT ===")
    
    # Filter messages to exclude initial response (simplistic check)
    task_messages = [m[1] for m in MESSAGES if "напоминания" not in m[1]]
    
    echo_water = [m for m in task_messages if "попить воды" in m.lower()]
    agent_weather = [m for m in task_messages if "лондон" in m.lower() or "london" in m.lower()]
    echo_mom = [m for m in task_messages if "маме" in m.lower()]
    
    # Reporting
    print(f"Total Messages Captured: {len(task_messages)}")
    
    if len(echo_water) == 1:
        print(f"✅ Water Reminder: RECEIVED ONCE (Correct)")
    else:
        print(f"❌ Water Reminder: Expected 1, got {len(echo_water)}")

    if len(echo_mom) == 1:
        print(f"✅ Mom Reminder: RECEIVED ONCE (Correct)")
    else:
        print(f"❌ Mom Reminder: Expected 1, got {len(echo_mom)}")

    # Weather: we asked for 2 separate weather tasks (10s and 15s)
    # They might produce identical output, so we check count
    if len(agent_weather) == 2:
        print(f"✅ Weather Tasks: RECEIVED 2 TIMES (Correct)")
    elif len(agent_weather) > 2:
        print(f"❌ Weather Tasks: SPAM DETECTED (Got {len(agent_weather)})")
    else:
        print(f"⚠️ Weather Tasks: Incomplete (Got {len(agent_weather)}) - maybe timeout?")

    # Final Verdict
    if len(echo_water) == 1 and len(echo_mom) == 1 and len(agent_weather) == 2:
        print("\n✅✅✅ TEST PASSED: ALL TASKS FIRED EXACTLY ONCE ✅✅✅")
    else:
        print("\n❌❌❌ TEST FAILED: INCORRECT MESSAGE COUNTS ❌❌❌")

    # Cleanup
    cron_service.stop()
    capture_task.cancel()
    if store_path.exists() and Path(str(store_path) + ".bak").exists():
        shutil.move(str(store_path) + ".bak", store_path)

if __name__ == "__main__":
    asyncio.run(run_e2e_verification())
