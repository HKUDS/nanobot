import asyncio
import os
import shutil
import json
import time
from pathlib import Path
from functools import partial

from nanobot.agent.loop import AgentLoop
from nanobot.config.loader import load_config
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.cron.service import CronService
from nanobot.bus.queue import MessageBus
from nanobot.bus.events import OutboundMessage

# 1. Mock Bus to capture outputs
class MockBus(MessageBus):
    def __init__(self):
        super().__init__()
        self.captured_messages = []

    async def publish_outbound(self, message: OutboundMessage):
        print(f"📨 [BUS] Outbound: {message.content[:100]}...")
        self.captured_messages.append(message)
        # We don't need to actually queue it for this test, just capture it

# 2. Execution Callback (matches cli/commands.py logic)
async def execute_cron_job(job, bus, agent) -> str | None:
    """Execute a cron job through the agent."""
    from nanobot.bus.events import OutboundMessage
    from loguru import logger

    print(f"⚙️ Executing Job: {job.name} ({job.payload.kind})")

    # Echo mode: just send message
    if job.payload.kind == "echo":
        if job.payload.to:
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                content=job.payload.message
            ))
        return job.payload.message

    # Agent turn mode
    response = await agent.process_direct(
        job.payload.message,
        session_key=f"cron:{job.id}",
        channel=job.payload.channel or "cli",
        chat_id=job.payload.to or "direct",
    )
    
    if job.payload.deliver and job.payload.to:
        if response and response.strip():
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                content=response
            ))
    return response

async def test_real_batch_agent():
    print("\n🧪 STARTING REAL END-TO-END CRON VERIFICATION TEST")
    print("==================================================")
    
    # Setup
    test_dir = Path("tests/temp_real_batch_test")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)
    
    # Config
    user_config_path = Path(os.path.expanduser("~/.nanobot/config.json"))
    print(f"📂 Loading config from {user_config_path}")
    config = load_config(user_config_path)
    
    model_id = "google/gemini-3-pro-preview"
    print(f"🤖 Using Model: {model_id}")
    
    # Initialize Components
    bus = MockBus()
    
    cron_service = CronService(store_path=test_dir / "jobs.json")
    
    provider = LiteLLMProvider(
        default_model=model_id,
        api_key=config.get_api_key(model_id),
        api_base=config.get_api_base(model_id),
        provider_name=config.get_provider_name(model_id)
    )
    
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=test_dir,
        cron_service=cron_service
    )
    
    # Wire callback
    cron_service.on_job = partial(execute_cron_job, bus=bus, agent=agent)
    
    await cron_service.start()
    
    # --- TEST SCENARIO ---
    user_prompt = (
        "Set these reminders:\n"
        "1. In 5 seconds: 'Drink water' (text)\n"
        "2. In 8 seconds: 'Check the weather in Tokyo' (find info)\n"
        "3. In 12 seconds: 'Stand up' (text)\n"
        "4. Every Monday at 9am: 'Call Mom'"
    )
    
    print(f"\n👤 User Prompt: {user_prompt}")
    print("⏳ Agent is scheduling...")
    
    response = await agent.process_direct(user_prompt)
    print(f"🤖 Agent Response: {response}")
    
    # --- VERIFICATION 1: JOBS CREATED ---
    jobs_file = test_dir / "jobs.json"
    if not jobs_file.exists():
        print("❌ FAILED: jobs.json not created")
        return

    with open(jobs_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        jobs = data.get("jobs", [])
    
    print(f"\n📂 Jobs created: {len(jobs)}")
    
    # Check Cron Translation (Monday at 9am)
    monday_jobs = [j for j in jobs if "mom" in j['name'].lower() or "mom" in j['payload']['message'].lower()]
    if not monday_jobs:
         print("❌ FAILED: 'Call Mom' job not found")
    else:
        mom_job = monday_jobs[0]
        expr = mom_job['schedule'].get('expr')
        # Expect "0 9 * * 1" or similar
        print(f"   - 'Call Mom' schedule: {expr}")
        if expr == "0 9 * * 1":
             print("   ✅ Natural Language Cron Translation: SUCCESS")
        else:
             print(f"   ⚠️ Natural Language Cron Translation: Got '{expr}', expected '0 9 * * 1'")

    # --- VERIFICATION 2: EXECUTION ---
    print("\n⏳ Waiting 45 seconds for execution...")
    # Sleep in chunks to show progress
    for i in range(45):
        await asyncio.sleep(1)
        print(".", end="", flush=True)
    print("\n")
    
    messages = bus.captured_messages
    print(f"📨 Total Messages Delivered: {len(messages)}")
    
    # Analyze Messages
    content_str = "\n".join([m.content.lower() for m in messages])
    
    success = True
    
    if "water" in content_str:
        print("✅ 'Drink water' (Echo) -> DELIVERED")
    else:
        print("❌ 'Drink water' (Echo) -> NOT DELIVERED")
        success = False

    if "tokyo" in content_str or "weather" in content_str or "degrees" in content_str:
        print("✅ 'Tokyo Weather' (Agent) -> DELIVERED")
    else:
        print("❌ 'Tokyo Weather' (Agent) -> NOT DELIVERED")
        success = False

    if "stand" in content_str:
        print("✅ 'Stand up' (Echo) -> DELIVERED")
    else:
        print("❌ 'Stand up' (Echo) -> NOT DELIVERED")
        success = False
        
    if success:
        print("\n🏆 END-TO-END TEST PASSED: Planning -> Scheduling -> Execution -> Delivery verified!")
    else:
        print("\n💥 TEST FAILED: Some messages were not delivered.")

    # Cleanup
    cron_service.stop()
    if test_dir.exists():
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    asyncio.run(test_real_batch_agent())
