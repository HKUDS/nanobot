"""Experiment Docker - Main entry point"""

import asyncio
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiment_docker.orchestrator.runner import ExperimentOrchestrator, generate_experiment_configs
from experiment_docker.orchestrator.aggregator import ResultAggregator


def parse_args():
    parser = argparse.ArgumentParser(description="Run Agent Architecture Comparison Experiments")
    parser.add_argument(
        "--mode",
        choices=["local", "cli", "docker-sdk", "aggregate", "clean", "status"],
        default="local",
        help="运行模式：local=本地直接运行，cli=docker 命令行，docker-sdk=docker SDK, aggregate=汇总结果，clean=清理容器，status=查看状态",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Base directory for experiment files",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=4,
        help="Maximum concurrent experiments",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=10,
        help="Number of repetitions per configuration",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Timeout per experiment (seconds)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of experiments per batch (to avoid timeout)",
    )
    parser.add_argument(
        "--batch-delay",
        type=float,
        default=2.0,
        help="Delay seconds between batches",
    )
    parser.add_argument(
        "--build-image",
        action="store_true",
        help="Force rebuild Docker image",
    )
    parser.add_argument(
        "--memory-config",
        choices=["VR", "SW"],
        help="Memory configuration (for single mode)",
    )
    parser.add_argument(
        "--tool-config",
        choices=["CG", "FG"],
        help="Tool configuration (for single mode)",
    )
    parser.add_argument(
        "--task-name",
        default="Task1",
        help="Task name (for single mode)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Run batch experiments (equivalent to --mode batch)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Clean all experiment containers and workspaces (for --mode clean)",
    )
    return parser.parse_args()


async def run_single(args):
    from experiment_docker.orchestrator.config import ExperimentConfig

    config = ExperimentConfig(
        session_key=f"{args.memory_config}_{args.tool_config}_{args.task_name}_rep1",
        memory_config=args.memory_config,
        tool_config=args.tool_config,
        task_name=args.task_name,
    )

    orchestrator = ExperimentOrchestrator(args.base_dir, args.max_concurrent, mode=args.mode)

    if args.build_image:
        orchestrator.build_image(force=True)

    result = await orchestrator.run_single_experiment(config, args.timeout)
    print(f"\nResult: {result}")
    return result


async def run_batch(args):
    orchestrator = ExperimentOrchestrator(args.base_dir, args.max_concurrent, mode=args.mode)

    if args.build_image:
        orchestrator.build_image(force=True)

    configs = generate_experiment_configs()
    print(f"Generated {len(configs)} base configurations")
    print(f"Will run {len(configs) * args.repetitions} total experiments")
    print(f"Mode: {args.mode}")

    # 使用分批执行避免超时
    results = await orchestrator.run_experiments_in_batches(
        configs * args.repetitions,
        timeout=args.timeout,
        batch_size=args.batch_size,
        delay_between_batches=args.batch_delay
    )
    
    orchestrator.save_results(results)

    aggregator = ResultAggregator(args.base_dir / "results")
    results_dir = args.base_dir / "results" / "raw"
    results_files = list(results_dir.glob("results_*.json"))
    if results_files:
        try:
            latest = max(results_files, key=lambda p: p.stat().st_mtime)
            report = aggregator.aggregate_from_results_file(latest)
        except Exception as e:
            print(f"Warning: Failed to aggregate results: {e}")
            print("You can manually run with --mode aggregate to retry.")

    return results


def run_aggregate(args):
    aggregator = ResultAggregator(args.base_dir / "results")
    logs_dir = args.base_dir / "results" / "raw"
    report = aggregator.aggregate_from_logs(logs_dir)
    return report


def run_clean(args):
    """清理实验容器和工作空间"""
    import subprocess
    
    print("清理 Docker 容器...")
    
    # 查找所有 nanobot_exp_ 开头的容器
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=nanobot_exp_", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        containers = result.stdout.strip().split("\n") if result.stdout.strip() else []
        
        if containers:
            print(f"找到 {len(containers)} 个实验容器")
            for container in containers:
                print(f"  删除容器：{container}")
                subprocess.run(
                    ["docker", "rm", "-f", container],
                    capture_output=True,
                    check=False,
                )
            print("容器清理完成")
        else:
            print("没有找到需要清理的容器")
        
        # 清理工作空间（如果指定 --all）
        if args.all:
            workspaces_dir = args.base_dir / "workspaces"
            if workspaces_dir.exists():
                import shutil
                print(f"\n清理工作空间目录：{workspaces_dir}")
                for ws in workspaces_dir.iterdir():
                    if ws.is_dir():
                        print(f"  删除工作空间：{ws.name}")
                        shutil.rmtree(ws)
                print("工作空间清理完成")
        
    except subprocess.CalledProcessError as e:
        print(f"Docker 命令执行失败：{e}")
    except Exception as e:
        print(f"清理过程出错：{e}")


def run_status(args):
    """查看实验状态"""
    import subprocess
    
    print("=" * 80)
    print("Docker 容器状态")
    print("=" * 80)
    
    try:
        # 查看运行中的容器
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=nanobot_exp_", "--format", "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip():
            print("\n运行中的容器:")
            print(result.stdout)
        else:
            print("\n没有运行中的容器")
        
        # 查看工作空间
        workspaces_dir = args.base_dir / "workspaces"
        if workspaces_dir.exists():
            workspaces = list(workspaces_dir.iterdir())
            print(f"\n工作空间数量：{len(workspaces)}")
            if workspaces:
                print("最近的工作空间:")
                for ws in sorted(workspaces, key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                    print(f"  - {ws.name} (创建时间：{datetime.fromtimestamp(ws.stat().st_mtime).isoformat()})")
        
        # 查看结果
        results_dir = args.base_dir / "results" / "raw"
        if results_dir.exists():
            result_files = list(results_dir.glob("results_*.json"))
            print(f"\n结果文件数量：{len(result_files)}")
            if result_files:
                print("最近的结果:")
                for rf in sorted(result_files, key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                    print(f"  - {rf.name} (修改时间：{datetime.fromtimestamp(rf.stat().st_mtime).isoformat()})")
        
    except subprocess.CalledProcessError as e:
        print(f"Docker 命令执行失败：{e}")
    except Exception as e:
        print(f"查看状态出错：{e}")
    
    print("=" * 80)


def main():
    args = parse_args()

    print_mode = args.mode if args.mode != "local" else "local (direct execution)"
    print(f"Running in {print_mode} mode")

    if args.mode == "clean":
        run_clean(args)
    elif args.mode == "status":
        run_status(args)
    elif args.memory_config and args.tool_config:
        asyncio.run(run_single(args))
    elif args.batch or args.mode == "local":
        # 默认运行 batch 实验
        asyncio.run(run_batch(args))
    elif args.mode == "aggregate":
        run_aggregate(args)
    else:
        print("\nExamples:")
        print("  python -m experiment_docker --mode local --batch --repetitions 10")
        print("  python -m experiment_docker --mode cli --memory-config VR --tool-config CG")
        print("  python -m experiment_docker --mode aggregate")
        print("  python -m experiment_docker --mode clean --all")
        print("  python -m experiment_docker --mode status")


if __name__ == "__main__":
    main()
