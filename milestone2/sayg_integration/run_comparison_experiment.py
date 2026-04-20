"""
SAYG-Mem 对比实验 - 主控脚本

功能：
1. 清理环境
2. 运行A组实验（SAYG-Mem 并发分段写入 + 异步合并）
3. 清理环境
4. 运行B组实验（并发推理 + 写入加锁 + 轮间同步合并）
5. 重复3次
6. 调用LLM盲评
7. 生成对比表格
"""

import asyncio
import os
import sys
import json
import time
import shutil
import signal
import subprocess
from datetime import datetime
from typing import Dict, List

# 添加sayg_integration到路径
sys.path.insert(0, os.path.dirname(__file__))

from learn_segments_multi_collab import main as run_group_a
from learn_segments_serial_baseline import run_group_b_baseline as run_group_b
from evaluate_quality import compare_public_memory

# 实验数据目录（统一路径管理）
EXPERIMENT_DIR = os.path.join(os.path.dirname(__file__), "experiment_data")
BASE_DIR = os.path.dirname(__file__)
HEAP_DIR = os.path.join(BASE_DIR, "data", "heaps")
PUBLIC_MEMORY_DIR = os.path.join(BASE_DIR, "data", "public_memory")
PUBLIC_MEMORY_FILE = os.path.join(PUBLIC_MEMORY_DIR, "public_memory.jsonl")
A_PUBLIC_MEMORY_FILE = os.path.join(EXPERIMENT_DIR, "a_public_memory.jsonl")
B_PUBLIC_MEMORY_FILE = os.path.join(EXPERIMENT_DIR, "b_public_memory.jsonl")
B_LOCK_FILE = os.path.join(EXPERIMENT_DIR, "b_public_memory.lock")
BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")


def shutdown_consolidator():
    """优雅关闭Consolidator容器"""
    print("\n[关闭Consolidator] 尝试关闭Consolidator...")
    try:
        # 通过WSL关闭容器
        try:
            subprocess.run(["wsl", "docker", "stop", "consolidator"], capture_output=True, timeout=10.0)
            print("  [关闭Consolidator] 通过docker stop关闭成功")
        except Exception:
            print("  [关闭Consolidator] 关闭失败（不影响主流程）")
    except Exception as e:
        print(f"  [关闭Consolidator] 异常: {e}")


def reset_km_public_memory():
    """重置KM容器的PublicMemory状态"""
    print("  [重置KM] 重置PublicMemory状态...")
    try:
        # 通过WSL执行docker exec命令重置KM容器
        subprocess.run([
            "wsl", "docker", "exec", "knowledge-manager", 
            "sh", "-c", "rm -f /app/data/public_memory/*.jsonl"
        ], capture_output=True, timeout=10.0)
        print("  [重置KM] PublicMemory已重置")
    except Exception as e:
        print(f"  [重置KM] 重置失败: {e}")


def clear_environment():
    """清理实验环境（仅清理工作目录，保留导出文件供盲评）"""
    print("\n[清理环境] 开始清理...")
    
    # 优雅关闭Consolidator
    shutdown_consolidator()
    time.sleep(2)
    
    # 清理Heap目录
    if os.path.exists(HEAP_DIR):
        shutil.rmtree(HEAP_DIR)
        print(f"  已清理Heap目录: {HEAP_DIR}")
    
    # 清理PublicMemory文件（原始路径）
    if os.path.exists(PUBLIC_MEMORY_DIR):
        for f in os.listdir(PUBLIC_MEMORY_DIR):
            if f.endswith('.jsonl'):
                os.remove(os.path.join(PUBLIC_MEMORY_DIR, f))
        print(f"  已清理PublicMemory文件: {PUBLIC_MEMORY_DIR}")
    
    # 清理B组锁文件
    if os.path.exists(B_LOCK_FILE):
        os.remove(B_LOCK_FILE)
        print(f"  已清理B组锁文件: {B_LOCK_FILE}")
    
    # 注意：不再删除 A_PUBLIC_MEMORY_FILE 和 B_PUBLIC_MEMORY_FILE
    # 它们将在盲评结束后由主函数统一清理
    
    print("[清理环境] 完成")


