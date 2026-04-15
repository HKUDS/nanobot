#!/usr/bin/env python3
"""wecom_contact - 企业微信通讯录 API

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
        raise RuntimeError(
            "缺少企业微信凭据，请配置 ~/.hiperone/config.json 或设置环境变量 "
            "NANOBOT_CHANNELS__WECOM__CORP_ID / NANOBOT_CHANNELS__WECOM__CORP_SECRET"
        )
    now = _time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]
    
    url = f"{BASE_URL}/gettoken"
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


def _get(path: str, params: Optional[dict] = None, *, timeout: int = 10, action: str = "") -> dict:
    full_params = params or {}
    full_params["access_token"] = get_access_token()
    resp = requests.get(f"{BASE_URL}{path}", params=full_params, timeout=timeout)
    return _check(resp.json(), action or path)


def _post(path: str, payload: Optional[dict] = None, *, timeout: int = 10, action: str = "") -> dict:
    url = f"{BASE_URL}{path}"
    params = {"access_token": get_access_token()}
    resp = requests.post(url, params=params, json=payload, timeout=timeout)
    return _check(resp.json(), action or path)


def _pp(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# 通讯录 API
# ============================================================

def get_user(userid: str) -> Dict[str, Any]:
    """获取用户信息"""
    return _get("/user/get", {"userid": userid}, action="获取用户信息")


def list_department_users(
    department_id: int = 1,
    fetch_child: int = 1,
) -> Dict[str, Any]:
    """获取部门下用户列表"""
    return _get("/user/list", {
        "department_id": department_id,
        "fetch_child": fetch_child
    }, action="获取部门用户列表")


def get_department(department_id: int) -> Dict[str, Any]:
    """获取部门信息"""
    return _get("/department/get", {"id": department_id}, action="获取部门信息")


def list_departments(parent_id: int = 1) -> Dict[str, Any]:
    """获取子部门列表"""
    return _get("/department/list", {"id": parent_id}, action="获取子部门列表")


def search_by_mobile(mobile: str) -> Dict[str, Any]:
    """通过手机号查询用户"""
    # 企业微信没有直接的手机号查询 API，需要先获取部门用户列表再筛选
    # 这里使用一个变通方法：尝试常见 userid 格式
    # 实际使用中建议管理员提供 userid 映射表
    result = {"errcode": 404, "errmsg": "手机号查询需要管理员配置映射关系"}
    return result


def search_by_email(email: str) -> Dict[str, Any]:
    """通过邮箱查询用户"""
    # 类似手机号查询，需要遍历用户列表
    result = {"errcode": 404, "errmsg": "邮箱查询需要管理员配置映射关系"}
    return result


def search_user(mobile: Optional[str] = None, email: Optional[str] = None) -> Dict[str, Any]:
    """搜索用户（通过手机号或邮箱）
    
    注意：企业微信 API 不直接支持手机号/邮箱查询，
    需要先获取用户列表再本地筛选。
    """
    if not mobile and not email:
        return {"errcode": 400, "errmsg": "请提供 mobile 或 email 至少其一"}
    
    # 获取所有用户（根部门 + 子部门）
    users_data = list_department_users(department_id=1, fetch_child=1)
    user_list = users_data.get("userlist", [])
    
    # 本地筛选
    for user in user_list:
        if mobile and user.get("mobile") == mobile:
            return {"errcode": 0, "errmsg": "ok", "user": user}
        if email and user.get("email") == email:
            return {"errcode": 0, "errmsg": "ok", "user": user}
    
    return {"errcode": 404, "errmsg": "未找到匹配的用户"}


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wecom_contact", description="企业微信通讯录")
    sub = parser.add_subparsers(dest="action")
    
    p = sub.add_parser("user", help="获取用户信息")
    p.add_argument("--userid", required=True)
    
    p = sub.add_parser("dept-users", help="部门用户列表")
    p.add_argument("--department-id", type=int, default=1)
    p.add_argument("--fetch-child", type=int, default=1)
    
    p = sub.add_parser("dept", help="部门信息")
    p.add_argument("--department-id", type=int, required=True)
    
    p = sub.add_parser("dept-children", help="子部门列表")
    p.add_argument("--parent-id", type=int, default=1)
    
    p = sub.add_parser("search", help="通过手机号/邮箱查 userid")
    p.add_argument("--mobile", default="", help="手机号")
    p.add_argument("--email", default="", help="邮箱")
    
    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "user":
        _pp(get_user(args.userid))
    elif act == "dept-users":
        _pp(list_department_users(args.department_id, args.fetch_child))
    elif act == "dept":
        _pp(get_department(args.department_id))
    elif act == "dept-children":
        _pp(list_departments(args.parent_id))
    elif act == "search":
        _pp(search_user(
            mobile=args.mobile if args.mobile else None,
            email=args.email if args.email else None
        ))


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
