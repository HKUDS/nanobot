"""
自动修复吞吐量实验脚本的合并验证问题

修复内容：
1. learn_throughput_fixed_time_b.py: trigger_merge() 添加重试机制
2. learn_throughput_fixed_time_b.py: main() 中添加合并验证
3. learn_throughput_fixed_time_a.py: 添加合并等待验证
"""

import re
import os

def fix_b_group():
    """修复 B 组脚本"""
    file_path = r"d:\collections2026\phd_application\nanobot1\milestone2\sayg_integration\learn_throughput_fixed_time_b.py"
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. 修改 trigger_merge 函数签名和实现
    old_trigger_merge = r'''async def trigger_merge\(\) -> float:
    """触发同步合并，返回合并耗时"""
    merge_start = time\.perf_counter\(\)
    try:
        async with httpx\.AsyncClient\(timeout=300\.0\) as client:
            resp = await client\.post\(f"\{BFF_BASE_URL\}/consolidator/merge"\)
            if resp\.status_code == 200:
                merge_time = time\.perf_counter\(\) - merge_start
                print\(f"  \[同步合并\] 完成: \{merge_time\:\.2f\}s"\)
                return merge_time
            else:
                print\(f"  \[同步合并\] 失败: HTTP \{resp\.status_code\}"\)
                return 0\.0
    except Exception as e:
        print\(f"  \[同步合并\] 异常：\{e\}"\)
        return 0\.0'''
    
    new_trigger_merge = '''async def trigger_merge() -> Tuple[bool, float, str]:
    """
    触发同步合并（带重试机制）
    
    Returns:
        (success, merge_time, error_message)
        - success: 是否成功
        - merge_time: 合并耗时（秒）
        - error_message: 错误信息
    """
    max_retries = 3
    retry_delay = 5.0
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
    return (False, total_time, last_error)'''
    
    content = re.sub(old_trigger_merge, new_trigger_merge, content)
    
    # 2. 修改调用处
    old_call = r'merge_time = await trigger_merge\(\)\n        total_merge_time \+= merge_time'
    new_call = '''merge_success, merge_time, merge_error = await trigger_merge()
        total_merge_time += merge_time
        
        # 如果合并失败，记录但继续实验
        if not merge_success:
            print(f"  ⚠️ [警告] 本轮合并失败，堆段可能未入库")
            # 不中断实验，继续下一轮'''
    
    content = re.sub(old_call, new_call, content)
    
    # 保存
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ B 组脚本已修复")


def fix_a_group():
    """修复 A 组脚本"""
    file_path = r"d:\collections2026\phd_application\nanobot1\milestone2\sayg_integration\learn_throughput_fixed_time_a.py"
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 添加导入
    if 'from typing import' not in content:
        content = content.replace(
            'import httpx',
            'import httpx\nfrom typing import Tuple'
        )
    
    # 在文件开头添加验证函数（在 BFF_BASE_URL 定义之后）
    validation_functions = '''

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
        print(f"[获取 PublicMemory] 失败：{e}")
    return 0


async def wait_for_auto_merge(
    initial_pm_count: int,
    timeout: float = 30.0,
    check_interval: float = 2.0
) -> Tuple[bool, int]:
    """
    等待自动合并完成
    
    Returns:
        (success, final_count)
    """
    start_time = time.time()
    
    print(f"  [{agent_name}] 等待自动合并... (初始={initial_pm_count}, 超时={timeout}s)")
    
    while time.time() - start_time < timeout:
        await asyncio.sleep(check_interval)
        
        current_count = await get_public_memory_count()
        
        if current_count > initial_pm_count:
            elapsed = time.time() - start_time
            growth = current_count - initial_pm_count
            print(f"  ✅ [{agent_name}] 合并完成：PublicMemory +{growth}条，耗时 {elapsed:.1f}s")
            return (True, current_count)
        
        # 显示进度
        print(f"  ⏳ [{agent_name}] 等待合并... PublicMemory={current_count}/{initial_pm_count}")
    
    print(f"  ❌ [{agent_name}] 合并超时：PublicMemory 仍为 {initial_pm_count}条")
    return (False, initial_pm_count)
'''
    
    # 找到合适的位置插入（在 wait_for_km_ready 函数之后）
    if 'async def wait_for_km_ready' in content:
        # 在 wait_for_km_ready 函数结束后插入
        pattern = r'(async def wait_for_km_ready\(.*?\n.*?return False\n)'
        match = re.search(pattern, content, re.MULTILINE)
        if match:
            end_pos = match.end()
            content = content[:end_pos] + validation_functions + content[end_pos:]
    
    # 修改等待逻辑
    old_wait = r'print\(f"  \[\{agent_name\}\] 等待自动合并\.\.\."\)\n        await asyncio\.sleep\(10\)'
    new_wait = '''# 等待自动合并并验证
        initial_pm_count = await get_public_memory_count()
        merge_success, final_pm_count = await wait_for_auto_merge(
            initial_pm_count=initial_pm_count,
            timeout=20.0
        )
        
        if not merge_success:
            print(f"  ⚠️ [{agent_name}] 自动合并可能失败，但继续下一轮")'''
    
    content = re.sub(old_wait, new_wait, content)
    
    # 保存
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ A 组脚本已修复")


if __name__ == "__main__":
    print("开始修复吞吐量实验脚本...")
    fix_b_group()
    fix_a_group()
    print("\n所有修复完成！请重新运行实验。")
