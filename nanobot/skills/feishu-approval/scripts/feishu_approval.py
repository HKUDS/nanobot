#!/usr/bin/env python3
"""feishu_approval - 飞书审批 API

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
# 审批 (approval/v4)
# ============================================================

DEFAULT_APPROVAL_CODE = "E565EC28-57C7-461C-B7ED-1E2D838F4878"


LEAVE_TYPES = {
    "年假": "7138673249737506817",
    "事假": "7138673250187935772",
    "病假": "7138673250640347138",
    "调休假": "7138673251139731484",
    "婚假": "7138673251697475612",
    "产假": "7138673252143726594",
    "陪产假": "7138673252595236865",
    "丧假": "7138673253106663426",
    "哺乳假": "7138673253534695425",
}


def approval_get_definition(approval_code: str) -> Dict[str, Any]:
    """获取审批定义详情（含表单结构）"""
    return _get(f"/approval/v4/approvals/{approval_code}", action="获取审批定义")


def approval_list_instances(
    approval_code: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page_size: int = 100,
    page_token: str = "",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """批量获取审批实例 ID"""
    now_ms = str(int(_time.time() * 1000))
    thirty_days_ago_ms = str(int((_time.time() - 30 * 86400) * 1000))
    params: Dict[str, Any] = {
        "approval_code": approval_code,
        "page_size": page_size,
        "start_time": start_time or thirty_days_ago_ms,
        "end_time": end_time or now_ms,
    }
    if page_token:
        params["page_token"] = page_token
    if user_id:
        params["user_id"] = user_id
    return _get("/approval/v4/instances", params, action="获取审批实例列表")


def approval_get_instance(instance_code: str) -> Dict[str, Any]:
    """获取审批实例详情"""
    return _get(f"/approval/v4/instances/{instance_code}", action="获取审批实例详情")


def approval_create_instance(
    approval_code: str,
    user_id: str,
    form: str,
) -> Dict[str, Any]:
    """创建审批实例"""
    return _post("/approval/v4/instances",
                 {"approval_code": approval_code, "open_id": user_id, "form": form},
                 action="创建审批实例")


def approval_cancel_instance(
    approval_code: str,
    instance_code: str,
    user_id: str,
    reason: str = "",
) -> Dict[str, Any]:
    """撤回审批实例"""
    payload: Dict[str, Any] = {
        "approval_code": approval_code,
        "instance_code": instance_code,
        "user_id": user_id,
    }
    if reason:
        payload["reason"] = reason
    return _post("/approval/v4/instances/cancel", payload,
                 params={"user_id_type": "open_id"}, action="撤回审批实例")


def approval_approve_task(
    approval_code: str,
    instance_code: str,
    task_id: str,
    user_id: str,
    comment: str = "",
) -> Dict[str, Any]:
    """审批任务同意"""
    payload: Dict[str, Any] = {
        "approval_code": approval_code,
        "instance_code": instance_code,
        "task_id": task_id,
        "user_id": user_id,
    }
    if comment:
        payload["comment"] = comment
    return _post("/approval/v4/tasks/approve", payload,
                 params={"user_id_type": "open_id"}, action="审批同意")


def approval_reject_task(
    approval_code: str,
    instance_code: str,
    task_id: str,
    user_id: str,
    comment: str = "",
) -> Dict[str, Any]:
    """审批任务拒绝"""
    payload: Dict[str, Any] = {
        "approval_code": approval_code,
        "instance_code": instance_code,
        "task_id": task_id,
        "user_id": user_id,
    }
    if comment:
        payload["comment"] = comment
    return _post("/approval/v4/tasks/reject", payload,
                 params={"user_id_type": "open_id"}, action="审批拒绝")


def approval_transfer_task(
    approval_code: str,
    instance_code: str,
    task_id: str,
    user_id: str,
    transfer_user_id: str,
    comment: str = "",
) -> Dict[str, Any]:
    """审批任务转交"""
    payload: Dict[str, Any] = {
        "approval_code": approval_code,
        "instance_code": instance_code,
        "task_id": task_id,
        "user_id": user_id,
        "transfer_user_id": transfer_user_id,
    }
    if comment:
        payload["comment"] = comment
    return _post("/approval/v4/tasks/transfer", payload,
                 params={"user_id_type": "open_id"}, action="审批转交")


def approval_list_comments(
    instance_id: str,
    user_id: str,
    user_id_type: str = "open_id",
    page_size: int = 50,
) -> Dict[str, Any]:
    """获取审批实例评论（需指定查询用户）"""
    return _get(f"/approval/v4/instances/{instance_id}/comments",
                {"user_id": user_id, "user_id_type": user_id_type, "page_size": page_size},
                action="获取审批评论")


def create_leave_approval(
    approval_code: str,
    user_id: str,
    leave_type: str,
    start_time: str,
    end_time: str,
    reason: str,
    unit: str = "DAY",
    interval: str = "1",
) -> Dict[str, Any]:
    """创建请假审批实例（便捷函数）"""
    leave_id = LEAVE_TYPES.get(leave_type, leave_type)
    form_array = [
        {
            "id": "widgetLeaveGroupV2",
            "type": "leaveGroupV2",
            "value": [
                {"id": "widgetLeaveGroupType", "type": "radioV2", "value": leave_id},
                {"id": "widgetLeaveGroupStartTime", "type": "date", "value": start_time},
                {"id": "widgetLeaveGroupEndTime", "type": "date", "value": end_time},
                {"id": "widgetLeaveGroupInterval", "type": "radioV2", "value": interval},
                {"id": "widgetLeaveGroupReason", "type": "textarea", "value": reason},
                {"id": "widgetLeaveGroupUnit", "type": "radioV2", "value": unit},
            ],
        }
    ]
    return approval_create_instance(approval_code, user_id,
                                    json.dumps(form_array, ensure_ascii=False))


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu_approval", description="飞书审批")
    sub = parser.add_subparsers(dest="action")

    p = sub.add_parser("definition", help="获取审批定义")
    p.add_argument("--code", required=True)

    p = sub.add_parser("list", help="列出实例")
    p.add_argument("--code", required=True)
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("get", help="获取实例详情")
    p.add_argument("--instance-code", required=True)

    p = sub.add_parser("comments", help="获取实例评论")
    p.add_argument("--instance-code", required=True)
    p.add_argument("--user-id", required=True, help="查询用户 open_id")

    p = sub.add_parser("create", help="创建实例")
    p.add_argument("--code", required=True)
    p.add_argument("--user-id", required=True)
    p.add_argument("--form", required=True, help="表单 JSON")

    p = sub.add_parser("cancel", help="撤回实例")
    p.add_argument("--code", required=True)
    p.add_argument("--instance-code", required=True)
    p.add_argument("--user-id", required=True)

    p = sub.add_parser("approve", help="审批同意")
    p.add_argument("--code", required=True)
    p.add_argument("--instance-code", required=True)
    p.add_argument("--user-id", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--comment", default="")

    p = sub.add_parser("reject", help="审批拒绝")
    p.add_argument("--code", required=True)
    p.add_argument("--instance-code", required=True)
    p.add_argument("--user-id", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--comment", default="")

    p = sub.add_parser("transfer", help="审批转交")
    p.add_argument("--code", required=True)
    p.add_argument("--instance-code", required=True)
    p.add_argument("--user-id", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--target-user-id", required=True)
    p.add_argument("--comment", default="")

    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "definition":
        _pp(approval_get_definition(args.code))
    elif act == "list":
        _pp(approval_list_instances(args.code, page_size=args.limit))
    elif act == "get":
        _pp(approval_get_instance(args.instance_code))
    elif act == "comments":
        _pp(approval_list_comments(args.instance_code, args.user_id))
    elif act == "create":
        _pp(approval_create_instance(args.code, args.user_id, args.form))
    elif act == "cancel":
        _pp(approval_cancel_instance(args.code, args.instance_code, args.user_id))
    elif act == "approve":
        _pp(approval_approve_task(args.code, args.instance_code, args.user_id,
                                  args.task_id, args.comment))
    elif act == "reject":
        _pp(approval_reject_task(args.code, args.instance_code, args.user_id,
                                 args.task_id, args.comment))
    elif act == "transfer":
        _pp(approval_transfer_task(args.code, args.instance_code, args.user_id,
                                   args.task_id, args.target_user_id, args.comment))


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
