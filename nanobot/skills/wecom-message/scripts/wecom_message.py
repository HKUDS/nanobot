#!/usr/bin/env python3
"""wecom_message - 企业微信消息收发 API

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
                    "corp_secret": wecom.get("corp_secret"),
                    "agent_id": str(wecom.get("agent_id", ""))
                }
    except Exception:
        pass
    return {}


_nanobot_cfg = _load_nanobot_config()
CORP_ID = _nanobot_cfg.get("corp_id") or os.environ.get("NANOBOT_CHANNELS__WECOM__CORP_ID", "")
CORP_SECRET = _nanobot_cfg.get("corp_secret") or os.environ.get("NANOBOT_CHANNELS__WECOM__CORP_SECRET", "")
AGENT_ID = _nanobot_cfg.get("agent_id") or os.environ.get("NANOBOT_CHANNELS__WECOM__AGENT_ID", "")

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


def _post(path: str, payload: Optional[dict] = None, *, timeout: int = 10, action: str = "") -> dict:
    url = f"{BASE_URL}{path}"
    params = {"access_token": get_access_token()}
    resp = requests.post(url, params=params, json=payload, timeout=timeout)
    return _check(resp.json(), action or path)


def _pp(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# 消息 API
# ============================================================

def send_text_message(
    touser: str,
    content: str,
    agent_id: Optional[str] = None,
    safe: int = 0
) -> Dict[str, Any]:
    """发送文本消息"""
    aid = agent_id or AGENT_ID
    if not aid:
        raise RuntimeError("缺少 agent_id 配置")
    payload = {
        "touser": touser,
        "msgtype": "text",
        "agentid": int(aid),
        "text": {"content": content},
        "safe": safe
    }
    return _post("/message/send", payload, action="发送文本消息")


def send_image_message(
    touser: str,
    media_id: str,
    agent_id: Optional[str] = None
) -> Dict[str, Any]:
    """发送图片消息"""
    payload = {
        "touser": touser,
        "msgtype": "image",
        "agentid": int(agent_id or AGENT_ID),
        "image": {"media_id": media_id}
    }
    return _post("/message/send", payload, action="发送图片消息")


def send_file_message(
    touser: str,
    media_id: str,
    agent_id: Optional[str] = None
) -> Dict[str, Any]:
    """发送文件消息"""
    payload = {
        "touser": touser,
        "msgtype": "file",
        "agentid": int(agent_id or AGENT_ID),
        "file": {"media_id": media_id}
    }
    return _post("/message/send", payload, action="发送文件消息")


def send_voice_message(
    touser: str,
    media_id: str,
    agent_id: Optional[str] = None
) -> Dict[str, Any]:
    """发送语音消息"""
    payload = {
        "touser": touser,
        "msgtype": "voice",
        "agentid": int(agent_id or AGENT_ID),
        "voice": {"media_id": media_id}
    }
    return _post("/message/send", payload, action="发送语音消息")


def send_news_message(
    touser: str,
    articles: List[Dict[str, str]],
    agent_id: Optional[str] = None
) -> Dict[str, Any]:
    """发送图文消息"""
    payload = {
        "touser": touser,
        "msgtype": "news",
        "agentid": int(agent_id or AGENT_ID),
        "news": {"articles": articles}
    }
    return _post("/message/send", payload, action="发送图文消息")


def send_markdown_message(
    touser: str,
    content: str,
    agent_id: Optional[str] = None
) -> Dict[str, Any]:
    """发送 Markdown 消息"""
    payload = {
        "touser": touser,
        "msgtype": "markdown",
        "agentid": int(agent_id or AGENT_ID),
        "markdown": {"content": content}
    }
    return _post("/message/send", payload, action="发送 Markdown 消息")


def upload_media(
    file_path: str,
    type: str = "file"
) -> Dict[str, Any]:
    """上传媒体文件（图片/文件/语音）
    
    type: image, file, voice
    """
    url = f"{BASE_URL}/media/upload"
    params = {
        "access_token": get_access_token(),
        "type": type
    }
    
    with open(file_path, "rb") as f:
        files = {"media": f}
        resp = requests.post(url, params=params, files=files, timeout=30)
    
    return _check(resp.json(), "上传媒体文件")


def recall_message(
    msgid: str
) -> Dict[str, Any]:
    """撤回消息"""
    payload = {"msgid": msgid}
    return _post("/message/recall", payload, action="撤回消息")


# ============================================================
# 群聊消息 API
# ============================================================

def send_group_chat_message(
    chatid: str,
    msgtype: str = "text",
    content: Optional[str] = None,
    media_id: Optional[str] = None,
    articles: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """发送群消息"""
    payload = {"chatid": chatid, "msgtype": msgtype}
    
    if msgtype == "text":
        payload["text"] = {"content": content}
    elif msgtype == "image":
        payload["image"] = {"media_id": media_id}
    elif msgtype == "file":
        payload["file"] = {"media_id": media_id}
    elif msgtype == "news":
        payload["news"] = {"articles": articles}
    
    return _post("/appchat/send", payload, action="发送群消息")


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wecom_message", description="企业微信消息收发")
    sub = parser.add_subparsers(dest="action")
    
    # send-text
    p = sub.add_parser("send-text", help="发送文本消息")
    p.add_argument("--touser", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--agent-id", default="")
    
    # send-image
    p = sub.add_parser("send-image", help="发送图片消息")
    p.add_argument("--touser", required=True)
    p.add_argument("--media-id", required=True)
    p.add_argument("--agent-id", default="")
    
    # send-file
    p = sub.add_parser("send-file", help="发送文件消息")
    p.add_argument("--touser", required=True)
    p.add_argument("--media-id", required=True)
    p.add_argument("--agent-id", default="")
    
    # send-markdown
    p = sub.add_parser("send-markdown", help="发送 Markdown 消息")
    p.add_argument("--touser", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--agent-id", default="")
    
    # upload
    p = sub.add_parser("upload", help="上传媒体文件")
    p.add_argument("--file", required=True)
    p.add_argument("--type", default="file", choices=["image", "file", "voice"])
    
    # recall
    p = sub.add_parser("recall", help="撤回消息")
    p.add_argument("--msgid", required=True)
    
    # group-send
    p = sub.add_parser("group-send", help="发送群消息")
    p.add_argument("--chatid", required=True)
    p.add_argument("--msgtype", default="text")
    p.add_argument("--content", default="")
    p.add_argument("--media-id", default="")
    
    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "send-text":
        _pp(send_text_message(args.touser, args.content, args.agent_id))
    elif act == "send-image":
        _pp(send_image_message(args.touser, args.media_id, args.agent_id))
    elif act == "send-file":
        _pp(send_file_message(args.touser, args.media_id, args.agent_id))
    elif act == "send-markdown":
        _pp(send_markdown_message(args.touser, args.content, args.agent_id))
    elif act == "upload":
        _pp(upload_media(args.file, args.type))
    elif act == "recall":
        _pp(recall_message(args.msgid))
    elif act == "group-send":
        _pp(send_group_chat_message(args.chatid, args.msgtype, args.content, args.media_id))


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
