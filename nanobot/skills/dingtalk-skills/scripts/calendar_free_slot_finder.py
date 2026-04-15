#!/usr/bin/env python3
"""
查询多人共同空闲时段，推荐最佳会议时间

用法:
    python calendar_free_slot_finder.py \
        --users userId1,userId2,userId3 \
        --date 2026-03-15 \
        --duration 60

    python calendar_free_slot_finder.py \
        --users userId1,userId2 \
        --date 2026-03-15 \
        --start-hour 9 --end-hour 18 \
        --duration 30 --dry-run
"""

import sys
import json
import subprocess
import argparse
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple

TZ = timezone(timedelta(hours=8))
SLOT_STEP_MIN = 30


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


def fmt_iso(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%S+08:00')


def parse_busy_intervals(
    data: Any,
) -> List[Tuple[datetime, datetime]]:
    intervals = []
    if not data:
        return intervals
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for user_data in data.values():
            if isinstance(user_data, list):
                items.extend(user_data)
            elif isinstance(user_data, dict):
                items.extend(
                    user_data.get('busyTimes', [])
                )
    for item in items:
        start_str = item.get('startTime') or item.get('start', '')
        end_str = item.get('endTime') or item.get('end', '')
        if not start_str or not end_str:
            continue
        for fmt in (
            '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M%z',
        ):
            try:
                s = datetime.strptime(start_str, fmt)
                e = datetime.strptime(end_str, fmt)
                if s.tzinfo is None:
                    s = s.replace(tzinfo=TZ)
                if e.tzinfo is None:
                    e = e.replace(tzinfo=TZ)
                intervals.append((s, e))
                break
            except ValueError:
                continue
    return intervals


def find_free_slots(
    day_start: datetime, day_end: datetime,
    busy: List[Tuple[datetime, datetime]],
    duration_min: int,
) -> List[Tuple[datetime, datetime]]:
    busy_sorted = sorted(busy, key=lambda x: x[0])
    merged: List[Tuple[datetime, datetime]] = []
    for s, e in busy_sorted:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    free: List[Tuple[datetime, datetime]] = []
    cursor = day_start
    for bs, be in merged:
        if cursor < bs:
            gap = (bs - cursor).total_seconds() / 60
            if gap >= duration_min:
                free.append((cursor, bs))
        cursor = max(cursor, be)
    if cursor < day_end:
        gap = (day_end - cursor).total_seconds() / 60
        if gap >= duration_min:
            free.append((cursor, day_end))
    return free


def main():
    parser = argparse.ArgumentParser(
        description='查询多人共同空闲时段'
    )
    parser.add_argument(
        '--users', required=True, help='用户 ID 列表，逗号分隔'
    )
    parser.add_argument(
        '--date', required=True, help='查询日期 YYYY-MM-DD'
    )
    parser.add_argument(
        '--duration', type=int, default=60,
        help='会议时长（分钟），默认 60',
    )
    parser.add_argument(
        '--start-hour', type=int, default=9,
        help='工作日开始小时，默认 9',
    )
    parser.add_argument(
        '--end-hour', type=int, default=18,
        help='工作日结束小时，默认 18',
    )
    parser.add_argument(
        '--dry-run', action='store_true', help='仅显示命令'
    )
    args = parser.parse_args()

    try:
        date = datetime.strptime(args.date, '%Y-%m-%d')
    except ValueError:
        print('错误：日期格式应为 YYYY-MM-DD')
        sys.exit(1)

    day_start = date.replace(
        hour=args.start_hour, tzinfo=TZ
    )
    day_end = date.replace(hour=args.end_hour, tzinfo=TZ)

    data = run_dws([
        'calendar', 'busy', 'search',
        '--users', args.users,
        '--start', fmt_iso(day_start),
        '--end', fmt_iso(day_end),
        '--format', 'json',
    ], dry_run=args.dry_run)

    if args.dry_run:
        return

    busy = parse_busy_intervals(data)
    free = find_free_slots(day_start, day_end, busy, args.duration)

    users_list = args.users.split(',')
    print(f"\n🕐 空闲时段查询 ({args.date})")
    print(f"   参与人: {len(users_list)} 人")
    print(f"   会议时长: {args.duration} 分钟")
    print(f"   工作时间: {args.start_hour}:00 ~ "
          f"{args.end_hour}:00")
    print('=' * 50)

    if not free:
        print('  ❌ 该日无共同空闲时段')
        return

    print(f"\n✅ 找到 {len(free)} 个可用时段:\n")
    for i, (s, e) in enumerate(free, 1):
        gap_min = int((e - s).total_seconds() / 60)
        label = '⭐ 推荐' if i == 1 else f'   备选{i-1}'
        print(f"  {label}  {s.strftime('%H:%M')} ~ "
              f"{e.strftime('%H:%M')}  ({gap_min}分钟)")


if __name__ == '__main__':
    main()
