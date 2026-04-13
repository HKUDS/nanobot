#!/usr/bin/env python3
"""feishu_task - 飞书任务管理 API

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


def _patch(path: str, payload: Optional[dict] = None, *, params: Optional[dict] = None,
           timeout: int = 10, action: str = "") -> dict:
    resp = requests.patch(f"{BASE_URL}{path}", headers=_headers(), json=payload,
                          params=params, timeout=timeout)
    return _check(resp.json(), action or path)


def _pp(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# 任务管理 (task/v1) — v1 全面支持 tenant_access_token
# ============================================================

_TASK_PARAMS = {"user_id_type": "open_id"}


_TASK_ORIGIN = {
    "platform_i18n_name": '{"zh_cn": "NanoBot", "en_us": "NanoBot"}',
    "href": {"url": "https://github.com", "title": "NanoBot"},
}


def task_create(
    summary: str,
    description: str = "",
    due: Optional[Dict] = None,
    collaborator_ids: Optional[List[str]] = None,
    follower_ids: Optional[List[str]] = None,
    origin: Optional[Dict] = None,
) -> Dict[str, Any]:
    """创建任务"""
    task: Dict[str, Any] = {"summary": summary, "origin": origin or _TASK_ORIGIN}
    if description:
        task["description"] = description
    if due:
        task["due"] = due
    if collaborator_ids:
        task["collaborator_ids"] = collaborator_ids
    if follower_ids:
        task["follower_ids"] = follower_ids
    return _post("/task/v1/tasks", task, params=_TASK_PARAMS, action="创建任务")


def task_get(task_id: str) -> Dict[str, Any]:
    """获取任务详情"""
    return _get(f"/task/v1/tasks/{task_id}", _TASK_PARAMS, action="获取任务详情")


def task_list(
    page_size: int = 50,
    page_token: str = "",
    completed: Optional[bool] = None,
) -> Dict[str, Any]:
    """获取任务列表"""
    params: Dict[str, Any] = {"page_size": page_size, **_TASK_PARAMS}
    if page_token:
        params["page_token"] = page_token
    if completed is not None:
        params["task_completed"] = str(completed).lower()
    return _get("/task/v1/tasks", params, action="获取任务列表")


def task_update(task_id: str, fields: dict) -> Dict[str, Any]:
    """更新任务（PATCH 语义，只更新传入的字段）"""
    update_fields = list(fields.keys())
    return _patch(f"/task/v1/tasks/{task_id}",
                  {"task": fields, "update_fields": update_fields},
                  params=_TASK_PARAMS, action="更新任务")


def task_complete(task_id: str) -> Dict[str, Any]:
    """完成任务"""
    return _post(f"/task/v1/tasks/{task_id}/complete", params=_TASK_PARAMS,
                 action="完成任务")


def tasklist_create(name: str) -> Dict[str, Any]:
    """创建任务清单"""
    return _post("/task/v2/tasklists", {"name": name}, action="创建任务清单")


def tasklist_list(page_size: int = 50, page_token: str = "") -> Dict[str, Any]:
    """获取任务清单列表"""
    params: Dict[str, Any] = {"page_size": page_size}
    if page_token:
        params["page_token"] = page_token
    return _get("/task/v2/tasklists", params, action="获取任务清单列表")


def tasklist_add_task(task_id: str, tasklist_id: str) -> Dict[str, Any]:
    """将任务添加到清单"""
    return _post(f"/task/v2/tasks/{task_id}/add_tasklist",
                 {"tasklist_guid": tasklist_id},
                 action="添加任务到清单")


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu_task", description="飞书任务管理")
    sub = parser.add_subparsers(dest="action")

    p = sub.add_parser("list", help="列出任务")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("get", help="获取任务")
    p.add_argument("--task-id", required=True)

    p = sub.add_parser("create", help="创建任务")
    p.add_argument("--summary", required=True)
    p.add_argument("--description", default="")

    p = sub.add_parser("update", help="更新任务")
    p.add_argument("--task-id", required=True)
    p.add_argument("--summary", default="", help="新标题")
    p.add_argument("--description", default="", help="新描述")

    p = sub.add_parser("complete", help="完成任务")
    p.add_argument("--task-id", required=True)

    p = sub.add_parser("tasklist-create", help="创建任务清单")
    p.add_argument("--name", required=True)

    p = sub.add_parser("tasklist-list", help="列出任务清单")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("tasklist-add", help="将任务添加到清单")
    p.add_argument("--task-id", required=True)
    p.add_argument("--tasklist-id", required=True)

    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "list":
        _pp(task_list(args.limit))
    elif act == "get":
        _pp(task_get(args.task_id))
    elif act == "create":
        _pp(task_create(args.summary, args.description))
    elif act == "update":
        fields = {}
        if args.summary:
            fields["summary"] = args.summary
        if args.description:
            fields["description"] = args.description
        if not fields:
            print("错误: 至少提供 --summary 或 --description", file=sys.stderr)
            return
        _pp(task_update(args.task_id, fields))
    elif act == "complete":
        _pp(task_complete(args.task_id))
    elif act == "tasklist-create":
        _pp(tasklist_create(args.name))
    elif act == "tasklist-list":
        _pp(tasklist_list(args.limit))
    elif act == "tasklist-add":
        _pp(tasklist_add_task(args.task_id, args.tasklist_id))


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
