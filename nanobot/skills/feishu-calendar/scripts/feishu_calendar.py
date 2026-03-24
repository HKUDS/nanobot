#!/usr/bin/env python3
"""feishu_calendar - 飞书日历与日程 API

凭据获取优先级: ~/.hiperone/config.json > 环境变量
"""

import argparse
import json
import os
import sys
import time as _time
import requests
from typing import Any, Dict, List, Optional


BASE_URL = "https://open.feishu.cn/open-apis"


def _load_nanobot_config() -> Dict[str, str]:
    config_path = os.path.expanduser("~/.hiperone/config.json")
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
            feishu = config.get("channels", {}).get("feishu", {})
            if feishu.get("enabled"):
                return {"appId": feishu.get("appId"), "appSecret": feishu.get("appSecret")}
    except Exception:
        pass
    return {}


_nanobot_cfg = _load_nanobot_config()
APP_ID = _nanobot_cfg.get("appId") or os.environ.get("NANOBOT_CHANNELS__FEISHU__APP_ID", "")
APP_SECRET = _nanobot_cfg.get("appSecret") or os.environ.get("NANOBOT_CHANNELS__FEISHU__APP_SECRET", "")
_token_cache: Dict[str, Any] = {"token": "", "expires": 0}


def get_tenant_access_token() -> str:
    if not APP_ID or not APP_SECRET:
        raise RuntimeError(
            "缺少飞书凭据，请配置 ~/.hiperone/config.json 或设置环境变量 "
            "NANOBOT_CHANNELS__FEISHU__APP_ID / NANOBOT_CHANNELS__FEISHU__APP_SECRET"
        )
    now = _time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=10)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 Token 失败: {data}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires"] = now + data.get("expire", 7200) - 60
    return _token_cache["token"]


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {get_tenant_access_token()}"}


def _check(data: dict, action: str) -> dict:
    if data.get("code") != 0:
        raise RuntimeError(f"{action}失败: [{data.get('code')}] {data.get('msg', 'Unknown error')}")
    return data.get("data", {})


def _get(path: str, params: Optional[dict] = None, *, timeout: int = 10, action: str = "") -> dict:
    resp = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=timeout)
    return _check(resp.json(), action or path)


def _post(path: str, payload: Optional[dict] = None, *, params: Optional[dict] = None,
          timeout: int = 10, action: str = "") -> dict:
    resp = requests.post(f"{BASE_URL}{path}", headers=_headers(), json=payload,
                         params=params, timeout=timeout)
    return _check(resp.json(), action or path)


def _put(path: str, payload: Optional[dict] = None, *, timeout: int = 10, action: str = "") -> dict:
    resp = requests.put(f"{BASE_URL}{path}", headers=_headers(), json=payload, timeout=timeout)
    return _check(resp.json(), action or path)


def _patch(path: str, payload: Optional[dict] = None, *, timeout: int = 10, action: str = "") -> dict:
    resp = requests.patch(f"{BASE_URL}{path}", headers=_headers(), json=payload, timeout=timeout)
    return _check(resp.json(), action or path)


def _delete(path: str, *, timeout: int = 10, action: str = "") -> dict:
    resp = requests.delete(f"{BASE_URL}{path}", headers=_headers(), timeout=timeout)
    return _check(resp.json(), action or path)


