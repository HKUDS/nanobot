#!/usr/bin/env python3
"""wecom_group - 企业微信群聊 API

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


def _get(path: str, params: Optional[dict] = None, *, timeout: int = 10, action: str = "") -> dict:
    full_params = params or {}
    full_params["access_token"] = get_access_token()
    resp = requests.get(f"{BASE_URL}{path}", params=full_params, timeout=timeout)
    return _check(resp.json(), action or path)


def _pp(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# 群聊 API
# ============================================================

def create_appchat(
    chatid: str,
    name: str,
    owner: str,
    userlist: List[str],
    notice: int = 0,
    pic_media_id: Optional[str] = None
) -> Dict[str, Any]:
    """创建应用群聊"""
    payload = {
        "chatid": chatid,
        "name": name,
        "owner": owner,
        "userlist": userlist,
        "notice": notice
    }
    if pic_media_id:
        payload["pic_media_id"] = pic_media_id
    return _post("/appchat/create", payload, action="创建群聊")


def get_appchat(chatid: str) -> Dict[str, Any]:
    """获取群聊详情"""
    params = {"chatid": chatid}
    return _get("/appchat/get", params, action="获取群聊详情")


def update_appchat(
    chatid: str,
    name: Optional[str] = None,
    owner: Optional[str] = None,
    add_user_list: Optional[List[str]] = None,
    del_user_list: Optional[List[str]] = None
) -> Dict[str, Any]:
    """修改群聊"""
    payload = {"chatid": chatid}
    if name:
        payload["name"] = name
    if owner:
        payload["owner"] = owner
    if add_user_list:
        payload["add_user_list"] = add_user_list
    if del_user_list:
        payload["del_user_list"] = del_user_list
    return _post("/appchat/update", payload, action="修改群聊")


def send_appchat_message(
    chatid: str,
    msgtype: str = "text",
    content: Optional[str] = None,
    media_id: Optional[str] = None
) -> Dict[str, Any]:
    """发送群消息"""
    payload = {"chatid": chatid, "msgtype": msgtype}
    if msgtype == "text":
        payload["text"] = {"content": content}
    elif msgtype == "image":
        payload["image"] = {"media_id": media_id}
    elif msgtype == "file":
        payload["file"] = {"media_id": media_id}
    elif msgtype == "markdown":
        payload["markdown"] = {"content": content}
    return _post("/appchat/send", payload, action="发送群消息")


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wecom_group", description="企业微信群聊")
    sub = parser.add_subparsers(dest="action")
    
    # create
    p = sub.add_parser("create", help="创建群聊")
    p.add_argument("--chatid", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--userlist", required=True, help="逗号分隔的 userid 列表")
    p.add_argument("--notice", type=int, default=0)
    
    # get
    p = sub.add_parser("get", help="获取群聊详情")
    p.add_argument("--chatid", required=True)
    
    # update
    p = sub.add_parser("update", help="修改群聊")
    p.add_argument("--chatid", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--owner", default="")
    p.add_argument("--add-users", default="", help="逗号分隔的 userid 列表")
    p.add_argument("--del-users", default="", help="逗号分隔的 userid 列表")
    
    # send
    p = sub.add_parser("send", help="发送群消息")
    p.add_argument("--chatid", required=True)
    p.add_argument("--msgtype", default="text")
    p.add_argument("--content", default="")
    p.add_argument("--media-id", default="")
    
    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "create":
        userlist = [u.strip() for u in args.userlist.split(",") if u.strip()]
        _pp(create_appchat(args.chatid, args.name, args.owner, userlist, args.notice))
    elif act == "get":
        _pp(get_appchat(args.chatid))
    elif act == "update":
        add_users = [u.strip() for u in args.add_users.split(",") if u.strip()] if args.add_users else None
        del_users = [u.strip() for u in args.del_users.split(",") if u.strip()] if args.del_users else None
        _pp(update_appchat(args.chatid, args.name or None, args.owner or None, add_users, del_users))
    elif act == "send":
        _pp(send_appchat_message(args.chatid, args.msgtype, args.content, args.media_id))


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
