#!/usr/bin/env python3
"""feishu_contact - 飞书通讯录 API

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
# 通讯录 (contact/v3)
# ============================================================

def get_user(user_id: str, user_id_type: str = "open_id") -> Dict[str, Any]:
    """获取用户信息"""
    return _get(f"/contact/v3/users/{user_id}", {"user_id_type": user_id_type},
                action="获取用户信息")


def list_department_users(
    department_id: str = "0",
    page_size: int = 50,
    page_token: str = "",
    department_id_type: str = "open_department_id",
    user_id_type: str = "open_id",
) -> Dict[str, Any]:
    """获取部门下用户列表"""
    params: Dict[str, Any] = {
        "department_id": department_id,
        "page_size": page_size,
        "department_id_type": department_id_type,
        "user_id_type": user_id_type,
    }
    if page_token:
        params["page_token"] = page_token
    return _get("/contact/v3/users/find_by_department", params, action="获取部门用户列表")


def get_department(
    department_id: str,
    department_id_type: str = "open_department_id",
) -> Dict[str, Any]:
    """获取部门信息"""
    return _get(f"/contact/v3/departments/{department_id}",
                {"department_id_type": department_id_type}, action="获取部门信息")


def list_departments(
    parent_department_id: str = "0",
    page_size: int = 50,
    page_token: str = "",
    department_id_type: str = "open_department_id",
) -> Dict[str, Any]:
    """获取子部门列表"""
    params: Dict[str, Any] = {
        "parent_department_id": parent_department_id,
        "page_size": page_size,
        "department_id_type": department_id_type,
    }
    if page_token:
        params["page_token"] = page_token
    return _get("/contact/v3/departments", params, action="获取子部门列表")


def batch_get_user_id(
    mobiles: Optional[List[str]] = None,
    emails: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """通过手机号或邮箱批量查询 open_id

    至少提供 mobiles 或 emails 其中之一。
    """
    payload: Dict[str, Any] = {}
    if mobiles:
        payload["mobiles"] = mobiles
    if emails:
        payload["emails"] = emails
    return _post("/contact/v3/users/batch_get_id",
                 payload, params={"user_id_type": "open_id"},
                 action="批量查询用户 ID")


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu_contact", description="飞书通讯录")
    sub = parser.add_subparsers(dest="action")
    p = sub.add_parser("user", help="获取用户信息")
    p.add_argument("--user-id", required=True)
    p.add_argument("--id-type", default="open_id")
    p = sub.add_parser("dept-users", help="部门用户列表")
    p.add_argument("--department-id", default="0")
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("dept", help="部门信息")
    p.add_argument("--department-id", required=True)
    p = sub.add_parser("dept-children", help="子部门列表")
    p.add_argument("--parent-id", default="0")
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("search", help="通过手机号/邮箱查 open_id")
    p.add_argument("--mobiles", default="", help="逗号分隔的手机号")
    p.add_argument("--emails", default="", help="逗号分隔的邮箱")
    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "user":
        _pp(get_user(args.user_id, args.id_type))
    elif act == "dept-users":
        _pp(list_department_users(args.department_id, page_size=args.limit))
    elif act == "dept":
        _pp(get_department(args.department_id))
    elif act == "dept-children":
        _pp(list_departments(args.parent_id, page_size=args.limit))
    elif act == "search":
        mobiles = [m.strip() for m in args.mobiles.split(",") if m.strip()] if args.mobiles else None
        emails = [e.strip() for e in args.emails.split(",") if e.strip()] if args.emails else None
        if not mobiles and not emails:
            print("错误: 请提供 --mobiles 或 --emails 至少其一", file=sys.stderr)
            return
        _pp(batch_get_user_id(mobiles, emails))


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
