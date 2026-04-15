#!/usr/bin/env python3
"""
扫描已过截止时间但未完成的待办，输出逾期清单

用法:
    python todo_overdue_check.py
    python todo_overdue_check.py --dry-run
"""

import sys
import json
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional

PAGE_SIZE = 50
MAX_PAGES = 10
PRIORITY_MAP = {10: '低', 20: '普通', 30: '较高', 40: '紧急'}


def run_dws(
    args: List[str], dry_run: bool = False,
) -> Optional[Any]:
    cmd = ['dws'] + args
    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
        return None
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"错误：{result.stderr.strip()}", file=sys.stderr)
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError,
            FileNotFoundError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return None


def fetch_all_undone(dry_run: bool = False) -> List[Dict[str, Any]]:
    all_todos: List[Dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        data = run_dws([
            'todo', 'task', 'list',
            '--page', str(page), '--size', str(PAGE_SIZE),
            '--status', 'false', '--format', 'json',
        ], dry_run=dry_run)
        if dry_run or not data:
            break
        items = (data if isinstance(data, list)
                 else data.get('result', data.get('todoCards', [])))
        if not items or not isinstance(items, list):
            break
        all_todos.extend(items)
        if len(items) < PAGE_SIZE:
            break
    return all_todos


def find_overdue(todos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now_ms = int(datetime.now().timestamp() * 1000)
    overdue = []
    for t in todos:
        due = t.get('dueTime') or t.get('due')
        if not due:
            continue
        try:
            if int(due) < now_ms:
                overdue.append(t)
        except (ValueError, TypeError):
            continue
    return overdue


def days_overdue(due_ms) -> int:
    now = datetime.now()
    try:
        due_dt = datetime.fromtimestamp(int(due_ms) / 1000)
        return max(0, (now - due_dt).days)
    except (ValueError, TypeError, OSError):
        return 0


def main():
    dry_run = '--dry-run' in sys.argv
    todos = fetch_all_undone(dry_run=dry_run)
    if dry_run:
        return

    overdue = find_overdue(todos)
    overdue.sort(
        key=lambda t: int(t.get('dueTime') or t.get('due', 0))
    )

    print(f"\n⏰ 逾期待办检查 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print('=' * 50)

    if not overdue:
        print('  ✅ 没有逾期待办，继续保持！')
        return

    for t in overdue:
        title = t.get('subject') or t.get('title', '无标题')
        due = t.get('dueTime') or t.get('due')
        days = days_overdue(due)
        pri = PRIORITY_MAP.get(
            int(t.get('priority', 20)), '普通'
        )
        due_str = datetime.fromtimestamp(
            int(due) / 1000
        ).strftime('%Y-%m-%d')
        print(f"  🔴 [{pri}] {title}")
        print(f"     截止: {due_str}  逾期: {days} 天")

    print(f"\n合计: {len(overdue)} 条逾期待办")
    sys.exit(1 if overdue else 0)


if __name__ == '__main__':
    main()
