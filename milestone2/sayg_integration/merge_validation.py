"""
吞吐量实验共享工具：合并验证与重试机制

解决的核心问题：
1. B 组合并失败静默 → 添加重试 + 验证
2. A 组无合并验证 → 添加等待 + 检查
"""

import asyncio
import time
import httpx
from typing import Tuple, Optional

BFF_BASE_URL = "http://localhost:8000"


async def get_public_memory_count() -> int:
    """获取 PublicMemory 实际条目数"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/public-memory")
            if resp.status_code == 200:
                data = resp.json()
                entries = data.get("entries", [])
                return len(entries)
    except Exception as e:
        print(f"[工具] 获取 PublicMemory 失败：{e}")
    return 0


async def get_unmerged_heap_count() -> int:
    """获取未合并堆段数"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/heap/all-unmerged")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("total_count", 0)
    except Exception as e:
        print(f"[工具] 获取未合并堆段数失败：{e}")
    return 0


async def trigger_merge_with_retry(max_retries: int = 3, retry_delay: float = 5.0) -> Tuple[bool, float, str]:
    """
    触发同步合并（带重试机制）
    
    Returns:
        (success, merge_time, error_message)
        - success: 是否成功
        - merge_time: 合并耗时（秒）
        - error_message: 错误信息（成功时为空）
    """
    last_error = ""
    
    for attempt in range(1, max_retries + 1):
        merge_start = time.perf_counter()
        try:
            print(f"  [同步合并] 尝试 {attempt}/{max_retries}...")
            
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(f"{BFF_BASE_URL}/consolidator/merge")
                
                if resp.status_code == 200:
                    merge_time = time.perf_counter() - merge_start
                    print(f"  ✅ [同步合并] 成功：{merge_time:.2f}s")
                    return (True, merge_time, "")
                else:
                    error_msg = f"HTTP {resp.status_code}"
                    print(f"  ❌ [同步合并] 失败：{error_msg}")
                    last_error = error_msg
                    
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            print(f"  ❌ [同步合并] 异常：{error_msg}")
            last_error = error_msg
        
        if attempt < max_retries:
            print(f"  [同步合并] {retry_delay}秒后重试...")
            await asyncio.sleep(retry_delay)
    
    # 所有重试失败
    total_time = time.perf_counter() - merge_start
    print(f"  ❌ [同步合并] 已重试{max_retries}次，最终失败")
    return (False, total_time, last_error)


async def wait_for_merge_completion(
    initial_pm_count: int,
    expected_min_growth: int = 1,
    timeout: float = 30.0,
    check_interval: float = 2.0
) -> Tuple[bool, int, str]:
    """
    等待合并完成（验证 PublicMemory 增长）
    
    Args:
        initial_pm_count: 初始 PublicMemory 条目数
        expected_min_growth: 期望的最小增长数
        timeout: 超时时间（秒）
        check_interval: 检查间隔（秒）
    
    Returns:
        (success, final_count, status_message)
    """
    start_time = time.time()
    last_count = initial_pm_count
    
    print(f"  [合并验证] 等待合并完成... (初始={initial_pm_count}, 期望增长>={expected_min_growth}, 超时={timeout}s)")
    
    while time.time() - start_time < timeout:
        await asyncio.sleep(check_interval)
        
        current_count = await get_public_memory_count()
        
        if current_count >= initial_pm_count + expected_min_growth:
            elapsed = time.time() - start_time
            growth = current_count - initial_pm_count
            print(f"  ✅ [合并验证] 成功：PublicMemory {initial_pm_count} → {current_count} (+{growth}), 耗时 {elapsed:.1f}s")
            return (True, current_count, f"增长{growth}条")
        
        # 显示进度
        unmerged = await get_unmerged_heap_count()
        print(f"  ⏳ [合并验证] PublicMemory={current_count} (需+{expected_min_growth}), 未合并堆段={unmerged}")
        last_count = current_count
    
    # 超时
    print(f"  ❌ [合并验证] 超时：PublicMemory 仍为 {last_count} (期望增长>={expected_min_growth})")
    return (False, last_count, f"超时，PublicMemory 未增长")


async def verify_and_report_merge(
    round_num: int,
    initial_pm_count: int,
    merge_success: bool,
    merge_time: float,
    expected_growth: int = 1
) -> bool:
    """
    验证合并结果并打印报告
    
    Returns:
        是否成功（合并成功且 PublicMemory 增长）
    """
    print(f"\n  [第{round_num}轮合并报告]")
    print(f"  - 合并执行：{'✅ 成功' if merge_success else '❌ 失败'} ({merge_time:.2f}s)")
    
    if not merge_success:
        print(f"  ❌ [结论] 本轮合并失败，堆段未入库")
        return False
    
    # 验证 PublicMemory 增长
    success, final_count, status = await wait_for_merge_completion(
        initial_pm_count=initial_pm_count,
        expected_min_growth=expected_growth,
        timeout=20.0
    )
    
    if not success:
        print(f"  ❌ [结论] 合并执行成功但 PublicMemory 未增长，可能 Consolidator 异常")
        return False
    
    print(f"  ✅ [结论] 本轮合并有效")
    return True
