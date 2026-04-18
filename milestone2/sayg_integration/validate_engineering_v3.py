"""
SAYG-Mem 工程验证脚本 v3
功能：通过BFF API启动3个真实Agent容器，让它们执行任务，然后进行CWW总结

架构：
- BFF运行在 localhost:8000
- BFF通过Docker Socket动态创建Agent容器
- 3个Agent并发执行任务，结果写入各自的堆段
- Consolidator异步合并，产出版本2
"""

import asyncio
import sys
import os
import time
import json
import httpx
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "bff"))
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 70)
print("SAYG-Mem 工程验证 v3")
print("=" * 70)

BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")
WAIT_TIMEOUT = 300.0

TASK_PROMPT = """你是一个技术专家。请用50字以内回答以下问题：

问题：Rust vs Go，选择哪种语言开发微服务更好？

请直接给出简洁的回答。"""

SUMMARY_PROMPT = """请对以下3个Agent的技术观点进行智能总结，生成一个统一的技术对比结论（100字以内）：

{agent_responses}

要求：
1. 去除重复内容
2. 保持客观中立
3. 用简洁的bullet points格式输出

总结："""

async def wait_for_bff(max_retries=30):
    print("\n[Step 0] 等待BFF服务就绪...")
    for i in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/")
                if resp.status_code in [200, 307, 308]:
                    print("  BFF服务就绪 ✓")
                    return True
        except Exception as e:
            if i % 5 == 0 and i > 0:
                print(f"  等待中... ({i}/{max_retries})")
            time.sleep(1)
    print("  BFF服务未就绪 ✗")
    return False

async def create_conversation(title: str, model: str = "deepseek-chat") -> dict:
    """创建对话，返回conversation_id和container_port"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/conversations",
                json={"title": title, "model": model}
            )
            if resp.status_code == 200:
                result = resp.json()
                conv_id = result.get("conversation_id")
                port = result.get("container_port")
                print(f"  创建对话成功: {conv_id[:8]}... (port={port})")
                return {"conversation_id": conv_id, "port": port, "success": True}
            else:
                print(f"  创建失败: {resp.status_code}")
                return {"success": False, "error": resp.text}
    except Exception as e:
        print(f"  创建异常: {e}")
        return {"success": False, "error": str(e)}

async def chat_with_agent(conversation_id: str, content: str, model: str = "deepseek-chat") -> dict:
    """向Agent发送消息并获取响应"""
    try:
        async with httpx.AsyncClient(timeout=WAIT_TIMEOUT) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/chat/{conversation_id}",
                json={"content": content, "model": model}
            )
            if resp.status_code == 200:
                result = resp.json()
                return {
                    "success": True,
                    "content": result.get("content", ""),
                    "conversation_id": conversation_id
                }
            else:
                return {"success": False, "error": resp.text, "conversation_id": conversation_id}
    except Exception as e:
        return {"success": False, "error": str(e), "conversation_id": conversation_id}

async def delete_conversation(conversation_id: str):
    """删除对话"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.delete(f"{BFF_BASE_URL}/conversations/{conversation_id}")
            print(f"  已删除: {conversation_id[:8]}...")
    except Exception as e:
        print(f"  删除异常: {conversation_id[:8]}... - {e}")

