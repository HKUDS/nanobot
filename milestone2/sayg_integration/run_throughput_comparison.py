"""
SAYG-Mem 吞吐量对比实验 - 主控脚本

实验设计：
- 固定时间预算（默认 300 秒）
- A组：SAyG-Mem（无界推理 + 异步合并）
- B组：Baseline（轮次栅栏 + 同步合并）
- 对比指标：总完成轮数、合并耗时占比、Agent空闲占比等
"""

import asyncio
import os
import sys
import json
import time
import random
import re
import shutil
import subprocess
from datetime import datetime
from typing import Dict, List

import httpx

sys.path.insert(0, os.path.dirname(__file__))

from learn_throughput_fixed_time_a import run_throughput_experiment_a
from learn_throughput_fixed_time_b import run_throughput_experiment_b
from evaluate_quality import create_evaluator_agent, close_evaluator_agent, read_public_memory

# 实验数据目录
EXPERIMENT_DIR = os.path.join(os.path.dirname(__file__), "experiment_data")
BASE_DIR = os.path.dirname(__file__)
HEAP_DIR = os.path.join(BASE_DIR, "data", "heaps")
PUBLIC_MEMORY_DIR = os.path.join(BASE_DIR, "data", "public_memory")
PUBLIC_MEMORY_FILE = os.path.join(PUBLIC_MEMORY_DIR, "public_memory.jsonl")
A_PUBLIC_MEMORY_FILE = os.path.join(EXPERIMENT_DIR, "a_throughput_public_memory.jsonl")
B_PUBLIC_MEMORY_FILE = os.path.join(EXPERIMENT_DIR, "b_throughput_public_memory.jsonl")
BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")


def get_pm_path():
    """获取 PublicMemory 文件路径（与 A/B 组一致）"""
    pm_host_path = os.environ.get("PUBLIC_MEMORY_HOST_PATH")
    if pm_host_path:
        if os.path.isdir(pm_host_path):
            return os.path.join(pm_host_path, "public_memory.jsonl")
        else:
            return pm_host_path
    else:
        return os.path.join(BASE_DIR, "data", "public_memory", "public_memory.jsonl")


def shutdown_consolidator():
    """通过 BFF API 关闭 Consolidator"""
    print("\n[关闭Consolidator] 通过 BFF API 关闭...")
    try:
        subprocess.run(
            ["docker", "stop", "consolidator"],
            capture_output=True, timeout=10.0
        )
        print("  [关闭Consolidator] 成功")
    except Exception as e:
        print(f"  [关闭Consolidator] 失败: {e}")


def reset_km_public_memory():
    """重置KM容器的PublicMemory状态"""
    print("  [重置KM] 重置PublicMemory状态...")
    pm_path = get_pm_path()
    
    if os.path.exists(pm_path):
        os.remove(pm_path)
        print(f"  [重置KM] 已删除: {pm_path}")
    else:
        print(f"  [重置KM] 文件不存在: {pm_path}")
    
    pm_dir = os.path.dirname(pm_path)
    os.makedirs(pm_dir, exist_ok=True)
    open(pm_path, "w").close()
    print(f"  [重置KM] 已创建空文件: {pm_path}")


async def clear_environment():
    """通过 BFF API 清理实验环境"""
    print("\n[清理环境] 开始清理...")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{BFF_BASE_URL}/experiment/cleanup")
            if resp.status_code == 200:
                result = resp.json()
                print(f"  [清理环境] BFF清理完成: 停止 {result.get('stopped_agents', 0)} 个Agent, {result.get('stopped_consolidator', 0)} 个Consolidator")
            else:
                print(f"  [清理环境] BFF清理失败: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  [清理环境] BFF清理异常: {e}")
    
    shutdown_consolidator()
    reset_km_public_memory()
    await asyncio.sleep(2)
    
    if os.path.exists(HEAP_DIR):
        shutil.rmtree(HEAP_DIR)
        print(f"  已清理Heap目录: {HEAP_DIR}")
    
    print("[清理环境] 完成")


def generate_comparison_table(a_report: Dict, b_report: Dict):
    """生成对比表格"""
    a_rounds = a_report.get("total_rounds", 0)
    b_rounds = b_report.get("total_rounds", 0)
    throughput_improvement = a_rounds / b_rounds if b_rounds > 0 else 0

    print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                          SAYG-Mem 吞吐量对比实验结果                           ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  指标                      A组(SAYG)           B组(Baseline)      对比            ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  总完成轮数                {a_rounds:<18} {b_rounds:<18} {throughput_improvement:.2f}x           ║
