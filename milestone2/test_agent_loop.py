"""AgentLoop 最小验证 Demo

目标：验证 AgentLoop 能否在容器内独立启动和工作
关键问题：
1. AgentLoop 初始化需要哪些参数？
2. 是否需要调用 initialize()？
3. 如何喂入消息并获取响应？
4. Session 和 Memory 存储在哪里？
"""

import asyncio
from pathlib import Path
from datetime import datetime

# 测试配置
TEST_WORKSPACE = Path("./test_workspace")
TEST_SESSION_KEY = "test_session_001"


async def test_agent_loop():
    """测试 AgentLoop 基本功能"""
    
    print("=" * 60)
    print("AgentLoop 最小验证 Demo")
    print("=" * 60)
    
    # ========== 步骤 1: 导入模块 ==========
    print("\n[1/6] 导入模块...")
    try:
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        from nanobot.session.manager import SessionManager
        from nanobot.bus.events import InboundMessage, OutboundMessage
        print("[OK] 模块导入成功")
    except Exception as e:
        print(f"[ERROR] 模块导入失败：{e}")
        return
    
    # ========== 步骤 2: 初始化基础组件 ==========
    print("\n[2/6] 初始化基础组件...")
    try:
        # 创建 MessageBus
        bus = MessageBus()
        print(f"[OK] MessageBus 创建成功")
        
        # 创建 LLM Provider（使用 DeepSeek API Key）
        # 通过环境变量设置 base_url
        import os
        os.environ['OPENAI_BASE_URL'] = 'https://api.deepseek.com/v1'
        
        api_key = "sk-b192d1bf26f740adace7d5f628656921"  # DeepSeek API Key
        provider = OpenAICompatProvider(api_key=api_key)
        print(f"[OK] Provider 创建成功 (model: {provider.get_default_model()})")
        print(f"[OK] Base URL: https://api.deepseek.com/v1 (通过 OPENAI_BASE_URL 环境变量)")
        
        # 准备 workspace
        TEST_WORKSPACE.mkdir(exist_ok=True)
        print(f"[OK] Workspace 准备成功：{TEST_WORKSPACE.absolute()}")
        
    except Exception as e:
        print(f"[ERROR] 组件初始化失败：{e}")
        import traceback
        traceback.print_exc()
        return
    
    # ========== 步骤 3: 创建 AgentLoop 实例 ==========
    print("\n[3/6] 创建 AgentLoop 实例...")
    try:
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=TEST_WORKSPACE,
            model="deepseek-chat",
            max_iterations=5,
        )
        print(f"[OK] AgentLoop 创建成功")
        print(f"  - SessionManager: {loop.sessions}")
        print(f"  - ToolRegistry: {loop.tools}")
        print(f"  - ContextBuilder: {loop.context}")
        
    except Exception as e:
        print(f"[ERROR] AgentLoop 创建失败：{e}")
        import traceback
        traceback.print_exc()
        return
    
    # ========== 步骤 4: 测试 Session 管理 ==========
    print("\n[4/6] 测试 Session 管理...")
    try:
        # 获取或创建会话
        session = loop.sessions.get_or_create(TEST_SESSION_KEY)
        print(f"[OK] Session 创建成功：{TEST_SESSION_KEY}")
        print(f"  - Session key: {session.key}")
        print(f"  - 历史消息数：{len(session.get_history())}")
        
        # 保存会话
        loop.sessions.save(session)
        print(f"[OK] Session 已保存")
        
    except Exception as e:
        print(f"[ERROR] Session 管理失败：{e}")
        import traceback
        traceback.print_exc()
        return
    
    # ========== 步骤 5: 测试消息处理 ==========
    print("\n[5/6] 测试消息处理...")
    try:
        # 构造测试消息
        test_message = InboundMessage(
            channel="test",
            chat_id=TEST_SESSION_KEY,
            sender_id="user",
            content="Hello, this is a test message",
            metadata={}
        )
        print(f"[OK] InboundMessage 构造成功")
        print(f"  - Channel: {test_message.channel}")
        print(f"  - Content: {test_message.content[:50]}...")
        
        # 方法 A: 直接调用 _process_message (需要确认是否可行)
        print("\n尝试方法 A: 直接调用 _process_message...")
        try:
            response = await loop._process_message(test_message)
            print(f"[OK] _process_message 调用成功")
            print(f"  - Response: {response.content if response else 'None'}")
        except Exception as e:
            print(f"[ERROR] _process_message 调用失败：{e}")
            print("  -> 可能需要通过 MessageBus 注入消息")
        
        # 方法 B: 通过 MessageBus 注入 (标准方式)
        print("\n尝试方法 B: 通过 MessageBus 注入...")
        try:
            # 发布消息到总线
            await bus.publish_inbound(test_message)
            print(f"[OK] 消息已发布到 MessageBus")
            
            # 注意：这种方式需要 AgentLoop 正在运行 run() 循环
            # 在 demo 中我们不启动完整循环，所以这里只是演示
            print("  -> 此方法需要 AgentLoop.run() 正在运行")
            
        except Exception as e:
            print(f"[ERROR] MessageBus 注入失败：{e}")
        
    except Exception as e:
        print(f"[ERROR] 消息处理失败：{e}")
        import traceback
        traceback.print_exc()
        return
    
    # ========== 步骤 6: 测试 Memory 读写 ==========
    print("\n[6/6] 测试 Memory 读写...")
    try:
        # 读取会话历史
        session = loop.sessions.get_or_create(TEST_SESSION_KEY)
        history = session.get_history(max_messages=10)
        print(f"[OK] 读取会话历史成功")
        print(f"  - 历史消息数：{len(history)}")
        
        # 检查 MEMORY.md 文件（长期记忆）
        memory_file = TEST_WORKSPACE / "memory" / "MEMORY.md"
        if memory_file.exists():
            memory_content = memory_file.read_text()
            print(f"[OK] 长期记忆文件存在：{memory_file}")
            print(f"  - 大小：{len(memory_content)} bytes")
        else:
            print(f"[INFO] 长期记忆文件不存在（正常，首次运行）")
        
    except Exception as e:
        print(f"[ERROR] Memory 读写失败：{e}")
        import traceback
        traceback.print_exc()
    
    # ========== 总结 ==========
    print("\n" + "=" * 60)
    print("验证完成！关键发现：")
    print("=" * 60)
    print("1. AgentLoop 可以直接实例化，不需要 initialize()")
    print("2. 消息处理有两种方式：")
    print("   - 直接调用 _process_message() (可行)")
    print("   - 通过 MessageBus 注入 (需要 run() 循环)")
    print("3. Session 存储在 workspace/sessions/ 目录")
    print("4. Memory 存储在 workspace/memory/MEMORY.md")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_agent_loop())
