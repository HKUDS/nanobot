#!/usr/bin/env python3
"""
按部门名称搜索并列出所有成员（自动 deptId 解析）

用法:
    python contact_dept_members.py --query "技术部"
    python contact_dept_members.py --query "产品" --dry-run
"""

import sys
import json
import subprocess
import argparse
from typing import List, Any, Optional


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


def main():
    parser = argparse.ArgumentParser(
        description='按部门名称搜索并列出所有成员'
    )
    parser.add_argument(
        '--query', required=True, help='部门名称关键词'
    )
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print(f'🔍 搜索部门: {args.query}')
    dept_data = run_dws([
        'contact', 'dept', 'search',
        '--query', args.query, '--format', 'json',
    ], dry_run=args.dry_run)

    if args.dry_run:
        run_dws([
            'contact', 'dept', 'list-members',
            '--ids', '<DEPT_ID>', '--format', 'json',
        ], dry_run=True)
        return

    if not dept_data:
        print('未找到匹配部门')
        sys.exit(1)

    depts = (dept_data if isinstance(dept_data, list)
             else dept_data.get('result', dept_data.get('items', [])))
    if not depts:
        print('未找到匹配部门')
        sys.exit(1)

    for dept in depts:
        dept_id = dept.get('id') or dept.get('deptId')
        dept_name = dept.get('name') or dept.get('deptName', '未知')
        if not dept_id:
            continue

        print(f"\n📂 {dept_name} (ID: {dept_id})")
        print('-' * 40)

        members_data = run_dws([
            'contact', 'dept', 'list-members',
            '--ids', str(dept_id), '--format', 'json',
        ])
        if not members_data:
            print('  无法获取成员列表')
            continue

        members = (members_data if isinstance(members_data, list)
                   else members_data.get('result',
                        members_data.get('userlist', [])))
        if not members:
            print('  (暂无成员)')
            continue

        for m in members:
            name = m.get('name') or m.get('userName', '未知')
            title = m.get('title') or m.get('position', '')
            uid = m.get('userId') or m.get('userid', '')
            line = f"  👤 {name}"
            if title:
                line += f" ({title})"
            if uid:
                line += f"  [ID: {uid}]"
            print(line)

        print(f"  共 {len(members)} 人")


if __name__ == '__main__':
    main()
