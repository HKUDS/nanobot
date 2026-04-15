#!/usr/bin/env python3
"""
从 JSON 文件批量创建待办（含优先级、截止时间、执行者）

用法:
    python todo_batch_create.py todos.json
    python todo_batch_create.py todos.json --dry-run

todos.json 格式:
    [
        {"title": "修复线上Bug", "executors": "userId1,userId2", "priority": 40},
        {"title": "写周报", "executors": "userId1", "due": "2026-03-15"},
        {"title": "代码评审", "executors": "userId1"},
        {"title": "每日站会", "executors": "userId1", "due": "2026-03-20",
         "recurrence": "DTSTART:20260320T020000Z\\nRRULE:FREQ=DAILY;INTERVAL=1"}
    ]

字段说明:
- title:     待办标题 (必填)
- executors: 执行者 userId，多人逗号分隔 (必填)
- priority:  优先级 10=低/20=普通/30=较高/40=紧急 (可选)
- due:       截止日期 YYYY-MM-DD 或毫秒时间戳 (可选)
- recurrence: 循环待办规则 (可选，需同时有 due)；字符串内需含换行，与 dws --recurrence 一致
"""

import sys
import json
import subprocess
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

ALLOWED_PRIORITIES = {10, 20, 30, 40}
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
MAX_FILE_SIZE = 10 * 1024 * 1024


def run_dws(
    args: List[str], dry_run: bool = False,
) -> Optional[Dict[str, Any]]:
    cmd = ['dws'] + args
    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
        return {'dry_run': True}
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"  ✗ 错误：{result.stderr.strip()}")
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print('  ✗ 命令执行超时', file=sys.stderr)
        return None
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"  ✗ 错误：{e}", file=sys.stderr)
        return None


def parse_due(due_value) -> Optional[str]:
    if not due_value:
        return None
    due_str = str(due_value)
    if due_str.isdigit() and len(due_str) >= 10:
        return due_str
    if DATE_PATTERN.match(due_str):
        dt = datetime.strptime(due_str, '%Y-%m-%d')
        dt = dt.replace(hour=23, minute=59, second=59)
        return str(int(dt.timestamp() * 1000))
    print(f"  ⚠ 无法解析截止时间：{due_value}，跳过")
    return None


def validate_todo(item: Dict[str, Any], idx: int) -> bool:
    if not isinstance(item, dict):
        print(f"  ✗ #{idx+1} 不是有效对象")
        return False
    if not item.get('title', '').strip():
        print(f"  ✗ #{idx+1} 缺少 title")
        return False
    if not item.get('executors', '').strip():
        print(f"  ✗ #{idx+1} 缺少 executors")
        return False
    priority = item.get('priority')
    if priority is not None and int(priority) not in ALLOWED_PRIORITIES:
        print(f"  ✗ #{idx+1} 无效优先级：{priority}")
        return False
    recurrence = item.get('recurrence')
    if recurrence and not str(recurrence).strip():
        print(f"  ✗ #{idx+1} recurrence 不能为空字符串")
        return False
    if recurrence and not item.get('due'):
        print(f"  ✗ #{idx+1} 设置 recurrence 时必须提供 due")
        return False
    return True


def main():
    dry_run = '--dry-run' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--dry-run']
    if not args:
        print(__doc__)
        sys.exit(1)

    file_path = Path(args[0])
    if not file_path.exists():
        print(f"错误：文件不存在：{file_path}")
        sys.exit(1)
    if file_path.stat().st_size > MAX_FILE_SIZE:
        print(f"错误：文件过大 (限制 {MAX_FILE_SIZE // 1024}KB)")
        sys.exit(1)

    with open(file_path, 'r', encoding='utf-8') as f:
        todos = json.load(f)
    if not isinstance(todos, list) or not todos:
        print('错误：JSON 文件必须是非空数组')
        sys.exit(1)

    for i, item in enumerate(todos):
        if not validate_todo(item, i):
            sys.exit(1)

    print(f"📋 准备创建 {len(todos)} 条待办\n")
    success, fail = 0, 0
    for i, item in enumerate(todos):
        title = item['title'].strip()
        cmd_args = [
            'todo', 'task', 'create',
            '--title', title,
            '--executors', item['executors'].strip(),
            '--format', 'json',
        ]
        priority = item.get('priority')
        if priority is not None:
            cmd_args.extend(['--priority', str(int(priority))])
        due = parse_due(item.get('due'))
        if due:
            cmd_args.extend(['--due', due])
        recurrence = item.get('recurrence')
        if recurrence:
            rr = str(recurrence).replace('\\n', '\n')
            cmd_args.extend(['--recurrence', rr])

        result = run_dws(cmd_args, dry_run=dry_run)
        if result:
            print(f"  ✓ [{i+1}/{len(todos)}] {title}")
            success += 1
        else:
            print(f"  ✗ [{i+1}/{len(todos)}] {title}")
            fail += 1

    print(f"\n完成: 成功 {success}, 失败 {fail}")
    sys.exit(0 if fail == 0 else 1)


if __name__ == '__main__':
    main()
