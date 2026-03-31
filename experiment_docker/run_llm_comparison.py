"""Run LLM Backend Comparison Experiments"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from experiment_docker.orchestrator.runner import ExperimentOrchestrator, generate_experiment_configs
from experiment_docker.orchestrator.aggregator import ResultAggregator


async def main():
    base_dir = Path(__file__).parent
    max_concurrent = 4
    timeout = 1800
    batch_size = 10
    batch_delay = 2.0
    repetitions = 1
    mode = "local"  # 使用本地模式（直接调用 Provider API）
    
    orchestrator = ExperimentOrchestrator(base_dir, max_concurrent, mode=mode)
    
    configs = generate_experiment_configs()
    print(f"\n{'='*80}")
    print(f"LLM Backend 对比实验")
    print(f"{'='*80}")
    print(f"任务数：4 (Task1_Sales, Task2_User, Task3_Finance, Task4_Review)")
    print(f"LLM Backend: 3 (deepseek-chat, qwen3-max-2026-01-23, kimi-k2.5)")
    print(f"总实验数：{len(configs)} ({len(configs)} 任务 × {repetitions} 次重复)")
    print(f"并发数：{max_concurrent}")
    print(f"超时：{timeout}秒")
    print(f"批次延迟：{batch_delay}秒")
    print(f"运行模式：本地模式（直接调用 Provider API）")
    print(f"{'='*80}\n")
    
    # Run experiments
    results = await orchestrator.run_experiments_in_batches(
        configs * repetitions,
        timeout=timeout,
        batch_size=batch_size,
        delay_between_batches=batch_delay
    )
    
    # Save results
    orchestrator.save_results(results)
    
    # Aggregate results
    aggregator = ResultAggregator(base_dir / "results")
    results_dir = base_dir / "results" / "raw"
    results_files = list(results_dir.glob("results_*.json"))
    
    if results_files:
        latest = max(results_files, key=lambda p: p.stat().st_mtime)
        print(f"\n从 {latest} 聚合结果...")
        report = aggregator.aggregate_from_results_file(latest)
    else:
        print("\n未找到结果文件")


if __name__ == "__main__":
    asyncio.run(main())