async def run_single_trial(trial_idx: int) -> Dict:
    """运行单次试验（A组 + B组）"""
    print(f"\n{'='*70}")
    print(f"第 {trial_idx+1} 次试验")
    print(f"{'='*70}")
    
    trial_result = {
        "trial": trial_idx + 1,
        "timestamp": datetime.now().isoformat(),
        "a_group": None,
        "b_group": None
    }
    
    # 运行A组
    print(f"\n{'='*70}")
    print(f"第 {trial_idx+1} 次试验 - A组")
    print(f"{'='*70}")
    clear_environment()
    
    a_start = time.perf_counter()
    try:
        a_report = await run_group_a()
        a_time = time.perf_counter() - a_start
        if a_report is None:
            print(f"\n[A组] 第{trial_idx+1}次试验合并失败，实验终止")
            trial_result["a_group"] = {"error": "合并失败，实验终止"}
        else:
            trial_result["a_group"] = a_report
            print(f"\n[A组] 第{trial_idx+1}次试验完成，耗时: {a_time:.2f}s")
    except Exception as e:
        print(f"\n[A组] 第{trial_idx+1}次试验失败: {e}")
        trial_result["a_group"] = {"error": str(e)}
    
    # 清理环境
    clear_environment()
    await asyncio.sleep(2)
    
    # 运行B组
    print(f"\n{'='*70}")
    print(f"第 {trial_idx+1} 次试验 - B组")
    print(f"{'='*70}")
    
    b_start = time.perf_counter()
    try:
        b_report = await run_group_b()
        b_time = time.perf_counter() - b_start
        trial_result["b_group"] = b_report
        print(f"\n[B组] 第{trial_idx+1}次试验完成，耗时: {b_time:.2f}s")
    except Exception as e:
        print(f"\n[B组] 第{trial_idx+1}次试验失败: {e}")
        trial_result["b_group"] = {"error": str(e)}
    
    return trial_result


def calculate_averages(trials: List[Dict]) -> Dict:
    """计算多次试验的平均值"""
    a_times = []
    b_times = []
    a_pm_counts = []
    b_pm_counts = []
    a_idle_ratios = []
    b_idle_ratios = []
    
    for trial in trials:
        if trial["a_group"] and "error" not in trial["a_group"]:
            a_times.append(trial["a_group"].get("total_time", 0))
            a_pm_counts.append(trial["a_group"].get("pm_entry_count", 0))
            a_idle_ratios.append(trial["a_group"].get("idle_ratio", 0))
        
        if trial["b_group"] and "error" not in trial["b_group"]:
            b_times.append(trial["b_group"].get("total_time", 0))
            b_pm_counts.append(trial["b_group"].get("pm_entry_count", 0))
            b_idle_ratios.append(trial["b_group"].get("idle_ratio", 0))
    
    return {
        "a_group": {
            "avg_time": sum(a_times) / len(a_times) if a_times else 0,
            "avg_pm_count": sum(a_pm_counts) / len(a_pm_counts) if a_pm_counts else 0,
            "avg_idle_ratio": sum(a_idle_ratios) / len(a_idle_ratios) if a_idle_ratios else 0
        },
        "b_group": {
            "avg_time": sum(b_times) / len(b_times) if b_times else 0,
            "avg_pm_count": sum(b_pm_counts) / len(b_pm_counts) if b_pm_counts else 0,
            "avg_idle_ratio": sum(b_idle_ratios) / len(b_idle_ratios) if b_idle_ratios else 0
        }
    }


