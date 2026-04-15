#!/usr/bin/env python3
"""
一键创建日程 + 添加参与者 + 搜索并预定空闲会议室

用法:
    python calendar_schedule_meeting.py \
        --title "Q1 复盘会" \
        --start "2026-03-15T14:00" \
        --end "2026-03-15T15:00" \
        --users userId1,userId2 \
        --book-room

    python calendar_schedule_meeting.py --dry-run \
        --title "测试" --start "2026-03-15T14:00" --end "2026-03-15T15:00"
"""

import sys
import json
import subprocess
import argparse
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

TZ = timezone(timedelta(hours=8))


def run_dws(
    args: List[str], dry_run: bool = False,
) -> Optional[Any]:
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
    except (subprocess.TimeoutExpired, json.JSONDecodeError,
            FileNotFoundError) as e:
        print(f"  ✗ 错误：{e}")
        return None


def normalize_time(time_str: str) -> str:
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M',
                '%Y-%m-%dT%H:%M:%S'):
        try:
            dt = datetime.strptime(time_str, fmt)
            dt = dt.replace(tzinfo=TZ)
            return dt.strftime('%Y-%m-%dT%H:%M:%S+08:00')
        except ValueError:
            continue
    if '+' in time_str or time_str.endswith('Z'):
        return time_str
    raise ValueError(f"无法解析时间：{time_str}")


def main():
    parser = argparse.ArgumentParser(
        description='一键创建日程 + 添加参与者 + 预定会议室'
    )
    parser.add_argument('--title', required=True, help='日程标题')
    parser.add_argument('--start', required=True, help='开始时间')
    parser.add_argument('--end', required=True, help='结束时间')
    parser.add_argument('--desc', default='', help='日程描述')
    parser.add_argument('--users', default='', help='参与者 userId')
    parser.add_argument(
        '--book-room', action='store_true', help='自动预定会议室'
    )
    parser.add_argument(
        '--dry-run', action='store_true', help='仅显示命令'
    )
    args = parser.parse_args()

    try:
        start_iso = normalize_time(args.start)
        end_iso = normalize_time(args.end)
    except ValueError as e:
        print(f"错误：{e}")
        sys.exit(1)

    print('📅 创建日程...')
    create_args = [
        'calendar', 'event', 'create',
        '--title', args.title,
        '--start', start_iso,
        '--end', end_iso,
        '--format', 'json',
    ]
    if args.desc:
        create_args.extend(['--desc', args.desc])

    result = run_dws(create_args, dry_run=args.dry_run)
    if not result:
        sys.exit(1)

    event_id = None
    if not args.dry_run and isinstance(result, dict):
        event_id = result.get('eventId') or result.get('id')
    print(f"  ✓ 日程已创建" +
          (f" (eventId: {event_id})" if event_id else ""))

    if args.users and event_id:
        print('\n👥 添加参与者...')
        r = run_dws([
            'calendar', 'participant', 'add',
            '--event', event_id,
            '--users', args.users,
            '--format', 'json',
        ], dry_run=args.dry_run)
        if r:
            print(f"  ✓ 已添加参与者: {args.users}")
    elif args.users and args.dry_run:
        run_dws([
            'calendar', 'participant', 'add',
            '--event', '<EVENT_ID>',
            '--users', args.users,
            '--format', 'json',
        ], dry_run=True)

    if args.book_room:
        print('\n🏢 搜索空闲会议室...')
        rooms_data = run_dws([
            'calendar', 'room', 'search',
            '--start', start_iso,
            '--end', end_iso,
            '--available',
            '--format', 'json',
        ], dry_run=args.dry_run)

        if not args.dry_run and rooms_data:
            rooms = (rooms_data if isinstance(rooms_data, list)
                     else rooms_data.get('rooms', []))
            if rooms:
                room = rooms[0]
                room_id = room.get('roomId') or room.get('id')
                room_name = room.get('roomName') or room.get('name')
                print(f"  找到空闲会议室: {room_name}")
                if event_id and room_id:
                    r = run_dws([
                        'calendar', 'room', 'add',
                        '--event', event_id,
                        '--rooms', str(room_id),
                        '--format', 'json',
                    ], dry_run=args.dry_run)
                    if r:
                        print(f"  ✓ 已预定: {room_name}")
            else:
                print('  ⚠ 该时段无空闲会议室')

    print('\n✅ 完成!')


if __name__ == '__main__':
    main()
