"""
A组轻量级测试脚本 - 用于快速验证CWW合并功能
仅3个Agent，每Agent 2轮，用于测试Consolidator是否正常工作
"""
import asyncio
import httpx
import os
import sys
import time
from datetime import datetime

BFF_BASE_URL = "http://localhost:8000"

AGENT_ROLES = [
    {"name": "技术架构师", "prompt": "你是一名技术架构师，擅长系统设计和架构优化。"},
    {"name": "产品经理", "prompt": "你是一名产品经理，擅长需求分析和产品规划。"},
    {"name": "安全专家", "prompt": "你是一名安全专家，擅长安全评估和风险分析。"},
]

SKILL_0_CONTENT = "技能0：SAYG-Mem多智能体协作学习系统 - 用于测试目的"

async def wait_for_bff(timeout: float = 300.0):
    """等待BFF服务启动"""
    print(f"[等待BFF] 等待BFF服务启动... (timeout={timeout}s)")
    start = time.time()
    while time.time() - start < timeout:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/health")
                if resp.status_code == 200:
                    print("[等待BFF] BFF服务已就绪")
                    return True
        except:
            pass
        await asyncio.sleep(2)
    print("[等待BFF] BFF服务启动超时")
    return False

async def wait_for_km(timeout: float = 30.0):
    """等待KM容器启动"""
    print(f"[等待KM] 等待KM容器启动... (timeout={timeout}s)")
    start = time.time()
    while time.time() - start < timeout:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/stats")
                if resp.status_code == 200:
                    print("[等待KM] KM容器已就绪")
                    return True
        except:
            pass
        await asyncio.sleep(2)
    print("[等待KM] KM容器启动超时")
    return False

async def create_collab_container(name: str) -> dict:
    """创建协作者容器"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{BFF_BASE_URL}/conversations",
            json={
                "title": name,
                "model": "deepseek-chat",
                "agent_type": "collab"
            }
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "conversation_id": data["conversation_id"],
            "container_port": data.get("container_port")
        }

async def call_bff_km_preset_skill(content: str):
    """预置0号Skill"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{BFF_BASE_URL}/knowledge-manager/preset-skill-0",
            json={"content": content}
        )
        resp.raise_for_status()

async def call_agent_chat(conv_id: str, port: int, role: dict, round_num: int) -> dict:
    """调用Agent进行一轮对话"""
    prompt = f"""{role['prompt']}

请回答以下问题（仅回答内容，不需要额外说明）：
问题：在分布式系统中，如何设计一个高效的任务分发机制？
请用50字左右描述你的核心观点。"""

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"http://localhost:{port}/chat",
            json={"content": prompt, "model": "deepseek-chat"}
        )
        resp.raise_for_status()
        result = resp.json()
        return result.get("content", "")

async def write_heap_segment(conv_id: str, port: int, content: str, content_type: str = "heap") -> dict:
    """写入堆段"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"http://localhost:{port}/heap/append",
            json={"content": content, "type": content_type}
        )
        resp.raise_for_status()
        return resp.json()

async def single_agent_learning(conv_id: str, port: int, role: dict, rounds: int = 2):
    """单个Agent的学习任务"""
    agent_name = role["name"]
    results = {
        "agent_id": conv_id,
        "role": agent_name,
        "rounds": [],
        "start_time": time.perf_counter()
    }

    for round_idx in range(1, rounds + 1):
        try:
            round_start = time.perf_counter()
            content = await call_agent_chat(conv_id, port, role, round_idx)

            await write_heap_segment(conv_id, port, content, "heap")

            round_elapsed = time.perf_counter() - round_start
            results["rounds"].append({
                "round": round_idx,
                "content_length": len(content),
                "time": round_elapsed
            })
            print(f"  [{agent_name}] 第{round_idx}轮完成: {round_elapsed:.2f}s")
        except Exception as e:
            print(f"  [{agent_name}] 第{round_idx}轮失败: {e}")
            results["rounds"].append({"round": round_idx, "error": str(e)})

    results["total_time"] = time.perf_counter() - results["start_time"]
    return results

async def check_consolidator_health() -> bool:
    """检查Consolidator容器健康状态"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/consolidator/health")
            return resp.status_code == 200
    except:
        return False

async def trigger_consolidator_merge() -> dict:
    """触发合并"""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{BFF_BASE_URL}/consolidator/merge")
        resp.raise_for_status()
        return resp.json()

async def get_heap_all_unmerged() -> dict:
    """获取所有未合并堆段"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{BFF_BASE_URL}/heap/all-unmerged")
        resp.raise_for_status()
        return resp.json()

async def get_km_public_memory() -> dict:
    """获取PublicMemory条目数"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/public-memory")
        resp.raise_for_status()
        return resp.json()

async def main():
    print("=" * 70)
    print("A组轻量级测试 - 验证CWW合并功能")
    print("=" * 70)

    await wait_for_bff()
    await wait_for_km()

    print("\n[Step 1] 预置0号Skill")
    await call_bff_km_preset_skill(SKILL_0_CONTENT)
    print("[Step 1] ✅ 0号Skill预置完成")

    print("\n[Step 2] 检查Consolidator容器状态...")
    if await check_consolidator_health():
        print("[Step 2] ✅ Consolidator容器就绪")
    else:
        print("[Step 2] ⚠️ Consolidator容器未就绪，将自动创建")

    print("\n[Step 3] 创建3个协作者Agent")
    print("=" * 70)
    agents = []
    for i in range(3):
        info = await create_collab_container(f"lite_test_{i+1}")
        info["role"] = AGENT_ROLES[i]
        print(f"  {info['conversation_id'][:8]} -> {AGENT_ROLES[i]['name']}")
        agents.append(info)
        await asyncio.sleep(0.5)

    print("\n[Step 4] 启动3个Agent并发学习（每Agent 2轮）")
    print("=" * 70)
    start_time = time.perf_counter()
    tasks = [
        single_agent_learning(info["conversation_id"], info["container_port"], info["role"], rounds=2)
        for info in agents
    ]
    results = await asyncio.gather(*tasks)
    total_time = time.perf_counter() - start_time

    print(f"\n[Step 4] 所有Agent完成，推理总耗时: {total_time:.2f}s")

    print("\n[Step 5] 触发Consolidator合并...")
    print("=" * 70)
    try:
        merge_result = await trigger_consolidator_merge()
        print(f"[合并] 完成: {merge_result}")
    except Exception as e:
        print(f"[合并] 失败: {e}")

    await asyncio.sleep(2)

    print("\n[Step 6] 检查合并结果")
    print("=" * 70)
    heap_status = await get_heap_all_unmerged()
    print(f"未合并堆段数: {heap_status.get('total_count', 0)}")

    pm_status = await get_km_public_memory()
    pm_entries = pm_status.get("entries", [])
    print(f"PublicMemory条目数: {len(pm_entries)}")

    print("\n[Step 7] 测试结果汇总")
    print("=" * 70)
    print(f"Agent数量: {len(agents)}")
    print(f"总推理耗时: {total_time:.2f}s")
    print(f"PublicMemory条目数: {len(pm_entries)}")
    print(f"未合并堆段数: {heap_status.get('total_count', 0)}")

    if len(pm_entries) > 1:
        print("\n✅ CWW合并功能正常工作！")
    else:
        print("\n❌ CWW合并功能可能有问题，请检查日志")

    return {
        "total_time": total_time,
        "pm_count": len(pm_entries),
        "unmerged_count": heap_status.get("total_count", 0)
    }

if __name__ == "__main__":
    asyncio.run(main())
