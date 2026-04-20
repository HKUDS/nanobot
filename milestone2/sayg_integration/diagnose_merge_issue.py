"""
诊断合并机制失效问题

检查项目：
1. Consolidator 容器状态
2. 各 Agent 堆段未合并数量
3. KM 的合并阈值配置
4. PublicMemory 实际条目数
"""

import asyncio
import httpx
import subprocess
from datetime import datetime

BFF_BASE_URL = "http://localhost:8000"


async def check_consolidator_status():
    """检查 Consolidator 容器状态"""
    print("\n" + "="*60)
    print("[1] 检查 Consolidator 容器状态")
    print("="*60)
    
    try:
        # 检查 Docker 容器
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=consolidator", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout.strip():
            print(f"容器信息:\n{result.stdout}")
        else:
            print("❌ 未找到 Consolidator 容器")
            return False
        
        # 检查容器是否正在运行
        if "Up" not in result.stdout:
            print("❌ Consolidator 容器未运行")
            return False
        
        print("✅ Consolidator 容器正在运行")
        
        # 尝试访问 Consolidator
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/consolidator/health")
                if resp.status_code == 200:
                    print(f"✅ Consolidator 健康检查通过：{resp.json()}")
                else:
                    print(f"⚠️ Consolidator 健康检查失败：HTTP {resp.status_code}")
        except Exception as e:
            print(f"❌ 无法访问 Consolidator: {e}")
            return False
            
        return True
    except Exception as e:
        print(f"❌ 检查失败：{e}")
        return False


async def check_heap_segments():
    """检查各 Agent 的堆段状态"""
    print("\n" + "="*60)
    print("[2] 检查堆段状态")
    print("="*60)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 获取所有未合并堆段
            resp = await client.get(f"{BFF_BASE_URL}/heap/all-unmerged")
            resp.raise_for_status()
            data = resp.json()
            
            unmerged_entries = data.get("entries", [])
            total_count = data.get("total_count", 0)
            
            print(f"全局未合并堆段总数：{total_count} 条")
            
            # 按 Agent 统计
            agent_stats = {}
            for entry in unmerged_entries:
                agent_id = entry.get("source_agent_id", "unknown")[:8]
                if agent_id not in agent_stats:
                    agent_stats[agent_id] = 0
                agent_stats[agent_id] += 1
            
            print(f"\n各 Agent 未合并堆段数:")
            for agent_id, count in sorted(agent_stats.items()):
                print(f"  Agent_{agent_id}: {count} 条")
            
            # 检查 KM 阈值
            km_url_resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/km-url")
            km_url = km_url_resp.json().get("km_url")
            if km_url:
                stats_resp = await client.get(f"{km_url}/stats")
                if stats_resp.status_code == 200:
                    stats = stats_resp.json()
                    merge_threshold = stats.get("merge_threshold", "unknown")
                    merge_interval = stats.get("merge_interval", "unknown")
                    print(f"\nKM 配置:")
                    print(f"  合并阈值：{merge_threshold} 条")
                    print(f"  合并间隔：{merge_interval} 秒")
            
            return total_count
    except Exception as e:
        print(f"❌ 检查失败：{e}")
        return 0


async def check_public_memory():
    """检查 PublicMemory 状态"""
    print("\n" + "="*60)
    print("[3] 检查 PublicMemory")
    print("="*60)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/public-memory")
            resp.raise_for_status()
            entries = resp.json().get("entries", [])
            
            print(f"PublicMemory 条目数：{len(entries)}")
            
            if entries:
                print(f"\n最近 5 条记录:")
                for i, entry in enumerate(entries[-5:]):
                    page_id = entry.get("page_id", "unknown")
                    agent_id = entry.get("agent_id", "unknown")[:8]
                    created_at = entry.get("created_at", "unknown")
                    print(f"  {i+1}. {page_id} (Agent_{agent_id}) @ {created_at}")
            
            return len(entries)
    except Exception as e:
        print(f"❌ 检查失败：{e}")
        return 0


async def test_merge_endpoint():
    """测试合并端点是否可用"""
    print("\n" + "="*60)
    print("[4] 测试合并端点")
    print("="*60)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            print("发送测试合并请求...")
            resp = await client.post(f"{BFF_BASE_URL}/consolidator/merge")
            
            if resp.status_code == 200:
                result = resp.json()
                print(f"✅ 合并成功：{result}")
            else:
                print(f"⚠️ 合并返回异常：HTTP {resp.status_code}")
                print(f"响应内容：{resp.text[:200]}")
    except Exception as e:
        print(f"❌ 合并请求失败：{e}")


async def main():
    print(f"\n{'='*60}")
    print(f"合并机制诊断报告")
    print(f"时间：{datetime.now().isoformat()}")
    print(f"{'='*60}")
    
    # 1. 检查 Consolidator
    consolidator_ok = await check_consolidator_status()
    
    # 2. 检查堆段
    unmerged_count = await check_heap_segments()
    
    # 3. 检查 PublicMemory
    pm_count = await check_public_memory()
    
    # 4. 测试合并
    if consolidator_ok:
        await test_merge_endpoint()
    
    # 总结
    print("\n" + "="*60)
    print("诊断总结")
    print("="*60)
    
    if unmerged_count > 0 and pm_count < 10:
        print("⚠️  警告：大量堆段未合并，但 PublicMemory 条目很少")
        print("   可能原因：")
        print("   1. Consolidator 容器崩溃或无响应")
        print("   2. 合并触发机制失效（KM 未正确发送合并请求）")
        print("   3. 合并后端处理失败但返回成功状态码")
        print("\n建议操作：")
        print("   1. 重启 BFF 服务（会自动重建 Consolidator）")
        print("   2. 检查 Consolidator 容器日志：docker logs consolidator")
        print("   3. 降低 KM 合并阈值进行测试（如设为 5）")
    elif unmerged_count == 0:
        print("✅ 所有堆段已合并")
    else:
        print("✅ 系统状态正常")


if __name__ == "__main__":
    asyncio.run(main())