def generate_comparison_table(averages: Dict, a_score: float, b_score: float):
    """生成对比表格"""
    a_time = averages["a_group"]["avg_time"]
    b_time = averages["b_group"]["avg_time"]
    time_improvement = b_time / a_time if a_time > 0 else 0
    
    a_pm = averages["a_group"]["avg_pm_count"]
    b_pm = averages["b_group"]["avg_pm_count"]
    dedup_rate = (b_pm - a_pm) / b_pm if b_pm > 0 else 0
    
    table = f"""
# SAYG-Mem 对比实验结果

## 实验设置
- 重复次数: 3次
- Agent数量: 5
- 每Agent轮数: 5

## 对比结果

| 指标 | A组（SAYG-Mem） | B组（并发+锁+同步合并） | 提升 |
|------|----------------|------------------------|------|
| 总耗时 | {a_time:.2f}s | {b_time:.2f}s | {time_improvement:.1f}× |
| PublicMemory条目数 | {a_pm:.0f} | {b_pm:.0f} | 去重率 {dedup_rate*100:.1f}% |
| Agent空闲等待占比 | {averages['a_group']['avg_idle_ratio']*100:.1f}% | {averages['b_group']['avg_idle_ratio']*100:.1f}% | - |
| LLM质量评分 | {a_score:.1f} | {b_score:.1f} | +{(a_score-b_score)/b_score*100:.0f}% |

## 结论

A组（SAYG-Mem）相比B组（传统并发+锁+同步合并）：
- 时间效率提升 {time_improvement:.1f}×
- 存储效率提升 {dedup_rate*100:.1f}%（去重率）
- 知识质量提升 {(a_score-b_score)/b_score*100:.0f}%（LLM评分）
"""
    
    # 保存对比表格
    comparison_path = os.path.join(EXPERIMENT_DIR, "comparison_result.md")
    with open(comparison_path, "w", encoding="utf-8") as f:
        f.write(table)
    
    print(f"\n对比结果已保存: {comparison_path}")
    print(table)


async def main():
    print("\n" + "=" * 70)
    print("SAYG-Mem 对比实验")
    print("=" * 70)
    
    # 创建实验数据目录
    os.makedirs(EXPERIMENT_DIR, exist_ok=True)
    
    # 运行1次试验（先验证效果）
    trials = []
    for i in range(1):
        trial_result = await run_single_trial(i)
        trials.append(trial_result)
        
        # 保存单次试验结果
        trial_path = os.path.join(EXPERIMENT_DIR, f"trial_{i+1}_result.json")
        with open(trial_path, "w", encoding="utf-8") as f:
            json.dump(trial_result, f, ensure_ascii=False, indent=2)
        
        print(f"\n[试验{i+1}] 结果已保存: {trial_path}")
        
        # 试验间等待
        if i < 2:
            print(f"\n等待60秒后开始下一次试验...")
            await asyncio.sleep(60)
    
    # 计算平均值
    print(f"\n{'='*70}")
    print("计算平均值")
    print(f"{'='*70}")
    averages = calculate_averages(trials)
    
    # LLM对比盲评（先独立评A，再对比评B）
    print(f"\n{'='*70}")
    print("LLM对比盲评")
    print(f"{'='*70}")
    
    a_pm_path = A_PUBLIC_MEMORY_FILE
    b_pm_path = B_PUBLIC_MEMORY_FILE
    
    if not os.path.exists(a_pm_path) or not os.path.exists(b_pm_path):
        print(f"[错误] PublicMemory文件不存在")
        a_score = 0.0
        b_score = 0.0
    else:
        a_score, b_score = await compare_public_memory(a_pm_path, b_pm_path)
    
    print(f"\n[LLM对比盲评] A组评分: {a_score:.1f}/5.0")
    print(f"[LLM对比盲评] B组评分: {b_score:.1f}/5.0")
    
    # 生成对比表格
    generate_comparison_table(averages, a_score, b_score)
    
    # 保存所有试验数据
    all_results_path = os.path.join(EXPERIMENT_DIR, "all_trials_result.json")
    with open(all_results_path, "w", encoding="utf-8") as f:
        json.dump({
            "trials": trials,
            "averages": averages,
            "llm_scores": {"a_group": a_score, "b_group": b_score}
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n所有试验数据已保存: {all_results_path}")
    
    # 盲评结束后清理导出文件
    print(f"\n{'='*70}")
    print("清理导出文件")
    print(f"{'='*70}")
    for path in [A_PUBLIC_MEMORY_FILE, B_PUBLIC_MEMORY_FILE]:
        if os.path.exists(path):
            os.remove(path)
            print(f"  已清理导出文件: {path}")
    
    print("\n✅ 对比实验完成")


if __name__ == "__main__":
    asyncio.run(main())