def _pp(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# 日历与日程 (calendar/v4)
# ============================================================

def calendar_list(page_size: int = 50, page_token: str = "") -> Dict[str, Any]:
    """获取日历列表"""
    params: Dict[str, Any] = {"page_size": page_size}
    if page_token:
        params["page_token"] = page_token
    return _get("/calendar/v4/calendars", params, action="获取日历列表")


def calendar_get(calendar_id: str) -> Dict[str, Any]:
    """获取日历信息"""
    return _get(f"/calendar/v4/calendars/{calendar_id}", action="获取日历信息")


def calendar_list_events(
    calendar_id: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page_size: int = 50,
    page_token: str = "",
) -> Dict[str, Any]:
    """获取日程列表"""
    params: Dict[str, Any] = {"page_size": page_size}
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    if page_token:
        params["page_token"] = page_token
    return _get(f"/calendar/v4/calendars/{calendar_id}/events", params,
                action="获取日程列表")


def calendar_get_event(calendar_id: str, event_id: str) -> Dict[str, Any]:
    """获取日程详情"""
    return _get(f"/calendar/v4/calendars/{calendar_id}/events/{event_id}",
                action="获取日程详情")


def calendar_create_event(
    calendar_id: str,
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    attendees: Optional[List[Dict]] = None,
    timezone: str = "Asia/Shanghai",
) -> Dict[str, Any]:
    """创建日程"""
    event: Dict[str, Any] = {
        "summary": summary,
        "start_time": {"timestamp": start_time} if start_time.isdigit()
            else {"date": start_time} if len(start_time) == 10
            else {"timestamp": start_time},
        "end_time": {"timestamp": end_time} if end_time.isdigit()
            else {"date": end_time} if len(end_time) == 10
            else {"timestamp": end_time},
        "time_zone": timezone,
    }
    if description:
        event["description"] = description
    if attendees:
        event["attendees"] = attendees
    return _post(f"/calendar/v4/calendars/{calendar_id}/events", event,
                 action="创建日程")


def calendar_update_event(
    calendar_id: str,
    event_id: str,
    fields: dict,
) -> Dict[str, Any]:
    """更新日程"""
    return _patch(f"/calendar/v4/calendars/{calendar_id}/events/{event_id}",
                  fields, action="更新日程")


def calendar_delete_event(calendar_id: str, event_id: str) -> Dict[str, Any]:
    """删除日程"""
    return _delete(f"/calendar/v4/calendars/{calendar_id}/events/{event_id}",
                   action="删除日程")


def _to_iso(ts: str) -> str:
    """将秒级时间戳转为 ISO 8601，已是 ISO 格式则原样返回"""
    if ts.isdigit():
        from datetime import datetime, timezone, timedelta
        dt = datetime.fromtimestamp(int(ts), tz=timezone(timedelta(hours=8)))
        return dt.isoformat()
    return ts


def calendar_freebusy(
    user_id: str,
    start_time: str,
    end_time: str,
    user_id_type: str = "open_id",
) -> Dict[str, Any]:
    """查询忙闲信息（时间支持秒级时间戳或 ISO 8601）"""
    return _post("/calendar/v4/freebusy/list", {
        "time_min": _to_iso(start_time),
        "time_max": _to_iso(end_time),
        "user_id": user_id,
    }, params={"user_id_type": user_id_type}, action="查询忙闲")


def meeting_room_search(
    query: str = "",
    room_level_id: str = "",
    page_size: int = 20,
) -> Dict[str, Any]:
    """搜索会议室"""
    params: Dict[str, Any] = {"page_size": page_size}
    if query:
        params["query"] = query
    if room_level_id:
        params["room_level_id"] = room_level_id
    return _get("/vc/v1/rooms", params, action="搜索会议室")


def meeting_reserve(
    start_time: str,
    end_time: str,
    room_id: Optional[str] = None,
    topic: str = "",
    owner_id: str = "",
) -> Dict[str, Any]:
    """预约会议

    使用 tenant_access_token 时 owner_id 必传。
    """
    payload: Dict[str, Any] = {"end_time": end_time}
    if owner_id:
        payload["owner_id"] = owner_id
    meeting_settings: Dict[str, Any] = {"topic": topic or "会议"}
    if room_id:
        meeting_settings["meeting_initial_type"] = 2
        meeting_settings["call_setting"] = {
            "callee": {
                "id": room_id, "user_type": 3,
                "pstn_sip_info": {"nickname": "room", "main_address": room_id},
            }
        }
    if start_time:
        payload["start_time"] = start_time
    payload["meeting_settings"] = meeting_settings
    return _post("/vc/v1/reserves/apply", payload,
                 params={"user_id_type": "open_id"}, action="预约会议")


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu_calendar", description="飞书日历与日程")
    sub = parser.add_subparsers(dest="action")

    p = sub.add_parser("list", help="列出日历")

    p = sub.add_parser("get", help="获取日历信息")
    p.add_argument("--calendar-id", required=True)

    p = sub.add_parser("events", help="列出日程")
    p.add_argument("--calendar-id", required=True)
    p.add_argument("--start-time", default="")
    p.add_argument("--end-time", default="")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("event-get", help="获取日程详情")
    p.add_argument("--calendar-id", required=True)
    p.add_argument("--event-id", required=True)

    p = sub.add_parser("event-create", help="创建日程")
    p.add_argument("--calendar-id", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--start-time", required=True)
    p.add_argument("--end-time", required=True)
    p.add_argument("--description", default="")

    p = sub.add_parser("event-update", help="更新日程")
    p.add_argument("--calendar-id", required=True)
    p.add_argument("--event-id", required=True)
    p.add_argument("--summary", default="", help="新标题")
    p.add_argument("--start-time", default="", help="新开始时间")
    p.add_argument("--end-time", default="", help="新结束时间")
    p.add_argument("--description", default="", help="新描述")

    p = sub.add_parser("event-delete", help="删除日程")
    p.add_argument("--calendar-id", required=True)
    p.add_argument("--event-id", required=True)

    p = sub.add_parser("freebusy", help="查询忙闲")
    p.add_argument("--user-id", required=True, help="open_id")
    p.add_argument("--start-time", required=True, help="秒级时间戳")
    p.add_argument("--end-time", required=True, help="秒级时间戳")

    p = sub.add_parser("rooms", help="搜索会议室")
    p.add_argument("--query", default="", help="搜索关键词")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("reserve", help="预约会议")
    p.add_argument("--start-time", required=True)
    p.add_argument("--end-time", required=True)
    p.add_argument("--room-id", default="", help="会议室 ID")
    p.add_argument("--topic", default="", help="会议主题")
    p.add_argument("--owner-id", default="", help="会议归属人 open_id（tenant_access_token 必传）")

    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "list":
        _pp(calendar_list())
    elif act == "get":
        _pp(calendar_get(args.calendar_id))
    elif act == "events":
        _pp(calendar_list_events(args.calendar_id, args.start_time or None,
                                 args.end_time or None, args.limit))
    elif act == "event-get":
        _pp(calendar_get_event(args.calendar_id, args.event_id))
    elif act == "event-create":
        _pp(calendar_create_event(args.calendar_id, args.summary,
                                  args.start_time, args.end_time, args.description))
    elif act == "event-update":
        fields: Dict[str, Any] = {}
        if args.summary:
            fields["summary"] = args.summary
        if args.description:
            fields["description"] = args.description
        if args.start_time:
            fields["start_time"] = ({"timestamp": args.start_time} if args.start_time.isdigit()
                                    else {"date": args.start_time} if len(args.start_time) == 10
                                    else {"timestamp": args.start_time})
        if args.end_time:
            fields["end_time"] = ({"timestamp": args.end_time} if args.end_time.isdigit()
                                  else {"date": args.end_time} if len(args.end_time) == 10
                                  else {"timestamp": args.end_time})
        _pp(calendar_update_event(args.calendar_id, args.event_id, fields))
    elif act == "event-delete":
        _pp(calendar_delete_event(args.calendar_id, args.event_id))
    elif act == "freebusy":
        _pp(calendar_freebusy(args.user_id, args.start_time, args.end_time))
    elif act == "rooms":
        _pp(meeting_room_search(args.query, page_size=args.limit))
    elif act == "reserve":
        _pp(meeting_reserve(args.start_time, args.end_time, args.room_id or None,
                            args.topic, args.owner_id))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.action:
        parser.print_help()
        return 1
    try:
        _run_cli(args)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
