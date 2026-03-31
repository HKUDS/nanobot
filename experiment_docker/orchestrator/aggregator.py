"""结果汇总器 - 从日志文件聚合结果并生成报告"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from experiment_docker.orchestrator.config import ExperimentResult


class ResultAggregator:
    """结果汇总器"""

    def __init__(self, results_dir: Path):
        self.results_dir = Path(results_dir)
        self.raw_dir = self.results_dir / "raw"
        self.report_dir = self.results_dir / "report"
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def aggregate_from_results_file(self, results_file: Path) -> dict:
        """从 results.json 文件聚合结果"""
        if not results_file.exists():
            raise FileNotFoundError(f"Results file not found: {results_file}")

        try:
            content = results_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = results_file.read_text(encoding="gbk")
            except UnicodeDecodeError:
                content = results_file.read_text(encoding="utf-8", errors="replace")

        data = json.loads(content)
        results = [ExperimentResult(**r) for r in data["results"]]
        return self._generate_report(results)

    def aggregate_from_logs(self, logs_dir: Path) -> dict:
        """从原始日志目录聚合结果"""
        results = []
        for log_file in logs_dir.rglob("experiment.log"):
            session_key = log_file.parent.name
            result = self._parse_log_file(log_file, session_key)
            results.append(result)
        return self._generate_report(results)

    def _parse_log_file(self, log_file: Path, session_key: str) -> ExperimentResult:
        """解析单个日志文件"""
        content = log_file.read_text(encoding="utf-8")

        total_tokens = 0
        prompt_tokens = 0
        completion_tokens = 0
        request_count = 0
        success = False

        for line in content.split("\n"):
            if "total_tokens" in line and line.strip().startswith("{"):
                try:
                    record = json.loads(line)
                    total_tokens += record.get("total_tokens", 0)
                    prompt_tokens += record.get("prompt_tokens", 0)
                    completion_tokens += record.get("completion_tokens", 0)
                    request_count += 1
                except json.JSONDecodeError:
                    pass

        success = total_tokens > 0

        parts = session_key.split("_")
        memory_config = parts[0] if len(parts) > 0 else "UNKNOWN"
        tool_config = parts[1] if len(parts) > 1 else "UNKNOWN"
        task_name = parts[2] if len(parts) > 2 else "UNKNOWN"

        return ExperimentResult(
            session_key=session_key,
            memory_config=memory_config,
            tool_config=tool_config,
            task_name=task_name,
            success=success,
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            request_count=request_count,
            execution_time=0.0,
        )

    def _generate_report(self, results: list[ExperimentResult]) -> dict:
        """生成汇总报告 - 按 LLM backend 分组统计"""
        # 按 LLM backend 分组
        llm_groups = {}
        for r in results:
            llm_groups.setdefault(r.model, []).append(r)

        report = {
            "report_date": datetime.now().isoformat(),
            "total_experiments": len(results),
            "successful": sum(1 for r in results if r.success),
            "success_rate": sum(1 for r in results if r.success) / len(results) if results else 0,
            "llm_backends": {},
        }

        for model, group_results in llm_groups.items():
            tokens = [r.total_tokens for r in group_results]
            estimated_tokens = [r.estimated_tokens for r in group_results]
            successes = sum(1 for r in group_results if r.success)
            times = [r.execution_time for r in group_results if r.execution_time > 0]

            # 计算 token 估算误差
            token_errors = []
            for r in group_results:
                if r.estimated_tokens > 0 and r.total_tokens > 0:
                    error = abs(r.total_tokens - r.estimated_tokens) / r.estimated_tokens * 100
                    token_errors.append(error)

            llm_data = {
                "model": model,
                "count": len(group_results),
                "success_rate": successes / len(group_results) if group_results else 0,
                "avg_total_tokens": sum(tokens) / len(tokens) if tokens else 0,
                "min_total_tokens": min(tokens) if tokens else 0,
                "max_total_tokens": max(tokens) if tokens else 0,
                "std_total_tokens": self._std(tokens) if len(tokens) > 1 else 0,
                "avg_estimated_tokens": sum(estimated_tokens) / len(estimated_tokens) if estimated_tokens else 0,
                "avg_token_error_rate": sum(token_errors) / len(token_errors) if token_errors else 0,
                "avg_execution_time": sum(times) / len(times) if times else 0,
                "tasks": {},
            }

            # 按任务细分
            task_groups = {}
            for r in group_results:
                task_groups.setdefault(r.task_name, []).append(r)

            for task_name, task_results in task_groups.items():
                task_tokens = [r.total_tokens for r in task_results]
                task_estimated = [r.estimated_tokens for r in task_results]
                task_times = [r.execution_time for r in task_results if r.execution_time > 0]

                llm_data["tasks"][task_name] = {
                    "count": len(task_results),
                    "success": sum(1 for r in task_results if r.success),
                    "avg_total_tokens": sum(task_tokens) / len(task_tokens) if task_tokens else 0,
                    "avg_estimated_tokens": sum(task_estimated) / len(task_estimated) if task_estimated else 0,
                    "avg_execution_time": sum(task_times) / len(task_times) if task_times else 0,
                }

            report["llm_backends"][model] = llm_data

        # 保存报告
        report_file = self.report_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False))

        self._print_report_summary(report)

        return report

    def _std(self, values: list[float]) -> float:
        """计算标准差"""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return variance ** 0.5

    def _print_report_summary(self, report: dict) -> None:
        """打印报告摘要"""
        print("\n" + "=" * 80)
        print("LLM BACKEND 对比实验报告")
        print("=" * 80)
        print(f"生成时间：{report['report_date']}")
        print(f"总实验数：{report['total_experiments']}")
        print(f"总体成功率：{report['success_rate']:.1%}")
        print()
        
        # 按 LLM backend 汇总
        print("=" * 80)
        print("LLM Backend 性能对比")
        print("=" * 80)
        print(f"{'Model':<25} {'Count':>6} {'Success':>8} {'Avg Tokens':>12} {'Est Tokens':>12} {'Error%':>8} {'Avg Time(s)':>12}")
        print("-" * 80)

        for model, data in report["llm_backends"].items():
            print(f"{model:<25} {data['count']:>6} {data['success_rate']:>7.1%} {data['avg_total_tokens']:>12.0f} {data['avg_estimated_tokens']:>12.0f} {data['avg_token_error_rate']:>7.1f}% {data['avg_execution_time']:>12.1f}")

        print("=" * 80)
        
        # 按任务细分
        print("\n任务级别详情:")
        print("-" * 80)
        for model, data in report["llm_backends"].items():
            print(f"\n{model}:")
            print(f"  {'Task':<20} {'Count':>6} {'Success':>8} {'Avg Tokens':>12} {'Est Tokens':>12} {'Avg Time(s)':>12}")
            print(f"  {'-'*70}")
            for task_name, task_data in data["tasks"].items():
                print(f"  {task_name:<20} {task_data['count']:>6} {task_data['success']:>8} {task_data['avg_total_tokens']:>12.0f} {task_data['avg_estimated_tokens']:>12.0f} {task_data['avg_execution_time']:>12.1f}")

        print("=" * 80)
        print(f"\n完整报告保存至：{self.report_dir}")
