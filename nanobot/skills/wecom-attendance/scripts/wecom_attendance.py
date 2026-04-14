#!/usr/bin/env python3
"""wecom_attendance - 企业微信打卡 API

凭据获取优先级：~/.hiperone/config.json > 环境变量
"""

import argparse
import json
import os
import sys
import time as _time
import requests
from typing import Any, Dict, List, Optional


BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin"


def _load_nanobot_config() -> Dict[str, str]:
    config_path = os.path.expanduser("~/.hiperone/config.json")
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
            wecom = config.get("channels", {}).get("wecom", {})
            if wecom.get("enabled"):
                return {
                    "corp_id": wecom.get("corp_id"),
                    "corp_secret": wecom.get("corp_secret")
                }
    except Exception:
        pass
    return {}


_nanobot_cfg = _load_nanobot_config()
CORP_ID = _nanobot_cfg.get("corp_id") or os.environ.get("NANOBOT_CHANNELS__WECOM__CORP_ID", "")
CORP_SECRET = _nanobot_cfg.get("corp_secret") or os.environ.get("NANOBOT_CHANNELS__WECOM__CORP_SECRET", "")

_token_cache: Dict[str, Any] = {"token": "", "expires": 0}


def get_access_token() -> str:
    if not CORP_ID or not CORP_SECRET:
        raise RuntimeError("缺少企业微信凭据")
    now = _time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]
    
    url = f"{BASE_URL}/auth/get_access_token"
    params = {"corpid": CORP_ID, "corpsecret": CORP_SECRET}
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"获取 Token 失败：{data}")
    
    _token_cache["token"] = data["access_token"]
    _token_cache["expires"] = now + data.get("expires_in", 7200) - 60
    return _token_cache["token"]


def _check(data: dict, action: str) -> dict:
    if data.get("errcode") != 0:
        raise RuntimeError(f"{action}失败：[{data.get('errcode')}] {data.get('errmsg', 'Unknown error')}")
    return data


def _post(path: str, payload: Optional[dict] = None, *, timeout: int = 10, action: str = "") -> dict:
    url = f"{BASE_URL}{path}"
    params = {"access_token": get_access_token()}
    resp = requests.post(url, params=params, json=payload, timeout=timeout)
    return _check(resp.json(), action or path)


def _pp(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# 打卡 API
# ============================================================

def get_checkin_data(
    opencheckindata: int,
    useridlist: List[str],
    starttime: int,
    endtime: int
) -> Dict[str, Any]:
    """获取打卡记录
    
    opencheckindata: 1-打卡记录，0-排班信息
    starttime/endtime: Unix 时间戳（秒）
    """
    payload = {
        "opencheckindata": opencheckindata,
        "useridlist": useridlist,
        "starttime": starttime,
        "endtime": endtime
    }
    return _post("/checkin/getcheckindata", payload, action="获取打卡记录")


def get_corp_checkin_option(
    datetime: int
) -> Dict[str, Any]:
    """获取打卡规则
    
    datetime: Unix 时间戳，获取该时间的规则
    """
    payload = {"datetime": datetime}
    return _post("/checkin/getcorpcheckinoption", payload, action="获取打卡规则")


def get_group_list() -> Dict[str, Any]:
    """获取打卡组列表"""
    return _post("/checkin/getcheckinoption", {}, action="获取打卡组列表")


def add_checkin_user(
    groupid: int,
    useridlist: List[str],
    schedulelist: Optional[List[int]] = None
) -> Dict[str, Any]:
    """添加打卡人员"""
    payload = {
        "groupid": groupid,
        "useridlist": useridlist
    }
    if schedulelist:
        payload["schedulelist"] = schedulelist
    return _post("/checkin/addcheckinuser", payload, action="添加打卡人员")


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wecom_attendance", description="企业微信打卡")
    sub = parser.add_subparsers(dest="action")
    
    # data
    p = sub.add_parser("data", help="获取打卡记录")
    p.add_argument("--useridlist", required=True, help="逗号分隔的 userid 列表")
    p.add_argument("--start-time", type=int, required=True)
    p.add_argument("--end-time", type=int, required=True)
    p.add_argument("--type", type=int, default=1, help="1-打卡记录，0-排班")
    
    # option
    p = sub.add_parser("option", help="获取打卡规则")
    p.add_argument("--datetime", type=int, required=True)
    
    # group
    p = sub.add_parser("group", help="获取打卡组列表")
    
    # add-user
    p = sub.add_parser("add-user", help="添加打卡人员")
    p.add_argument("--groupid", type=int, required=True)
    p.add_argument("--useridlist", required=True, help="逗号分隔的 userid 列表")
    
    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "data":
        useridlist = [u.strip() for u in args.useridlist.split(",") if u.strip()]
        _pp(get_checkin_data(args.type, useridlist, args.start_time, args.end_time))
    elif act == "option":
        _pp(get_corp_checkin_option(args.datetime))
    elif act == "group":
        _pp(get_group_list())
    elif act == "add-user":
        useridlist = [u.strip() for u in args.useridlist.split(",") if u.strip()]
        _pp(add_checkin_user(args.groupid, useridlist))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.action:
        parser.print_help()
        return 1
    try:
        _run_cli(args)
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
