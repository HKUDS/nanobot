
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

# logger.remove()
import sys
logger.remove()
logger.add(sys.stderr, level="INFO")

async def run_test():
    print("🚀 Starting REAL Agent Capability Verification Test...")
    print("🤖 Model: google/gemini-3-pro-preview")

    # 1. Setup paths
    base_dir = Path("tests/temp_cap_test")
    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir(parents=True)
    
    workspace = base_dir / "workspace"
    workspace.mkdir()
    
    # Create required memory dir
    (workspace / "memory").mkdir()
    (workspace / "AGENTS.md").write_text("# Instructions\nYou are a helpful agent.")
    
    cron_dir = base_dir / "data" / "cron"
    cron_dir.mkdir(parents=True)
    cron_store_path = cron_dir / "jobs.json"
    
    # 2. Load Config & Provider
    try:
        config = load_config() 
        print(f"📂 Loaded config from: {config.agents.defaults.workspace}")
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        return

    # Setup Provider
    p_config = config.providers.openrouter or config.get_provider()
    if not p_config or not p_config.api_key:
        print("❌ No API Key found in config. Cannot run real agent test.")
        return

    print(f"🔑 Using API Key: {p_config.api_key[:5]}...")

    provider = LiteLLMProvider(
        api_key=p_config.api_key,
        provider_name="openrouter", 
        default_model="google/gemini-3-pro-preview",
        extra_headers=p_config.extra_headers,
    )
    
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
    
    # 5. Run Test Case: Create File (Shopping List)
    prompt = """
    Запиши список покупок в файл shopping_list.md:
    1. Яблоки
    2. Хлеб
    3. Сыр
    """
    print(f"\n🧪 Test: File Creation (Memory/Tool Usage)")
    print(f"👤 User: {prompt}")
    
    # Pass 1: Agent creates file
    response = await agent.process_direct(prompt)
    print(f"🤖 Agent: {response}")
    
    # Verify File
    file_path = workspace / "shopping_list.md"
    cwd_file_path = Path("shopping_list.md").resolve()
    
    found_path = None
    if file_path.exists():
        found_path = file_path
    elif cwd_file_path.exists():
        found_path = cwd_file_path
        
    if found_path:
        content = found_path.read_text(encoding='utf-8')
        print(f"📄 File Content (at {found_path}):\n{content}")
        if "Яблоки" in content and "Хлеб" in content:
            print("✅ SUCCESS: File created with correct content.")
        else:
            print("❌ FAILED: File content mismatch.")
        
        # Cleanup if created in CWD
        if found_path == cwd_file_path:
            cwd_file_path.unlink()
    else:
        print(f"❌ FAILED: File not created at {file_path} or {cwd_file_path}")

    # Cleanup
    shutil.rmtree(base_dir)

if __name__ == "__main__":
    asyncio.run(run_test())
