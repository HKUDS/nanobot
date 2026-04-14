#!/usr/bin/env python3
"""wecom_approval - 企业微信审批 API

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
# 审批 API
# ============================================================

def get_template_detail(template_id: str) -> Dict[str, Any]:
    """获取审批模板详情"""
    payload = {"template_id": template_id}
    return _post("/oa/gettemplatedetail", payload, action="获取审批模板")


def create_approval(
    creator_userid: str,
    template_id: str,
    apply_data: Dict[str, Any],
    use_template_approver: int = 1
) -> Dict[str, Any]:
    """提交审批申请
    
    use_template_approver: 1-使用模板审批流程，0-自定义
    """
    payload = {
        "creator_userid": creator_userid,
        "template_id": template_id,
        "use_template_approver": use_template_approver,
        "apply_data": apply_data
    }
    return _post("/oa/applyevent", payload, action="提交审批申请")


def get_approval_info(sp_no: str) -> Dict[str, Any]:
    """获取审批详情
    
    sp_no: 审批编号
    """
    payload = {"sp_no": sp_no}
    return _post("/oa/getapprovalinfo", payload, action="获取审批详情")


def get_approval_list(
    starttime: int,
    endtime: int,
    cursor: int = 0,
    limit: int = 100,
    filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """批量获取审批单号
    
    starttime/endtime: Unix 时间戳（秒）
    """
    payload = {
        "starttime": starttime,
        "endtime": endtime,
        "cursor": cursor,
        "limit": limit
    }
    if filters:
        payload["filters"] = filters
    return _post("/oa/getapprovallist", payload, action="获取审批列表")


def withdraw_approval(sp_no: str) -> Dict[str, Any]:
    """撤回审批申请"""
    payload = {"sp_no": sp_no}
    return _post("/oa/cancelapproval", payload, action="撤回审批申请")


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wecom_approval", description="企业微信审批")
    sub = parser.add_subparsers(dest="action")
    
    # template
    p = sub.add_parser("template", help="获取审批模板详情")
    p.add_argument("--template-id", required=True)
    
    # create
    p = sub.add_parser("create", help="提交审批申请")
    p.add_argument("--creator", required=True)
    p.add_argument("--template-id", required=True)
    p.add_argument("--apply-data", required=True, help="JSON 格式的申请数据")
    
    # get
    p = sub.add_parser("get", help="获取审批详情")
    p.add_argument("--sp-no", required=True)
    
    # list
    p = sub.add_parser("list", help="获取审批列表")
    p.add_argument("--start-time", type=int, required=True)
    p.add_argument("--end-time", type=int, required=True)
    p.add_argument("--limit", type=int, default=100)
    
    # withdraw
    p = sub.add_parser("withdraw", help="撤回审批申请")
    p.add_argument("--sp-no", required=True)
    
    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "template":
        _pp(get_template_detail(args.template_id))
    elif act == "create":
        apply_data = json.loads(args.apply_data)
        _pp(create_approval(args.creator, args.template_id, apply_data))
    elif act == "get":
        _pp(get_approval_info(args.sp_no))
    elif act == "list":
        _pp(get_approval_list(args.start_time, args.end_time, limit=args.limit))
    elif act == "withdraw":
        _pp(withdraw_approval(args.sp_no))


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