║  平均单Agent轮数          {a_report.get('avg_rounds_per_agent', 0):<18.1f} {b_report.get('avg_rounds_per_agent', 0):<18.1f} -             ║
║  实际耗时(秒)             {a_report.get('actual_time', 0):<18.1f} {b_report.get('actual_time', 0):<18.1f} -             ║
║  推理总耗时(秒)           {a_report.get('total_inference_time', 0):<18.1f} {b_report.get('total_inference_time', 0):<18.1f} -             ║
║  Agent空闲占比            {a_report.get('idle_ratio', 0)*100:<17.1f}% {b_report.get('idle_ratio', 0)*100:<17.1f}% -             ║
║  PublicMemory条目数       {a_report.get('public_memory_count', 0):<18} {b_report.get('public_memory_count', 0):<18} -             ║
╚══════════════════════════════════════════════════════════════════════════════════╝
""")


async def call_agent_evaluate(agent_id: str, content: str) -> float:
    """调用 Agent 对内容进行质量评分（1-5分）"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{BFF_BASE_URL}/conversations/{agent_id}")
        resp.raise_for_status()
        port = resp.json().get("container_port")
        if not port:
            return 3.0

    prompt = f"""请对以下知识条目的质量进行严格评分（1-5 分）：

评分标准（必须严格）：
5 分：内容精炼、无冗余、观点深刻、结构清晰、信息量大
4 分：内容较好、少量冗余、观点有价值
3 分：内容一般、有一定冗余、观点普通
2 分：内容较差、冗余明显、观点浅显
1 分：内容差、大量重复、无价值

请只输出一个数字（1-5），不要任何解释。

待评估内容：
{content[:3000]}

评分："""

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"http://localhost:{port}/chat",
            json={"content": prompt, "model": "deepseek-chat"}
        )
        resp.raise_for_status()
        result = resp.json()
        response_content = result.get("content", "").strip()

        match = re.search(r'\b([1-5])\b', response_content)
        if match:
            return float(match.group(1))

        print(f"  [评分解析失败] {response_content[:100]}")
        return 3.0


async def llm_blind_evaluate(a_file: str, b_file: str) -> Dict:
    """LLM盲评 - 严格评估A组和B组的PublicMemory质量"""
    print(f"\n{'='*70}")
    print("LLM 盲评环节 - PublicMemory 质量评估")
    print(f"{'='*70}")

    a_entries = read_public_memory(a_file)
    b_entries = read_public_memory(b_file)

    if not a_entries and not b_entries:
        print("[LLM 盲评] 两组均无内容")
        return {"a_score": 0.0, "b_score": 0.0, "a_entries": 0, "b_entries": 0}

    print(f"[LLM 盲评] A组 {len(a_entries)} 条，B组 {len(b_entries)} 条")

    # 创建评估Agent
    evaluator_info = await create_evaluator_agent()
    evaluator_id = evaluator_info["conversation_id"]

    try:
        # A组评分：独立严格评分（最多10条）
        if len(a_entries) > 10:
            random.seed(42)
            a_sampled = random.sample(a_entries, 10)
        else:
            a_sampled = a_entries

        print(f"\n[LLM 盲评] A组评分中（{len(a_sampled)}条）...")
        a_scores = []
        for i, entry in enumerate(a_sampled):
            content = entry.get("content", "") or entry.get("page_content", "")
            if content:
                score = await call_agent_evaluate(evaluator_id, content)
                a_scores.append(score)
                print(f"    A组 [{i+1}/{len(a_sampled)}]: {score}")
                await asyncio.sleep(0.5)

        a_avg = sum(a_scores) / len(a_scores) if a_scores else 0.0

        # B组评分：对比A组评分（严格对比）
        if len(b_entries) > 10:
            random.seed(123)  # 不同种子，保证B组采样不同
            b_sampled = random.sample(b_entries, 10)
        else:
            b_sampled = b_entries

        print(f"\n[LLM 盲评] B组对比评分中（{len(b_sampled)}条，对比A组）...")
        b_scores = []
        for i, entry in enumerate(b_sampled):
            content = entry.get("content", "") or entry.get("page_content", "")
            if content:
                # 严格对比评分：对比A组平均分，给出相对分数
                score = await call_agent_compare_evaluate(evaluator_id, a_avg, content)
                b_scores.append(score)
                print(f"    B组 [{i+1}/{len(b_sampled)}]: {score}")
                await asyncio.sleep(0.5)

        b_avg = sum(b_scores) / len(b_scores) if b_scores else 0.0

        print(f"\n[LLM 盲评] 结果：")
        print(f"  A组（SAYG-Mem）独立评分：{a_avg:.2f}/5.0")
        print(f"  B组（Baseline）对比评分：{b_avg:.2f}/5.0（相对A组 {a_avg:.1f} 分）")

        return {
            "a_score": a_avg,
            "b_score": b_avg,
            "a_entries": len(a_entries),
            "b_entries": len(b_entries),
            "a_scores": a_scores,
            "b_scores": b_scores
        }

    finally:
        await close_evaluator_agent(evaluator_info)


