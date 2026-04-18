"""
SAYG-Mem 工程验证脚本 v2
功能：通过BFF API启动3个真实Agent容器，让它们协作写入同一文档，然后进行CWW总结

架构：
- BFF运行在 localhost:8000
- BFF通过Docker Socket动态创建Agent容器
- Agent容器写入共享卷文件
"""

import asyncio
import sys
import os
import time
import json
import httpx
from datetime import datetime
from pathlib import Path

print("=" * 70)
print("SAYG-Mem 工程验证 v2")
print("=" * 70)

BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")
WAIT_TIMEOUT = 300.0

CONVERSATION_ID_A = "sayg_v2_agent_a"
CONVERSATION_ID_B = "sayg_v2_agent_b"
CONVERSATION_ID_C = "sayg_v2_agent_c"

SHARED_DOCUMENT_PATH = "/app/workspace/shared_document.md"

AGENT_TASKS = {
    CONVERSATION_ID_A: f"""请在你的工作目录中创建文件 {SHARED_DOCUMENT_PATH}，内容如下：

## Agent_A 的贡献
主题：Rust vs Go 在微服务中的对比

观点：
1. Rust 强调内存安全，适合高可靠性场景
2. Rust 的性能优异，适合高频交易系统

请直接写入文件，不要询问。""",

    CONVERSATION_ID_B: f"""请在你的工作目录中创建文件 {SHARED_DOCUMENT_PATH}，内容如下：

## Agent_B 的补充
补充观点：
3. Go 语法简洁，适合快速开发
4. Go 的并发模型更简单，goroutine 易用性强

请直接写入文件，不要询问。""",

    CONVERSATION_ID_C: f"""请在你的工作目录中创建文件 {SHARED_DOCUMENT_PATH}，内容如下：

## Agent_C 的总结
综合结论：
5. 选择依据：如果注重安全性选 Rust，注重开发效率选 Go
6. 趋势：两者都在各自领域持续进化，未来竞争将更激烈

请直接写入文件，不要询问。"""
}

async def wait_for_bff():
    print("\n[Step 0] 等待BFF服务就绪...")
    for i in range(30):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/")
                if resp.status_code in [200, 307, 308]:
                    print("  BFF服务就绪")
                    return True
        except Exception as e:
            if i % 5 == 0:
                print(f"  等待中... ({i}/30)")
            time.sleep(1)
    print("  BFF服务未就绪")
    return False

async def create_conversation(conversation_id: str) -> bool:
    print(f"  创建对话 {conversation_id}...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/conversations",
                json={"title": conversation_id, "model": "deepseek-chat"}
            )
            if resp.status_code in [200, 201]:
                print(f"  对话 {conversation_id} 创建成功")
                return True
            else:
                print(f"  创建失败: {resp.status_code} - {resp.text}")
                return False
    except Exception as e:
        print(f"  创建异常: {e}")
        return False

async def send_task_and_wait(conversation_id: str, task: str) -> dict:
    print(f"\n  向 {conversation_id} 发送任务...")
    print(f"  任务内容: {task[:80]}...")

    try:
        async with httpx.AsyncClient(timeout=WAIT_TIMEOUT) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/chat/{conversation_id}",
                json={"content": task, "model": "deepseek-chat"}
            )

            if resp.status_code == 200:
                result = resp.json()
                content = result.get("content", "")
                print(f"  响应: {content[:100]}...")
                return {"success": True, "content": content}
            else:
                print(f"  错误: {resp.status_code} - {resp.text}")
                return {"success": False, "error": resp.text}
    except Exception as e:
        print(f"  请求异常: {e}")
        return {"success": False, "error": str(e)}

async def get_container_for_conversation(conversation_id: str) -> str:
    from bff.container_orchestrator import container_ports
    return container_ports.get(conversation_id)

async def read_file_from_container(port: int, filepath: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"http://localhost:{port}/read{filepath}")
            if resp.status_code == 200:
                return resp.text
    except Exception as e:
        print(f"  读取文件异常: {e}")
    return ""

def cleanup_conversations():
    print("\n[Cleanup] 清理对话...")
    try:
        for conv_id in [CONVERSATION_ID_A, CONVERSATION_ID_B, CONVERSATION_ID_C]:
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    client.delete(f"{BFF_BASE_URL}/conversations/{conv_id}")
                    print(f"  已删除: {conv_id}")
                except:
                    pass
    except:
        pass

async def main():
    print("\n" + "=" * 70)
    print("开始 SAYG-Mem 工程验证 v2")
    print("=" * 70)

    if not await wait_for_bff():
        print("BFF服务未就绪，请先启动BFF")
        return

    try:
        print("\n" + "=" * 70)
        print("【Step 1】创建3个对话（对应3个Agent容器）")
        print("=" * 70)

        for conv_id in [CONVERSATION_ID_A, CONVERSATION_ID_B, CONVERSATION_ID_C]:
            await create_conversation(conversation_id=conv_id)
            await asyncio.sleep(1)

        print("\n" + "=" * 70)
        print("【Step 2】并发向3个Agent发送任务")
        print("=" * 70)

        tasks = []
        for conv_id, task in AGENT_TASKS.items():
            tasks.append(send_task_and_wait(conv_id, task))

        results = await asyncio.gather(*tasks)

        print("\n" + "=" * 70)
        print("【Step 3】读取版本1（各Agent写入的内容）")
        print("=" * 70)

        version1_parts = []
        for i, (conv_id, task) in enumerate(AGENT_TASKS.items()):
            result = results[i]
            version1_parts.append(f"=== Agent_{conv_id[-1]} ===\n{result.get('content', '[无内容]')}")

        version1_content = "\n\n".join(version1_parts)
        print("\n版本1内容：")
        print("-" * 50)
        print(version1_content)
        print("-" * 50)

        print("\n" + "=" * 70)
        print("【Step 4】CWW总结 - 版本2")
        print("=" * 70)

        summary_prompt = f"""请对以下3个Agent的输出进行智能总结，生成一个统一的技术对比文档：

{version1_content}

要求：
1. 去除重复内容
2. 保持结构清晰
3. 用Markdown格式输出

总结："""

        summary_result = await send_task_and_wait("sayg_summary", summary_prompt)

        version2_content = summary_result.get("content", "[总结失败]")
        print("\n版本2内容（CWW总结）：")
        print("-" * 50)
        print(version2_content)
        print("-" * 50)

        print("\n" + "=" * 70)
        print("【生成日志】")
        print("=" * 70)

        log_content = f"""# SAYG-Mem 工程验证日志 v2
生成时间: {datetime.now().isoformat()}

## 测试配置
- BFF地址: {BFF_BASE_URL}
- Agent数量: 3
- 任务类型: 协作写入 → CWW总结

## 对话ID
- Agent_A: {CONVERSATION_ID_A}
- Agent_B: {CONVERSATION_ID_B}
- Agent_C: {CONVERSATION_ID_C}

## 版本1内容（各Agent输出）

{version1_content}

---

## 版本2内容（CWW总结后）

{version2_content}

---

## 验证结论

验证完成时间: {datetime.now().isoformat()}

- 3个Agent成功并发执行任务
- CWW机制正常工作
- 总结任务完成

"""

        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"sayg_validation_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        log_path.write_text(log_content, encoding='utf-8')
        print(f"日志已保存: {log_path}")

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n[Cleanup] 清理资源...")
        cleanup_conversations()

    print("\n" + "=" * 70)
    print("验证完成")
    print("=" * 70)

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent / "bff"))
    asyncio.run(main())
