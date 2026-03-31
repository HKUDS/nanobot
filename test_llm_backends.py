#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版多 LLM Backend 测试
"""

import asyncio
import time
from nanobot.providers import set_current_session_config, get_current_session_config
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


async def test_api(session_name: str, api_type: str, prompt: str):
    """测试单个 API"""
    print(f"\n测试：{session_name} ({api_type})")
    
    # 设置会话配置
    session_config = {
        "session_key": session_name,
        "api_type": api_type,
    }
    set_current_session_config(session_config)
    
    try:
        provider = OpenAICompatProvider()
        messages = [
            {"role": "system", "content": "用一句话回答。"},
            {"role": "user", "content": prompt}
        ]
        
        start = time.time()
        response = await provider.chat(messages=messages, max_tokens=8000)  # 增加到 8000 tokens
        elapsed = time.time() - start
        
        tokens = response.usage.get("total_tokens", 0) if response.usage else 0
        
        print(f"  ✓ 成功 | Token: {tokens} | 时间：{elapsed:.2f}s")
        print(f"  回复：{response.content[:80]}")
        
        return {"success": True, "tokens": tokens, "time": elapsed}
        
    except Exception as e:
        print(f"  ✗ 失败：{e}")
        return {"success": False, "error": str(e)}
    finally:
        set_current_session_config(None)


async def main():
    print("="*70)
    print("多 LLM Backend 并发测试")
    print("="*70)
    
    # 测试 3 个不同的 LLM
    tasks = [
        test_api("deepseek_test", "deepseek", "中国的首都是哪里？"),
        test_api("qwen_test", "qwen", "上海有多少人？"),
        test_api("kimi_test", "kimi", "推荐一部电影。"),
    ]
    
    results = await asyncio.gather(*tasks)
    
    print("\n" + "="*70)
    success = sum(1 for r in results if r.get("success"))
    print(f"结果：{success}/3 成功")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
