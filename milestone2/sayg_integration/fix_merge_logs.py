"""修复吞吐量实验脚本的日志问题"""

import re

# 修复 B 组脚本
b_file = r"d:\collections2026\phd_application\nanobot1\milestone2\sayg_integration\learn_throughput_fixed_time_b.py"

with open(b_file, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修复 trigger_merge 函数
old_b = '''async def trigger_merge() -> float:
    """触发同步合并，返回合并耗时"""
    merge_start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(f"{BFF_BASE_URL}/consolidator/merge")
            if resp.status_code == 200:
                merge_time = time.perf_counter() - merge_start
                print(f"  [同步合并] 完成：{merge_time:.2f}s")
                return merge_time
            else:
                print(f"  [同步合并] 失败：HTTP {resp.status_code}")
                return 0.0
    except Exception as e:
        print(f"  [同步合并] 异常：{e}")
        return 0.0'''

new_b = '''async def trigger_merge() -> float:
    """触发同步合并，返回合并耗时"""
    merge_start = time.perf_counter()
    url = f"{BFF_BASE_URL}/consolidator/merge"
    print(f"  [同步合并] 发送请求：{url}")
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(url)
            print(f"  [同步合并] 响应状态：{resp.status_code}")
            if resp.status_code == 200:
                result = resp.json()
                print(f"  [同步合并] 响应体：{json.dumps(result, ensure_ascii=False)[:500]}")
                merge_time = time.perf_counter() - merge_start
                print(f"  [同步合并] 完成：{merge_time:.2f}s")
                return merge_time
            else:
                resp_text = await resp.text()
                print(f"  [同步合并] 失败：HTTP {resp.status_code}, 响应：{resp_text[:500]}")
                return 0.0
    except Exception as e:
        print(f"  [同步合并] 异常：{type(e).__name__} - {e}")
        return 0.0'''

if old_b in content:
    content = content.replace(old_b, new_b)
    print("✅ B 组 trigger_merge() 已修复")
else:
    print("❌ 未找到 B 组 trigger_merge() 原函数")

with open(b_file, 'w', encoding='utf-8') as f:
    f.write(content)

# 修复 A 组脚本
a_file = r"d:\collections2026\phd_application\nanobot1\milestone2\sayg_integration\learn_throughput_fixed_time_a.py"

with open(a_file, 'r', encoding='utf-8') as f:
    content = f.read()

# 2. 修复 A 组等待逻辑
old_wait = '''# 等待自动合并完成（最多 60 秒）
        print(f"  [{agent_name}] 等待自动合并...")
        await asyncio.sleep(10)'''

new_wait = '''# 等待自动合并完成并轮询未合并堆段数
        print(f"\n  [{agent_name}] 等待自动合并：轮询未合并堆段数...")
        max_wait = 60
        waited = 0
        while waited < max_wait:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"{BFF_BASE_URL}/heap/all-unmerged")
                    if resp.status_code == 200:
                        data = resp.json()
                        unmerged = data.get("total_count", -1)
                        print(f"    [{agent_name}] 未合并堆段数：{unmerged} (已等待 {waited}s)")
                        if unmerged == 0:
                            break
            except Exception as e:
                print(f"    [{agent_name}] 查询未合并堆段失败：{e}")
            await asyncio.sleep(2)
            waited += 2
        
        if waited >= max_wait:
            print(f"  ⚠️  [{agent_name}] 等待合并超时，堆段可能未完全合并")
        else:
            print(f"  ✅  [{agent_name}] 所有堆段已合并 (耗时 {waited}s)")'''

if old_wait in content:
    content = content.replace(old_wait, new_wait)
    print("✅ A 组等待逻辑已修复")
else:
    print("❌ 未找到 A 组等待逻辑原代码")

with open(a_file, 'w', encoding='utf-8') as f:
    f.write(content)

print("\n✅ 所有修复完成！")