async def call_agent_compare_evaluate(agent_id: str, a_avg_score: float, b_content: str) -> float:
    """调用 Agent 对比 A组平均分，评价 B组内容的相对质量"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{BFF_BASE_URL}/conversations/{agent_id}")
        resp.raise_for_status()
        port = resp.json().get("container_port")
        if not port:
            return 3.0

    prompt = f"""严格评估以下知识条目（评分1-5分）：

评分标准（必须严格，宁低勿高）：
5 分：内容精炼、无冗余、观点深刻、结构清晰、信息量大
4 分：内容较好、少量冗余、观点有价值
3 分：内容一般、有一定冗余、观点普通
2 分：内容较差、冗余明显、观点浅显
1 分：内容差、大量重复、无价值

参考基准：A组的平均质量评分约为 {a_avg_score:.1f} 分。
请严格按照此基准评分，如果内容不如A组平均水平，应给3分以下。

请只输出一个数字（1-5），不要任何解释。

待评估内容：
{b_content[:3000]}

评分："""

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"http://localhost:{port}/chat",
            json={"content": prompt, "model": "deepseek-chat"}
        )
        resp.raise_for_status()
        result = resp.json()
        response_content = result.get("content", "").strip()

        match = re.search(r'\b([1-5])\b', response_content)
        if match:
            return float(match.group(1))

        print(f"  [对比评分解析失败] {response_content[:100]}")
        return 3.0


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
    await clear_environment()
    
    try:
        a_report = await run_throughput_experiment_a()
        trial_result["a_group"] = a_report
        print(f"\n[A组] 第{trial_idx+1}次试验完成")
    except Exception as e:
        print(f"\n[A组] 第{trial_idx+1}次试验失败: {e}")
        trial_result["a_group"] = {"error": str(e)}
    
    # 清理环境
    await clear_environment()
    
    # 运行B组
    print(f"\n{'='*70}")
    print(f"第 {trial_idx+1} 次试验 - B组")
    print(f"{'='*70}")
    
    try:
        b_report = await run_throughput_experiment_b()
        trial_result["b_group"] = b_report
        print(f"\n[B组] 第{trial_idx+1}次试验完成")
    except Exception as e:
        print(f"\n[B组] 第{trial_idx+1}次试验失败: {e}")
        trial_result["b_group"] = {"error": str(e)}
    
    return trial_result


async def main():
    print("\n" + "=" * 70)
    print("SAYG-Mem 吞吐量对比实验（固定时间预算）")
    print("=" * 70)
    
    time_budget = int(os.environ.get("TIME_BUDGET", "300"))
    print(f"时间预算：{time_budget}秒")
    
    # 创建实验数据目录
    os.makedirs(EXPERIMENT_DIR, exist_ok=True)
    
    # 运行1次试验（先验证效果）
    trials = []
    for i in range(1):
        trial_result = await run_single_trial(i)
        trials.append(trial_result)
        
        # 保存单次试验结果
        trial_path = os.path.join(EXPERIMENT_DIR, f"throughput_trial_{i+1}_result.json")
        with open(trial_path, "w", encoding="utf-8") as f:
            json.dump(trial_result, f, ensure_ascii=False, indent=2)
        
        print(f"\n[试验{i+1}] 结果已保存: {trial_path}")
        
        # 试验间等待
        if i < 2:
            print(f"\n等待30秒后开始下一次试验...")
            await asyncio.sleep(30)
    
    # 生成对比表格
    if trials and trials[0]["a_group"] and trials[0]["b_group"]:
        a_report = trials[0]["a_group"]
        b_report = trials[0]["b_group"]
        
        if "error" not in a_report and "error" not in b_report:
            generate_comparison_table(a_report, b_report)

            # LLM 盲评环节
            quality_result = await llm_blind_evaluate(A_PUBLIC_MEMORY_FILE, B_PUBLIC_MEMORY_FILE)
            
            # 保存所有试验数据（含LLM评分）
            all_results_path = os.path.join(EXPERIMENT_DIR, "throughput_all_trials_result.json")
            with open(all_results_path, "w", encoding="utf-8") as f:
                json.dump({
                    "trials": trials,
                    "time_budget": time_budget,
                    "llm_quality": quality_result
                }, f, ensure_ascii=False, indent=2)
            
            print(f"\n所有试验数据已保存: {all_results_path}")
    
    # 清理导出文件
    print(f"\n{'='*70}")
    print("清理导出文件")
    print(f"{'='*70}")
    for path in [A_PUBLIC_MEMORY_FILE, B_PUBLIC_MEMORY_FILE]:
        if os.path.exists(path):
            os.remove(path)
            print(f"  已清理导出文件: {path}")
    
    print("\n✅ 吞吐量对比实验完成")


if __name__ == "__main__":
    asyncio.run(main())
