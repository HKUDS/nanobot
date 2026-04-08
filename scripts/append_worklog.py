#!/usr/bin/env python3
"""Track file changes and manage worklog entries.

Usage:
  python append_worklog.py track   # PostToolUse: accumulate file path from stdin
  python append_worklog.py show    # Show pending changes
  python append_worklog.py flush   # Write one worklog entry and clean up
  python append_worklog.py clean   # Discard pending changes
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKLOG_PATH = REPO_ROOT / "docs" / "codex-worklog.md"
PENDING_PATH = REPO_ROOT / ".claude" / "worklog_pending.txt"

SKIP_PATTERNS = ["codex-worklog.md", "docs/README.md"]


def normalize_path(file_path: str) -> str:
    """Normalize and strip repo root prefix."""
    p = file_path.replace("\\", "/")
    for prefix in ["D:/nanobot/", "d/nanobot/"]:
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    return p


def track():
    """Accumulate modified file path to pending file."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        return

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    for pattern in SKIP_PATTERNS:
        if pattern in file_path:
            return

    display_path = normalize_path(file_path)
    with open(PENDING_PATH, "a", encoding="utf-8") as f:
        f.write(display_path + "\n")


def get_pending_files() -> list[str]:
    """Read and deduplicate pending file paths."""
    if not PENDING_PATH.exists():
        return []
    with open(PENDING_PATH, "r", encoding="utf-8") as f:
        return sorted(set(line.strip() for line in f if line.strip()))


def show():
    """Print pending changes."""
    files = get_pending_files()
    if not files:
        print("无待记录的变更。")
        return
    print("待记录的变更文件：")
    for f in files:
        print(f"  - {f}")


def flush():
    """Write one worklog entry from pending changes and clean up."""
    files = get_pending_files()
    if PENDING_PATH.exists():
        PENDING_PATH.unlink()

    if not files:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(WORKLOG_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return

    records = re.findall(r"### 记录 (\d+)", content)
    next_num = len(records) + 1

    files_str = "、".join(f"`{f}`" for f in files)

    entry = f"""
### 记录 {next_num}
- 日期时间: {now} (Asia/Shanghai)
- 修改文件: {files_str}
- 任务目标: [待补充]
- 实际操作: [待补充]
- 测试结果: [待补充]
- 风险/待办: [待补充]
"""

    with open(WORKLOG_PATH, "a", encoding="utf-8") as f:
        f.write(entry)

    print(f"已写入记录 {next_num}")


def clean():
    """Discard pending changes."""
    if PENDING_PATH.exists():
        PENDING_PATH.unlink()
    print("已丢弃待记录的变更。")


def main():
    if len(sys.argv) < 2:
        return
    command = sys.argv[1]
    if command == "track":
        track()
    elif command == "show":
        show()
    elif command == "flush":
        flush()
    elif command == "clean":
        clean()


if __name__ == "__main__":
    main()
