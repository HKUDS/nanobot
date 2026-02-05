"""
nanobot AI  (test)
"""

import asyncio
from pathlib import Path

from nanobot.agent import AgentLoop
from nanobot.providers import LiteLLMProvider
from nanobot.bus import MessageBus


# ============================================================================
# configuration
# ============================================================================

CONFIG = {
    # model configuration
    "api_key": "",
    "api_base": "",
    "model": "qwen-plus",  # qwen-turbo, qwen-plus, qwen-max
    
    # workspace (using project's workspace)
    "workspace": Path(__file__).parent / "workspace",
    
    # Agent configuration
    "max_iterations": 20,  # 最大工具调用轮数
}


# ============================================================================
# Initialize Agent
# ============================================================================

def create_agent() -> AgentLoop:
    """Create Agent instance"""
    
    # ensure workspace exists
    workspace = CONFIG["workspace"]
    workspace.mkdir(parents=True, exist_ok=True)
    
    # create LLM Provider
    provider = LiteLLMProvider(
        api_key=CONFIG["api_key"],
        api_base=CONFIG["api_base"],
        default_model=CONFIG["model"],
    )
    
    # create message bus (although not needed for direct calling, AgentLoop depends on it)
    bus = MessageBus()
    
    # create Agent
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=CONFIG["model"],
        max_iterations=CONFIG["max_iterations"],
    )
    
    return agent


# ============================================================================
# Conversation loop
# ============================================================================

async def chat_loop():
    """Continuous conversation loop"""
    
    print("=" * 60)
    print("🤖 nanobot AI - new framework version")
    print("=" * 60)
    print(f"model: {CONFIG['model']}")
    print(f"workspace: {CONFIG['workspace']}")
    print("=" * 60)
    print("input 'exit' or 'quit' to exit")
    print("input 'clear' to clear conversation")
    print("=" * 60)
    print()
    
    # create Agent
    agent = create_agent()
    session_key = "cli:user123"
    
    while True:
        # get user input
        try:
            user_input = input("👤 you: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 bye!")
            break
        
        if not user_input:
            continue
        
        # 命令处理
        if user_input.lower() in ["exit", "quit"]:
            print("\n👋 bye!")
            break
        
        if user_input.lower() == "clear":
            # recreate Agent to clear conversation
            agent = create_agent()
            print("✅ conversation cleared\n")
            continue
        
        try:
            # call Agent
            print("🤖 assistant: ", end="", flush=True)
            
            response = await agent.process_direct(user_input, session_key)
            print(response)
            print()
            
        except Exception as e:
            print(f"\n❌ error: {e}\n")
            import traceback
            traceback.print_exc()
            continue


async def single_chat(message: str):
    """Single conversation"""
    agent = create_agent()
    response = await agent.process_direct(message, "cli:single")
    return response


# ============================================================================
# Entry
# ============================================================================

if __name__ == "__main__":
    # continuous conversation mode
    asyncio.run(chat_loop())
    
    # single conversation example:
    # response = asyncio.run(single_chat("Hello, please introduce yourself"))
    # print(response)
