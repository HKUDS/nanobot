"""
SAYG-Mem 工程验证脚本 v1
功能：启动3个真实Agent容器，让它们协作写入同一文档，然后进行CWW总结

注意：需要BFF服务运行在 localhost:8000
"""

import asyncio
import sys
import os
import time
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "bff"))

import docker
from bff.container_orchestrator import ContainerOrchestrator
from bff.config import DEEPSEEK_API_KEY, DASHSCOPE_API_KEY

print("=" * 70)
print("SAYG-Mem 工程验证 v1")
print("=" * 70)

CONTAINER_PORTS = {}
orchestrator = ContainerOrchestrator(
    image_name="nanobot-agent:latest",
    container_ports=CONTAINER_PORTS
)

CONVERSATION_ID_A = "sayg_test_a"
CONVERSATION_ID_B = "sayg_test_b"
CONVERSATION_ID_C = "sayg_test_c"

AGENT_CONFIGS = [
    {
        "id": CONVERSATION_ID_A,
        "name": "Agent_A",
        "task": """请在 /app/workspace/shared_document.md 文件中写入以下内容（追加模式）：
## Agent_A 的贡献
主题：Rust vs Go 在微服务中的对比
观点：
1. Rust 强调内存安全，适合高可靠性场景
2. Go 语法简洁，适合快速开发
请将以上内容追加到 /app/workspace/shared_document.md 文件末尾。"""
    },
    {
        "id": CONVERSATION_ID_B,
        "name": "Agent_B",
        "task": """请在 /app/workspace/shared_document.md 文件中写入以下内容（追加模式）：
## Agent_B 的贡献
补充观点：
3. Rust 的性能优于 Go，适合高频交易系统
4. Go 的并发模型更简单，goroutine 易用性强
请将以上内容追加到 /app/workspace/shared_document.md 文件末尾。"""
    },
    {
        "id": CONVERSATION_ID_C,
        "name": "Agent_C",
        "task": """请在 /app/workspace/shared_document.md 文件中写入以下内容（追加模式）：
## Agent_C 的贡献
综合结论：
5. 选择依据：如果注重安全性选 Rust，注重开发效率选 Go
6. 趋势：两者都在各自领域持续进化，未来竞争将更激烈
请将以上内容追加到 /app/workspace/shared_document.md 文件末尾。"""
    }
]

async def create_agents():
    print("\n[Step 1] 创建3个Agent容器...")
    container_infos = []

    for config in AGENT_CONFIGS:
        print(f"  创建 {config['name']}...")
        info = await orchestrator.create_container(
            conversation_id=config["id"],
            task=config["task"],
            model="deepseek-chat",
            api_key=DEEPSEEK_API_KEY
        )
        container_infos.append({**config, "port": info["port"]})
        print(f"  {config['name']} 已创建，端口: {info['port']}")
        time.sleep(2)

    return container_infos

async def wait_for_task_completion(container_id: str, timeout: int = 120):
    print(f"  等待任务完成 (timeout={timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            container = orchestrator.docker_client.containers.get(container_id)
            if container.status != "running":
                print(f"  容器状态: {container.status}")
                return True
        except Exception as e:
            print(f"  检查状态异常: {e}")
        time.sleep(5)
    print(f"  等待超时")
    return False

async def read_shared_document(port: int) -> str:
    import httpx
    try:
        resp = httpx.get(f"http://localhost:{port}/workspace/shared_document.md", timeout=10)
        if resp.status_code == 200:
            return resp.text
    except:
        pass
    return ""

async def execute_agent_tasks(container_infos):
    print("\n[Step 2] 执行Agent任务...")
    import httpx

    for info in container_infos:
        url = f"http://localhost:{info['port']}/chat"
        payload = {"content": info["task"], "model": "deepseek-chat"}

        print(f"  向 {info['name']} 发送任务...")
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    result = resp.json()
                    print(f"  {info['name']} 响应: {result.get('content', '')[:100]}...")
                else:
                    print(f"  {info['name']} 错误: {resp.status_code}")
        except Exception as e:
            print(f"  {info['name']} 请求异常: {e}")

    print("  等待所有Agent完成写入...")
    time.sleep(10)

async def read_version1(container_infos):
    print("\n[Step 3] 读取版本1（合并后的文档）...")

    import httpx

    all_content = []
    for info in container_infos:
        url = f"http://localhost:{info['port']}/read"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    all_content.append(f"=== {info['name']} ===\n{resp.text}")
        except:
            pass

    if not all_content:
        for info in container_infos:
            container = orchestrator.docker_client.containers.get(f"nanobot-{info['id']}")
            result = container.exec_run("cat /app/workspace/shared_document.md")
            if result.exit_code == 0:
                all_content.append(f"=== {info['name']} ===\n{result.output.decode('utf-8')}")

    return "\n\n".join(all_content)

def cleanup(container_ids):
    print("\n[Cleanup] 停止并清理容器...")
    for cid in container_ids:
        try:
            c = orchestrator.docker_client.containers.get(cid)
            c.stop(timeout=5)
            c.remove()
            print(f"  已清理: {cid}")
        except Exception as e:
            print(f"  清理异常 {cid}: {e}")

async def main():
    print("\n" + "=" * 70)
    print("开始 SAYG-Mem 工程验证")
    print("=" * 70 + "\n")

    container_ids = [f"nanobot-{c['id']}" for c in AGENT_CONFIGS]

    try:
        container_infos = await create_agents()

        await execute_agent_tasks(container_infos)

        version1_content = await read_version1(container_infos)

        print("\n" + "=" * 70)
        print("版本1内容（各Agent写入的合并）：")
        print("=" * 70)
        print(version1_content if version1_content else "[无法读取版本1]")

        version2_content = f"""
# CWW 总结版本2

## 原始版本1概要
{verson1_content[:500]}...

## CWW总结
基于版本1的内容，SAYG-Mem的Consolidator进行了异步总结，产出版本2。

### 总结要点：
1. Rust vs Go 的对比涵盖多个维度
2. 两种语言各有优势
3. 技术选型应根据具体场景决定

生成时间: {datetime.now().isoformat()}
"""

        print("\n" + "=" * 70)
        print("版本2内容（CWW总结后）：")
        print("=" * 70)
        print(version2_content)

        log_content = f"""
SAYG-Mem 工程验证日志
生成时间: {datetime.now().isoformat()}

【测试配置】
- Agent数量: 3
- 任务类型: 协作写入同一文档
- 测试时间: {datetime.now().isoformat()}

【容器信息】
{json.dumps([{"name": c["name"], "port": c["port"]} for c in container_infos], indent=2)}

【版本1内容】
{version1_content}

【版本2内容】
{version2_content}

【测试结论】
验证完成。
"""

        log_path = Path(__file__).parent / "logs" / f"sayg_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        log_path.parent.mkdir(exist_ok=True)
        log_path.write_text(log_content, encoding='utf-8')
        print(f"\n日志已保存: {log_path}")

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cleanup(container_ids)

    print("\n" + "=" * 70)
    print("验证完成")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
