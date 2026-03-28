#!/usr/bin/env python3
"""feishu_attendance - 飞书考勤 API

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


def _pp(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# 考勤 (attendance/v1)
# ============================================================

def get_user_id_from_open_id(open_id: str) -> str:
    """通过 open_id 获取 user_id（考勤 API 的 employee_id 类型对应 contact 的 user_id）"""
    data = _get(f"/contact/v3/users/{open_id}", {"user_id_type": "open_id"},
                action="获取用户信息")
    user = data.get("user", {})
    uid = user.get("user_id")
    if not uid:
        raise RuntimeError(f"用户 {open_id} 没有 user_id（需权限 contact:user.base:readonly）")
    return uid


def get_attendance(
    user_ids: List[str],
    date_from: int,
    date_to: int,
) -> Dict[str, Any]:
    """查询打卡结果

    Args:
        user_ids: employee_id 列表（最多 50 个）
        date_from: 开始日期 yyyyMMdd
        date_to: 结束日期 yyyyMMdd
    """
    return _post(
        "/attendance/v1/user_tasks/query",
        {"user_ids": user_ids[:50], "check_date_from": date_from, "check_date_to": date_to},
        params={"employee_type": "employee_id"},
        action="查询考勤打卡",
    )


# ============================================================
# CLI
# ============================================================

def _resolve_ids(raw: str) -> List[str]:
    """接受 open_id 或 user_id，自动将 open_id 转换为 user_id"""
    ids = [i.strip() for i in raw.split(",") if i.strip()]
    result = []
    for uid in ids:
        if uid.startswith("ou_"):
            result.append(get_user_id_from_open_id(uid))
        else:
            result.append(uid)
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu_attendance", description="飞书考勤查询")
    sub = parser.add_subparsers(dest="action")
    p = sub.add_parser("query", help="查询打卡")
    p.add_argument("--user-ids", required=True, help="user_id 或 open_id(ou_开头自动转换)，逗号分隔")
    p.add_argument("--date-from", type=int, required=True, help="yyyyMMdd")
    p.add_argument("--date-to", type=int, required=True, help="yyyyMMdd")
    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "query":
        eids = _resolve_ids(args.user_ids)
        _pp(get_attendance(eids, args.date_from, args.date_to))


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
