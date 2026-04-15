#!/usr/bin/env python3
"""
查看今天/明天/本周的日程安排

用法:
    python calendar_today_agenda.py              # 今天
    python calendar_today_agenda.py today        # 今天
    python calendar_today_agenda.py tomorrow     # 明天
    python calendar_today_agenda.py week         # 本周
    python calendar_today_agenda.py --dry-run    # 仅显示命令
"""

import sys
import json
import subprocess
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

TZ = timezone(timedelta(hours=8))


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


def get_range(scope: str):
    now = datetime.now(TZ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if scope == 'today':
        return today, today + timedelta(days=1)
    elif scope == 'tomorrow':
        t = today + timedelta(days=1)
        return t, t + timedelta(days=1)
    elif scope == 'week':
        ws = today - timedelta(days=today.weekday())
        return ws, ws + timedelta(days=7)
    return today, today + timedelta(days=1)


def fmt_iso(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%S+08:00')


def fmt_time(iso_str: str) -> str:
    if not iso_str:
        return '??:??'
    try:
        for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S'):
            try:
                dt = datetime.strptime(iso_str, fmt)
                return dt.strftime('%H:%M')
            except ValueError:
                continue
        return iso_str[:16]
    except Exception:
        return iso_str[:16]


def main():
    dry_run = '--dry-run' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--dry-run']
    scope = args[0] if args else 'today'
    if scope not in ('today', 'tomorrow', 'week'):
        print(__doc__)
        sys.exit(1)

    start, end = get_range(scope)
    data = run_dws([
        'calendar', 'event', 'list',
        '--start', fmt_iso(start),
        '--end', fmt_iso(end),
        '--format', 'json',
    ], dry_run=dry_run)
    if dry_run:
        return

    events = []
    if isinstance(data, list):
        events = data
    elif isinstance(data, dict):
        events = data.get('events', data.get('result', []))

    label = {'today': '今天', 'tomorrow': '明天', 'week': '本周'
             }.get(scope, scope)
    print(f"\n📅 {label}日程 ({start.strftime('%m-%d')} ~ "
          f"{end.strftime('%m-%d')})")
    print('=' * 50)

    if not events:
        print('  ✅ 暂无日程，自由安排！')
        return

    for e in events:
        title = e.get('summary') or e.get('title', '无标题')
        s = e.get('start', {})
        ed = e.get('end', {})
        start_t = fmt_time(
            s.get('dateTime', '') if isinstance(s, dict) else str(s)
        )
        end_t = fmt_time(
            ed.get('dateTime', '') if isinstance(ed, dict) else str(ed)
        )
        loc = e.get('location', {})
        loc_str = (loc.get('displayName', '')
                   if isinstance(loc, dict) else str(loc or ''))
        line = f"  🕐 {start_t}-{end_t}  {title}"
        if loc_str:
            line += f"  📍{loc_str}"
        print(line)

    print(f"\n合计: {len(events)} 场日程")


if __name__ == '__main__':
    main()
