"""
nanobot AI 助手 - 使用新的 nanobot 框架
"""

import asyncio
from pathlib import Path

from nanobot.agent import AgentLoop
from nanobot.providers import LiteLLMProvider
from nanobot.bus import MessageBus


# ============================================================================
# 配置
# ============================================================================

CONFIG = {
    # 模型配置
    "api_key": "",
    "api_base": "",
    "model": "qwen-plus",  # qwen-turbo, qwen-plus, qwen-max
    
    # 工作空间（使用项目内的 workspace）
    "workspace": Path(__file__).parent / "workspace",
    
    # Agent 配置
    "max_iterations": 20,  # 最大工具调用轮数
}


# ============================================================================
# 初始化 Agent
# ============================================================================

def create_agent() -> AgentLoop:
    """创建 Agent 实例"""
    
    # 确保工作空间存在
    workspace = CONFIG["workspace"]
    workspace.mkdir(parents=True, exist_ok=True)
    
    # 创建 LLM Provider
    provider = LiteLLMProvider(
        api_key=CONFIG["api_key"],
        api_base=CONFIG["api_base"],
        default_model=CONFIG["model"],
    )
    
    # 创建消息总线（虽然直接调用不需要，但 AgentLoop 依赖它）
    bus = MessageBus()
    
    # 创建 Agent
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=CONFIG["model"],
        max_iterations=CONFIG["max_iterations"],
    )
    
    return agent


# ============================================================================
# 对话循环
# ============================================================================

async def chat_loop():
    """持续对话循环"""
    
    print("=" * 60)
    print("🤖 nanobot AI 助手 - 新框架版本")
    print("=" * 60)
    print(f"模型: {CONFIG['model']}")
    print(f"工作空间: {CONFIG['workspace']}")
    print("=" * 60)
    print("输入 'exit' 或 'quit' 退出")
    print("输入 'clear' 清空会话")
    print("=" * 60)
    print()
    
    # 创建 Agent
    agent = create_agent()
    session_key = "cli:user123"
    
    while True:
        # 获取用户输入
        try:
            user_input = input("👤 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 再见！")
            break
        
        if not user_input:
            continue
        
        # 命令处理
        if user_input.lower() in ["exit", "quit"]:
            print("\n👋 再见！")
            break
        
        if user_input.lower() == "clear":
            # 重新创建 Agent 来清空会话
            agent = create_agent()
            print("✅ 会话已清空\n")
            continue
        
        try:
            # 调用 Agent
            print("🤖 助手: ", end="", flush=True)
            
            response = await agent.process_direct(user_input, session_key)
            print(response)
            print()
            
        except Exception as e:
            print(f"\n❌ 错误: {e}\n")
            import traceback
            traceback.print_exc()
            continue


async def single_chat(message: str):
    """单次对话"""
    agent = create_agent()
    response = await agent.process_direct(message, "cli:single")
    return response


# ============================================================================
# 入口
# ============================================================================

if __name__ == "__main__":
    # 持续对话模式
    asyncio.run(chat_loop())
    
    # 单次对话示例：
    # response = asyncio.run(single_chat("你好，请介绍一下你自己"))
    # print(response)
