#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试多 LLM Backend 并发调用

验证单进程多会话架构下，不同会话可以使用不同的 LLM Backend
"""

import asyncio
import time
from pathlib import Path
from nanobot.providers.openai_compat_provider import (
    set_current_session_config,
    get_current_session_config,
    OpenAICompatProvider,
)
from nanobot.providers import set_current_session_key


async def test_single_session(session_name: str, api_type: str, prompt: str) -> dict:
    """测试单个会话的 API 调用"""
    print(f"\n{'='*60}")
    print(f"测试会话：{session_name}")
    print(f"API 类型：{api_type}")
    print(f"提示词：{prompt[:50]}...")
    print(f"{'='*60}")
    
    # 设置会话配置
    session_config = {
        "session_key": session_name,
        "api_type": api_type,
        "model": None,  # 使用默认模型
    }
    
    set_current_session_config(session_config)
    
    try:
        # 创建 provider 实例
        provider = OpenAICompatProvider()
        
        # 构建消息
        messages = [
            {"role": "system", "content": "你是一个有帮助的助手。请用简洁的语言回答。"},
            {"role": "user", "content": prompt}
        ]
        
        # 调用 API
        start_time = time.time()
        response = await provider.chat(
            messages=messages,
            max_tokens=200,
            temperature=0.7,
        )
        end_time = time.time()
        
        result = {
            "session": session_name,
            "api_type": api_type,
            "success": True,
            "content": response.content[:100] if response.content else None,
            "total_tokens": response.usage.get("total_tokens", 0) if response.usage else 0,
            "execution_time": end_time - start_time,
        }
        
        print(f"✓ 成功！Token: {result['total_tokens']}, 时间：{result['execution_time']:.2f}s")
        print(f"  回复：{result['content']}")
        
        return result
        
    except Exception as e:
        print(f"✗ 失败：{e}")
        return {
            "session": session_name,
            "api_type": api_type,
            "success": False,
            "error": str(e),
        }
    finally:
        # 清除会话配置
        set_current_session_config(None)


async def test_concurrent_sessions():
    """并发测试多个会话"""
    print("\n" + "="*80)
    print("多 LLM Backend 并发测试")
    print("="*80)
    
    # 定义测试会话
    sessions = [
        ("test_deepseek_1", "deepseek", "中国的首都是哪里？"),
        ("test_qwen_1", "qwen", "上海的天气怎么样？"),
        ("test_kimi_1", "kimi", "推荐一本好书。"),
        # 可以添加更多测试
    ]
    
    # 并发执行所有测试
    tasks = [
        test_single_session(name, api_type, prompt)
        for name, api_type, prompt in sessions
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 统计结果
    print("\n" + "="*80)
    print("测试结果汇总")
    print("="*80)
    
    success_count = 0
    total_tokens = 0
    total_time = 0
    
    for result in results:
        if isinstance(result, Exception):
            print(f"✗ 异常：{result}")
            continue
        
        if result.get("success"):
            success_count += 1
            total_tokens += result.get("total_tokens", 0)
            total_time += result.get("execution_time", 0)
            print(f"✓ {result['session']} ({result['api_type']}): "
                  f"Token={result['total_tokens']}, "
                  f"时间={result['execution_time']:.2f}s")
        else:
            print(f"✗ {result['session']} ({result['api_type']}): {result.get('error', 'Unknown error')}")
    
    print("\n" + "-"*80)
    print(f"总计：{success_count}/{len(sessions)} 成功")
    print(f"总 Token: {total_tokens}")
    print(f"总时间：{total_time:.2f}s")
    print(f"平均时间：{total_time/len(sessions):.2f}s")
    print("="*80)
    
    return success_count == len(sessions)


async def main():
    """主函数"""
    print("开始测试多 LLM Backend 功能...")
    
    # 测试 1: 单个会话
    print("\n【测试 1】单个 DeepSeek 会话")
    result1 = await test_single_session(
        "single_test",
        "deepseek",
        "你好，请做个自我介绍。"
    )
    
    # 测试 2: 并发多个会话
    print("\n【测试 2】并发多个 LLM Backend")
    success = await test_concurrent_sessions()
    
    # 最终结果
    print("\n" + "="*80)
    if success:
        print("✓ 所有测试通过！多 LLM Backend 功能正常工作。")
    else:
        print("✗ 部分测试失败，请检查配置。")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
