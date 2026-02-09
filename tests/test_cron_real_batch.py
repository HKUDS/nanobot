import asyncio
import os
import shutil
import json
from pathlib import Path
from nanobot.agent.loop import AgentLoop
from nanobot.config.loader import load_config
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.agent.tools.cron import CronTool
from nanobot.cron.service import CronService
from nanobot.bus import MessageBus

# Mock output channel to verify execution
class MockOutput:
    def __init__(self):
        self.messages = []

    async def send(self, message):
        print(f"MockOutput received: {message}")
        self.messages.append(message)

async def test_real_batch_agent():
    print("\n🧪 STARTING REAL BATCH AGENT VERIFICATION TEST")
    print("===============================================")
    
    # 1. Setup Environment
    test_dir = Path("tests/temp_real_batch_test")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)
    
    # Load REAL user config to get keys
    user_config_path = Path(os.path.expanduser("~/.nanobot/config.json"))
    if not user_config_path.exists():
        print("❌ SKIPPING: No ~/.nanobot/config.json found")
        return

    print(f"📂 Loading config from {user_config_path}")
    config = load_config(user_config_path)
    
    # Force the specific model requested by user
    model_id = "google/gemini-3-pro-preview"
    print(f"🤖 Using Model: {model_id}")
    
    # 2. Initialize Components
    bus = MessageBus()
    
    # Initialize CronService with test directory
    cron_service = CronService(store_path=test_dir / "jobs.json")
    await cron_service.start()
    
    # Initialize Provider
    provider = LiteLLMProvider(
        default_model=model_id,
        api_key=config.get_api_key(model_id),
        api_base=config.get_api_base(model_id),
        provider_name=config.get_provider_name(model_id)
    )
    
    # Initialize Agent
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=test_dir,
        cron_service=cron_service
    )
    
    # 3. Run Test Scenario
    # Mixed intent: Echo (simple) + Agent (complex) + Echo (simple)
    user_prompt = (
        "Set these reminders:\n"
        "1. In 5 seconds: 'Drink water' (just text)\n"
        "2. In 10 seconds: 'Check the weather in Tokyo' (find info)\n"
        "3. In 15 seconds: 'Stand up' (just text)"
    )
    
    print(f"\n👤 User Prompt: {user_prompt}")
    print("⏳ Agent is thinking...")
    
    response = await agent.process_direct(user_prompt)
    print(f"🤖 Agent Response: {response}")
    
    # 4. Verify Results in jobs.json
    jobs_file = test_dir / "jobs.json"
    if not jobs_file.exists():
        print("❌ FAILED: jobs.json not created")
        return

    with open(jobs_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        jobs = data.get("jobs", [])
    
    print(f"\n📂 Jobs created: {len(jobs)}")
    
    # Analyze Job Types
    echo_jobs = [j for j in jobs if j['payload']['kind'] == 'echo']
    agent_jobs = [j for j in jobs if j['payload']['kind'] == 'agent']
    
    print(f"   - Echo Jobs: {len(echo_jobs)}")
    print(f"   - Agent Jobs: {len(agent_jobs)}")
    
    # Assertions
    success = True
    
    # Check counts
    if len(jobs) != 3:
        print(f"❌ FAILED: Expected 3 jobs, got {len(jobs)}")
        success = False
    
    if len(echo_jobs) != 2:
        print(f"❌ FAILED: Expected 2 echo jobs, got {len(echo_jobs)}")
        success = False
    else:
        # Verify content of echo jobs
        payloads = [j['payload']['message'].lower() for j in echo_jobs]
        if not any("water" in p for p in payloads):
            print("❌ FAILED: 'Drink water' job missing or malformed")
            success = False
        if not any("stand" in p for p in payloads):
            print("❌ FAILED: 'Stand up' job missing or malformed")
            success = False
            
    if len(agent_jobs) != 1:
        print(f"❌ FAILED: Expected 1 agent job, got {len(agent_jobs)}")
        success = False
    else:
        # Verify content of agent job
        payload = agent_jobs[0]['payload']['message'].lower()
        if "tokyo" not in payload and "weather" not in payload:
            print("❌ FAILED: Weather job payload looks wrong")
            success = False

    if success:
        print("\n✅ TEST PASSED: Agent correctly distinguished Mixed Echo/Agent tasks!")
    else:
        print("\n❌ TEST FAILED: See errors above.")

    # Cleanup
    cron_service.stop()
    if test_dir.exists():
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    asyncio.run(test_real_batch_agent())