async def main():
    print("\n" + "=" * 70)
    print("开始 SAYG-Mem 工程验证 v3")
    print("=" * 70)

    if not await wait_for_bff():
        print("\n错误: BFF服务未就绪，请先启动BFF")
        print("提示: 在milestone2目录运行: docker-compose up bff")
        return

    agent_results = []
    start_time = time.time()

    try:
        print("\n" + "=" * 70)
        print("【Step 1】创建3个Agent容器（对应3个对话）")
        print("=" * 70)

        creation_tasks = [
            create_conversation("sayg_agent_a", "deepseek-chat"),
            create_conversation("sayg_agent_b", "deepseek-chat"),
            create_conversation("sayg_agent_c", "deepseek-chat"),
        ]

        creation_results = await asyncio.gather(*creation_tasks)
        valid_agents = [r for r in creation_results if r.get("success")]

        if len(valid_agents) < 3:
            print(f"\n警告: 只成功创建了 {len(valid_agents)}/3 个Agent")

        print(f"\n成功创建 {len(valid_agents)} 个Agent容器")

        print("\n" + "=" * 70)
        print("【Step 2】并发向3个Agent发送任务")
        print("=" * 70)

        chat_tasks = [
            chat_with_agent(agent["conversation_id"], TASK_PROMPT)
            for agent in valid_agents
        ]

        print(f"  发送任务: Rust vs Go 技术选型")
        print(f"  等待响应 (timeout={WAIT_TIMEOUT}s)...\n")

        chat_results = await asyncio.gather(*chat_tasks)

        for i, result in enumerate(chat_results):
            if result.get("success"):
                content = result.get("content", "")
                print(f"  Agent_{i+1} 响应: {content[:80]}...")
                agent_results.append({
                    "agent_id": f"Agent_{i+1}",
                    "conversation_id": result["conversation_id"],
                    "response": content
                })
            else:
                print(f"  Agent_{i+1} 失败: {result.get('error', 'unknown')}")

        print("\n" + "=" * 70)
        print("【Step 3】CWW总结 - 产出版本2")
        print("=" * 70)

        if agent_results:
            responses_text = "\n".join([
                f"- {r['agent_id']}: {r['response']}"
                for r in agent_results
            ])
            summary_prompt = SUMMARY_PROMPT.format(agent_responses=responses_text)

            print("  发送总结任务...")
            summary_result = await chat_with_agent(
                valid_agents[0]["conversation_id"],
                summary_prompt
            )

            version2_content = summary_result.get("content", "[总结失败]") if summary_result.get("success") else "[总结失败]"
            print(f"\n  版本2 (CWW总结): {version2_content[:100]}...")
        else:
            version2_content = "[无Agent响应，无法总结]"

        elapsed = time.time() - start_time

        print("\n" + "=" * 70)
        print("【结果汇总】")
        print("=" * 70)

        print("\n版本1内容（各Agent原始响应）：")
        for r in agent_results:
            print(f"  [{r['agent_id']}] {r['response'][:100]}...")

        print(f"\n版本2内容（CWW总结）：")
        print(f"  {version2_content[:200]}...")

        print(f"\n性能指标：")
        print(f"  - Agent数量: {len(valid_agents)}")
        print(f"  - 总耗时: {elapsed:.2f}s")
        print(f"  - 平均每Agent: {elapsed/len(valid_agents):.2f}s" if valid_agents else "  - N/A")

        print("\n" + "=" * 70)
        print("【生成日志文件】")
        print("=" * 70)

        log_content = f"""# SAYG-Mem 工程验证日志 v3

## 测试信息
- 测试时间: {datetime.now().isoformat()}
- BFF地址: {BFF_BASE_URL}
- 总耗时: {elapsed:.2f}s

## 测试配置
- 测试类型: 3 Agent并发执行 + CWW总结
- Agent模型: deepseek-chat
- 任务: Rust vs Go 技术选型讨论

## 版本1内容（各Agent原始响应）

"""

        for r in agent_results:
            log_content += f"### {r['agent_id']}\n"
            log_content += f"Conversation ID: `{r['conversation_id']}`\n\n"
            log_content += f"**响应内容:**\n{r['response']}\n\n---\n\n"

        log_content += f"""## 版本2内容（CWW总结）

**总结内容:**
{version2_content}

---

## 验证结论

✅ 测试完成时间: {datetime.now().isoformat()}
✅ 成功创建Agent数量: {len(valid_agents)}/3
✅ CWW总结任务: {'成功' if version2_content and '[' not in version2_content else '失败'}

## 性能数据

| 指标 | 值 |
|------|-----|
| Agent数量 | {len(valid_agents)} |
| 总耗时 | {elapsed:.2f}s |
| 平均每Agent | {elapsed/len(valid_agents):.2f}s |
"""

        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_filename = f"sayg_validation_v3_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        log_path = log_dir / log_filename
        log_path.write_text(log_content, encoding='utf-8')
        print(f"  日志已保存: {log_path}")

        print("\n" + "=" * 70)
        print("验证完成！")
        print("=" * 70)

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n[Cleanup] 清理对话...")
        cleanup_tasks = [
            delete_conversation(agent["conversation_id"])
            for agent in valid_agents if agent.get("conversation_id")
        ]
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)

if __name__ == "__main__":
    asyncio.run(main())
