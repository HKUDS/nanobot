#!/usr/bin/env python3
"""
查看我今天/本周/指定日期的考勤记录（自动获取 userId）

用法:
    python attendance_my_record.py               # 今天
    python attendance_my_record.py today          # 今天
    python attendance_my_record.py 2026-03-10     # 指定日期
    python attendance_my_record.py --dry-run      # 仅显示命令
"""

import sys
import json
import subprocess
import re
from datetime import datetime
from typing import List, Any, Optional

DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')


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


def get_my_user_id(dry_run: bool = False) -> Optional[str]:
    data = run_dws([
        'contact', 'user', 'get-self', '--format', 'json',
    ], dry_run=dry_run)
    if dry_run:
        return '<MY_USER_ID>'
    if not data or not isinstance(data, dict):
        return None
    return data.get('userId') or data.get('userid')


def main():
    dry_run = '--dry-run' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--dry-run']

    date_str = args[0] if args else 'today'
    if date_str == 'today':
        date_str = datetime.now().strftime('%Y-%m-%d')
    elif not DATE_PATTERN.match(date_str):
        print(__doc__)
        sys.exit(1)

    print('🔍 获取当前用户信息...')
    user_id = get_my_user_id(dry_run=dry_run)
    if not user_id and not dry_run:
        print('错误：无法获取当前用户 ID')
        sys.exit(1)

    print(f'📊 查询 {date_str} 考勤记录...\n')
    data = run_dws([
        'attendance', 'record', 'get',
        '--user', user_id or '<MY_USER_ID>',
        '--date', date_str,
        '--format', 'json',
    ], dry_run=dry_run)

    if dry_run:
        return
    if not data:
        print('未查到考勤记录')
        return

    print(f"📋 考勤记录 ({date_str})")
    print('=' * 40)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
