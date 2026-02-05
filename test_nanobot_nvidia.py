import sys
import os
sys.path.insert(0, os.getcwd())

async def test():
    # 测试配置
    from nanobot.schema import Config
    config = Config()
    
    print("=== 配置 ===")
    print(f"模型: {config.agents.defaults.model}")
    print(f"OpenAI API Key: {config.providers.openai.api_key[:20]}..." if config.providers.openai.api_key else "未设置")
    print(f"OpenAI API Base: {config.providers.openai.api_base}")
    
    # 测试直接使用 openai 库
    print("\n=== 直接使用 openai 库测试 ===")
    from openai import OpenAI
    
    client = OpenAI(
        api_key=config.providers.openai.api_key,
        base_url=config.providers.openai.api_base
    )
    
    try:
        completion = client.chat.completions.create(
            model=config.agents.defaults.model,
            messages=[{"role": "user", "content": "Hello from nanobot test"}],
            temperature=0.7,
            max_tokens=100
        )
        print(f"✅ 成功!")
        print(f"响应: {completion.choices[0].message.content}")
    except Exception as e:
        print(f"❌ 失败: {e}")

import asyncio
asyncio.run(test())
