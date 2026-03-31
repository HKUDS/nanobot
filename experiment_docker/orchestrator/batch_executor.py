#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分批执行实验方案

将大量 API 调用分成多个批次，避免单次执行超时
"""

import asyncio
from typing import List, Any, Callable, Awaitable


async def execute_in_batches(
    tasks: List[Awaitable[Any]],
    batch_size: int = 10,
    delay_between_batches: float = 1.0,
) -> List[Any]:
    """
    分批执行异步任务
    
    Args:
        tasks: 要执行的任务列表
        batch_size: 每批任务数量（默认 10 个）
        delay_between_batches: 批次间延迟秒数（默认 1 秒）
    
    Returns:
        所有任务的执行结果
    """
    all_results = []
    total_tasks = len(tasks)
    num_batches = (total_tasks + batch_size - 1) // batch_size
    
    print(f"开始分批执行：共 {total_tasks} 个任务，分为 {num_batches} 批，每批最多 {batch_size} 个")
    
    for batch_idx in range(num_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, total_tasks)
        batch_tasks = tasks[start_idx:end_idx]
        
        print(f"\n[批次 {batch_idx + 1}/{num_batches}] 执行任务 {start_idx + 1}-{end_idx}")
        
        # 并发执行当前批次
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        all_results.extend(batch_results)
        
        # 检查是否有失败的任务
        success_count = sum(1 for r in batch_results if not isinstance(r, Exception))
        print(f"  [OK] 完成：{success_count}/{len(batch_results)} 成功")
        
        # 批次间延迟（避免 API 限流）
        if batch_idx < num_batches - 1:
            print(f"  [WAIT] 等待 {delay_between_batches} 秒...")
            await asyncio.sleep(delay_between_batches)
    
    return all_results


# 使用示例
async def example_usage():
    """使用示例"""
    
    # 模拟 36 个 API 调用任务
    async def mock_api_call(task_id: int):
        await asyncio.sleep(2)  # 模拟 2 秒的 API 调用
        return f"Task {task_id} completed"
    
    # 创建 36 个任务
    tasks = [mock_api_call(i) for i in range(36)]
    
    # 分批执行（每批 10 个任务）
    results = await execute_in_batches(
        tasks,
        batch_size=10,
        delay_between_batches=1.0
    )
    
    print(f"\n最终结果：{len(results)} 个任务完成")
    return results


if __name__ == "__main__":
    asyncio.run(example_usage())
