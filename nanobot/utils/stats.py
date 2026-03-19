"""Token usage statistics management."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_runtime_subdir
from nanobot.utils.helpers import ensure_dir


class StatsManager:
    """Manages token usage statistics for all sessions."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.stats_dir = ensure_dir(workspace / "stats")
        self.stats_file = self.stats_dir / "usage.jsonl"

    def record_usage(
        self,
        session_key: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        """Record usage data to the global stats file."""
        if total_tokens <= 0:
            return

        record = {
            "timestamp": datetime.now().isoformat(),
            "session_key": session_key,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

        try:
            with open(self.stats_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            # Update daily report after recording
            self.generate_daily_report()
        except Exception as e:
            logger.error("Failed to record usage stats: {}", e)

    def get_session_stats(self, session_key: str) -> dict[str, int]:
        """Aggregate usage stats for a specific session."""
        stats = {"prompt": 0, "completion": 0, "total": 0}
        if not self.stats_file.exists():
            return stats

        try:
            with open(self.stats_file, encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line)
                    if data.get("session_key") == session_key:
                        stats["prompt"] += data.get("prompt_tokens", 0)
                        stats["completion"] += data.get("completion_tokens", 0)
                        stats["total"] += data.get("total_tokens", 0)
        except Exception as e:
            logger.error("Failed to read session stats: {}", e)

        return stats

    def get_daily_stats(self, date_str: str | None = None) -> dict[str, int]:
        """Aggregate usage stats for a specific day (default today)."""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        stats = {"prompt": 0, "completion": 0, "total": 0}
        if not self.stats_file.exists():
            return stats

        try:
            with open(self.stats_file, encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line)
                    if data.get("timestamp", "").startswith(date_str):
                        stats["prompt"] += data.get("prompt_tokens", 0)
                        stats["completion"] += data.get("completion_tokens", 0)
                        stats["total"] += data.get("total_tokens", 0)
        except Exception as e:
            logger.error("Failed to read daily stats: {}", e)

        return stats

    def generate_daily_report(self) -> None:
        """Generate/Update a Markdown report for today's usage."""
        today = datetime.now().strftime("%Y-%m-%d")
        report_file = self.stats_dir / f"daily_{today}.md"

        if not self.stats_file.exists():
            return

        model_stats: dict[str, dict[str, int]] = {}
        try:
            with open(self.stats_file, encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line)
                    if data.get("timestamp", "").startswith(today):
                        model = data.get("model", "unknown")
                        if model not in model_stats:
                            model_stats[model] = {"prompt": 0, "completion": 0, "total": 0}
                        model_stats[model]["prompt"] += data.get("prompt_tokens", 0)
                        model_stats[model]["completion"] += data.get("completion_tokens", 0)
                        model_stats[model]["total"] += data.get("total_tokens", 0)
        except Exception:
            return

        if not model_stats:
            return

        lines = [
            f"# Daily Token Usage Report: {today}",
            "",
            "| Model | Prompt Tokens | Completion Tokens | Total Tokens |",
            "| :--- | :--- | :--- | :--- |",
        ]
        
        grand_total = {"prompt": 0, "completion": 0, "total": 0}
        for model, s in sorted(model_stats.items()):
            lines.append(f"| {model} | {s['prompt']:,} | {s['completion']:,} | {s['total']:,} |")
            grand_total["prompt"] += s["prompt"]
            grand_total["completion"] += s["completion"]
            grand_total["total"] += s["total"]

        lines.append(f"| **TOTAL** | **{grand_total['prompt']:,}** | **{grand_total['completion']:,}** | **{grand_total['total']:,}** |")
        lines.append("")
        lines.append(f"*Last updated: {datetime.now().strftime('%H:%M:%S')}*")

        try:
            report_file.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass
