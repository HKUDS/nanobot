#!/usr/bin/env python3
"""
feishu_api - 飞书统一 API 客户端

合并群组、消息、通讯录、考勤、云文档、多维表格、审批、日历、任务、知识库、
云空间、百科、人事等模块，消除重复的凭据加载和 token 获取逻辑。

凭据获取优先级: ~/.hiperone/config.json > 环境变量
"""

import argparse
import json
import os
import sys
import time as _time
import requests
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


BASE_URL = "https://open.feishu.cn/open-apis"


# ============================================================
# 凭据加载 & 通用工具
# ============================================================

def _load_nanobot_config() -> Dict[str, str]:
    """从 nanobot config.json 读取飞书配置"""
    config_path = os.path.expanduser("~/.hiperone/config.json")
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
            feishu = config.get("channels", {}).get("feishu", {})
            if feishu.get("enabled"):
                return {
                    "appId": feishu.get("appId"),
                    "appSecret": feishu.get("appSecret"),
                }
    except Exception:
        pass
    return {}


_nanobot_cfg = _load_nanobot_config()
APP_ID = _nanobot_cfg.get("appId") or os.environ.get("NANOBOT_CHANNELS__FEISHU__APP_ID", "")
APP_SECRET = _nanobot_cfg.get("appSecret") or os.environ.get("NANOBOT_CHANNELS__FEISHU__APP_SECRET", "")

_token_cache: Dict[str, Any] = {"token": "", "expires": 0}


def get_tenant_access_token() -> str:
    """获取 tenant_access_token（带缓存，有效期内不重复请求）"""
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


def _patch(path: str, payload: Optional[dict] = None, *, params: Optional[dict] = None,
           timeout: int = 10, action: str = "") -> dict:
    resp = requests.patch(f"{BASE_URL}{path}", headers=_headers(), json=payload,
                          params=params, timeout=timeout)
    return _check(resp.json(), action or path)


def _delete(path: str, *, timeout: int = 10, action: str = "") -> dict:
    resp = requests.delete(f"{BASE_URL}{path}", headers=_headers(), timeout=timeout)
    return _check(resp.json(), action or path)


def _pp(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# 群组管理 (im/v1/chats)
# ============================================================

def list_chats(page_size: int = 20, page_token: str = "") -> Dict[str, Any]:
    """获取机器人所在的群列表"""
    params: Dict[str, Any] = {"page_size": page_size}
    if page_token:
        params["page_token"] = page_token
    return _get("/im/v1/chats", params, action="获取群列表")


def get_chat(chat_id: str) -> Dict[str, Any]:
    """获取群信息"""
    return _get(f"/im/v1/chats/{chat_id}", action="获取群信息")


def get_chat_members(
    chat_id: str,
    member_id_type: str = "open_id",
    page_size: int = 100,
    page_token: str = "",
) -> Dict[str, Any]:
    """获取群成员列表（单页）"""
    params: Dict[str, Any] = {"member_id_type": member_id_type, "page_size": page_size}
    if page_token:
        params["page_token"] = page_token
    return _get(f"/im/v1/chats/{chat_id}/members", params, action="获取群成员列表")


def get_chat_members_all(chat_id: str, member_id_type: str = "open_id") -> List[Dict]:
    """获取群全部成员（自动分页）"""
    members: List[Dict] = []
    page_token = ""
    while True:
        data = get_chat_members(chat_id, member_id_type, page_size=100, page_token=page_token)
        members.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    return members


# ============================================================
# 消息 (im/v1/messages)
# ============================================================

def get_chat_history(
    chat_id: str,
    start_time: str = "",
    end_time: str = "",
    page_size: int = 20,
    page_token: str = "",
) -> Dict[str, Any]:
    """获取会话历史消息"""
    params: Dict[str, Any] = {
        "container_id_type": "chat",
        "container_id": chat_id,
        "page_size": min(page_size, 50),
    }
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    if page_token:
        params["page_token"] = page_token
    return _get("/im/v1/messages", params, action="获取会话历史消息")


def send_message(
    receive_id: str,
    msg_type: str,
    content: str,
    receive_id_type: str = "chat_id",
) -> Dict[str, Any]:
    """发送消息"""
    payload = {"receive_id": receive_id, "msg_type": msg_type, "content": content}
    return _post("/im/v1/messages", payload, params={"receive_id_type": receive_id_type},
                 action="发送消息")


def send_text(receive_id: str, text: str, receive_id_type: str = "chat_id") -> Dict[str, Any]:
    """发送文本消息（便捷函数）"""
    return send_message(receive_id, "text", json.dumps({"text": text}), receive_id_type)


def reply_message(message_id: str, msg_type: str, content: str) -> Dict[str, Any]:
    """回复消息"""
    return _post(f"/im/v1/messages/{message_id}/reply",
                 {"msg_type": msg_type, "content": content}, action="回复消息")


def get_message(message_id: str) -> Dict[str, Any]:
    """获取单条消息"""
    return _get(f"/im/v1/messages/{message_id}", action="获取消息")


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


# ============================================================
# 考勤 (attendance/v1)
# ============================================================

def get_user_employee_id(open_id: str) -> str:
    """通过 open_id 获取 employee_id（考勤 API 前置步骤）"""
    data = get_user(open_id, user_id_type="open_id")
    user = data.get("user", {})
    eid = user.get("employee_id")
    if not eid:
        raise RuntimeError(f"用户 {open_id} 没有 employee_id（需权限 contact:user.employee_id:readonly）")
    return eid


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
# 云文档 (docx/v1, drive/v1)
# ============================================================

def list_files(parent_node: str = "", page_size: int = 20) -> List[Dict]:
    """获取云文档文件列表"""
    params: Dict[str, Any] = {"page_size": page_size}
    if parent_node:
        params["parent_node"] = parent_node
    data = _get("/drive/v1/files", params, action="获取文件列表")
    return data.get("files", [])


def read_doc(document_id: str) -> str:
    """读取云文档内容，返回 Markdown 格式纯文本"""
    params: Dict[str, Any] = {"page_size": 100}
    all_blocks: List[Dict] = []
    while True:
        data = _get(f"/docx/v1/documents/{document_id}/blocks", params, timeout=15,
                     action="获取文档内容")
        all_blocks.extend(data.get("items", []))
        page_token = data.get("page_token")
        if not page_token:
            break
        params = {"page_size": 100, "page_token": page_token}
    return _extract_text_from_blocks(all_blocks)


def search_docs(keyword: str, page_size: int = 10) -> List[Dict]:
    """搜索云文档（使用 suite 搜索 API）"""
    payload = {"search_key": keyword, "count": page_size, "offset": 0, "docs_types": []}
    data = _post("/suite/docs-api/search/object", payload, action="搜索文档")
    return data.get("docs_entities", [])


_BLOCK_TYPE_KEY = {
    2: "paragraph", 3: "heading1", 4: "heading2", 5: "heading3",
    7: "bulleted_list_item", 8: "numbered_list_item", 11: "quote",
}
_BLOCK_TYPE_PREFIX = {3: "## ", 4: "### ", 5: "#### ", 7: "- ", 8: "1. "}


def _extract_text_from_elements(elements: list) -> str:
    parts = []
    for elem in elements:
        if "text_run" in elem:
            parts.append(elem["text_run"].get("content", ""))
        elif "text" in elem:
            parts.append(elem["text"].get("content", ""))
    return "".join(parts)


def _extract_text_from_blocks(blocks: list) -> str:
    text_parts = []
    for block in blocks:
        bt = block.get("block_type")
        if bt == 1:
            continue
        if bt == 10:
            text_parts.append("```\n" + block.get("code", {}).get("content", "") + "\n```")
            continue
        key = _BLOCK_TYPE_KEY.get(bt)
        if not key:
            continue
        elements = block.get(key, {}).get("elements", [])
        text = _extract_text_from_elements(elements)
        if bt == 11:
            text = "\n".join("> " + line for line in text.split("\n"))
        else:
            text = _BLOCK_TYPE_PREFIX.get(bt, "") + text
        if text:
            text_parts.append(text)
    return "\n".join(text_parts)


# ============================================================
# 多维表格 (bitable/v1)
# ============================================================

def bitable_get_fields(app_token: str, table_id: str) -> Dict[str, Any]:
    """获取多维表格字段定义"""
    return _get(f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
                action="获取表字段定义")


def bitable_list_records(
    app_token: str,
    table_id: str,
    page_size: int = 20,
    filter_expr: Optional[str] = None,
    page_token: str = "",
) -> Dict[str, Any]:
    """查询多维表格记录"""
    params: Dict[str, Any] = {"page_size": page_size}
    if filter_expr:
        params["filter"] = filter_expr
    if page_token:
        params["page_token"] = page_token
    return _get(f"/bitable/v1/apps/{app_token}/tables/{table_id}/records", params,
                action="查询多维表格记录")


def bitable_add_record(app_token: str, table_id: str, fields: dict) -> Dict[str, Any]:
    """创建多维表格记录"""
    return _post(f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                 {"fields": fields}, action="创建多维表格记录")


def bitable_update_record(
    app_token: str, table_id: str, record_id: str, fields: dict,
) -> Dict[str, Any]:
    """更新多维表格记录"""
    return _put(f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
                {"fields": fields}, action="更新多维表格记录")


def bitable_delete_record(app_token: str, table_id: str, record_id: str) -> Dict[str, Any]:
    """删除多维表格记录"""
    return _delete(f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
                   action="删除多维表格记录")


def bitable_list_tables(app_token: str, page_size: int = 20) -> Dict[str, Any]:
    """获取多维表格中的数据表列表"""
    return _get(f"/bitable/v1/apps/{app_token}/tables", {"page_size": page_size},
                action="获取数据表列表")


# --- 多维表格预置常量（团队表格） ---
BITABLE_APP_TOKEN = "JXdtbkkchaSXmksx6eFc2Eatn45"
DAILY_TABLE_ID = "tblYWOnDxGsVSfDN"
TASK_TABLE_ID = "tblH6xn2dp6E1UtD"
PROJECT_TABLE_ID = "tblihZwJnOg84PUQ"


def bitable_add_daily_report(
    user_id: str, date: str, project: str, content: str, hours: float,
    app_token: str = BITABLE_APP_TOKEN,
) -> Dict[str, Any]:
    """录入日报"""
    fields = {
        "姓名": [{"id": user_id}],
        "日期": date,
        "项目": project,
        "工作内容": content,
        "时长": str(hours),
    }
    return bitable_add_record(app_token, DAILY_TABLE_ID, fields)


def bitable_query_daily_reports(
    page_size: int = 20, app_token: str = BITABLE_APP_TOKEN,
) -> Dict[str, Any]:
    """查询日报记录"""
    return bitable_list_records(app_token, DAILY_TABLE_ID, page_size=page_size)


def bitable_add_task(
    task_name: str,
    serial_number: int,
    project_record_id: str,
    executor_id: str,
    status: str = "进行中",
    deadline_days: int = 7,
    estimated_hours: int = 2,
    description: str = "",
    table_id: str = TASK_TABLE_ID,
    app_token: str = BITABLE_APP_TOKEN,
) -> Dict[str, Any]:
    """录入任务（自动检测状态字段类型）"""
    fields_info = bitable_get_fields(app_token, table_id)
    status_field_type = None
    for f in fields_info.get("items", []):
        if f.get("field_name") == "状态":
            status_field_type = f.get("type")
            break
    status_value: Any = [status] if status_field_type == 4 else status
    deadline = int((datetime.now() + timedelta(days=deadline_days)).timestamp() * 1000)
    fields = {
        "任务名称": task_name,
        "序号": serial_number,
        "所属项目": [project_record_id],
        "执行人": [{"id": executor_id}],
        "状态": status_value,
        "计划截止时间": deadline,
        "预计耗时": estimated_hours,
        "说明": description,
    }
    return bitable_add_record(app_token, table_id, fields)


def bitable_query_tasks(
    page_size: int = 20,
    table_id: str = TASK_TABLE_ID,
    app_token: str = BITABLE_APP_TOKEN,
) -> Dict[str, Any]:
    """查询任务记录"""
    return bitable_list_records(app_token, table_id, page_size=page_size)


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
    """创建审批实例

    Args:
        approval_code: 审批定义 code
        user_id: 申请人 open_id
        form: 表单 JSON 字符串
    """
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


def approval_list_comments(instance_id: str, page_size: int = 50) -> Dict[str, Any]:
    """获取审批实例评论"""
    return _get(f"/approval/v4/instances/{instance_id}/comments",
                {"page_size": page_size}, action="获取审批评论")


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
    """获取日程列表

    Args:
        calendar_id: 日历 ID（可用 "primary" 表示主日历）
        start_time: RFC3339 格式，如 "2026-03-12T00:00:00+08:00"
        end_time: RFC3339 格式
    """
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
    """创建日程

    Args:
        calendar_id: 日历 ID（"primary" 表示主日历）
        summary: 日程标题
        start_time: RFC3339 格式
        end_time: RFC3339 格式
        attendees: [{"type": "user", "user_id": "ou_xxx"}]
    """
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
    return _put(f"/calendar/v4/calendars/{calendar_id}/events/{event_id}",
                fields, action="更新日程")


def calendar_delete_event(calendar_id: str, event_id: str) -> Dict[str, Any]:
    """删除日程"""
    return _delete(f"/calendar/v4/calendars/{calendar_id}/events/{event_id}",
                   action="删除日程")


def calendar_freebusy(
    user_ids: List[str],
    start_time: str,
    end_time: str,
    user_id_type: str = "open_id",
) -> Dict[str, Any]:
    """查询忙闲信息

    Args:
        user_ids: 用户 ID 列表
        start_time: RFC3339
        end_time: RFC3339
    """
    return _post("/calendar/v4/freebusy/list", {
        "time_min": start_time,
        "time_max": end_time,
        "user_id": user_ids[0] if len(user_ids) == 1 else None,
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
    end_time: str,
    meeting_settings: Optional[dict] = None,
) -> Dict[str, Any]:
    """预约会议"""
    payload: Dict[str, Any] = {"end_time": end_time}
    if meeting_settings:
        payload["meeting_settings"] = meeting_settings
    return _post("/vc/v1/reserves/apply", payload, action="预约会议")


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
    """创建任务

    Args:
        summary: 任务标题
        description: 任务描述
        due: {"time": "1710000000", "timezone": "Asia/Shanghai"}
        collaborator_ids: 执行者 open_id 列表
        follower_ids: 关注者 open_id 列表
        origin: 来源平台信息（v1 必填，不传则使用默认值）
    """
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
    """获取任务列表

    使用 tenant_access_token 时，返回该应用通过 task_create 创建的所有任务。
    """
    params: Dict[str, Any] = {"page_size": page_size, **_TASK_PARAMS}
    if page_token:
        params["page_token"] = page_token
    if completed is not None:
        params["task_completed"] = str(completed).lower()
    return _get("/task/v1/tasks", params, action="获取任务列表")


def task_update(task_id: str, fields: dict) -> Dict[str, Any]:
    """更新任务（PATCH 语义，只更新传入的字段）

    Args:
        task_id: 任务 ID
        fields: 要更新的字段，如 {"summary": "新标题", "description": "新描述"}
    """
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
    """将任务添加到清单

    Args:
        task_id: 任务 GUID
        tasklist_id: 任务清单 GUID
    """
    return _post(f"/task/v2/tasks/{task_id}/add_tasklist",
                 {"tasklist_guid": tasklist_id},
                 action="添加任务到清单")


# ============================================================
# 知识库 (wiki/v2)
# ============================================================

def wiki_list_spaces(page_size: int = 50, page_token: str = "") -> Dict[str, Any]:
    """获取知识空间列表"""
    params: Dict[str, Any] = {"page_size": page_size}
    if page_token:
        params["page_token"] = page_token
    return _get("/wiki/v2/spaces", params, action="获取知识空间列表")


def wiki_get_space(space_id: str) -> Dict[str, Any]:
    """获取知识空间信息"""
    return _get(f"/wiki/v2/spaces/{space_id}", action="获取知识空间信息")


def wiki_list_nodes(
    space_id: str,
    parent_node_token: str = "",
    page_size: int = 50,
    page_token: str = "",
) -> Dict[str, Any]:
    """获取知识空间节点列表"""
    params: Dict[str, Any] = {"page_size": page_size}
    if parent_node_token:
        params["parent_node_token"] = parent_node_token
    if page_token:
        params["page_token"] = page_token
    return _get(f"/wiki/v2/spaces/{space_id}/nodes", params, action="获取知识空间节点")


def wiki_get_node(space_id: str, node_token: str) -> Dict[str, Any]:
    """获取知识库节点信息"""
    return _get(f"/wiki/v2/spaces/{space_id}/nodes/{node_token}",
                action="获取知识库节点信息")


def wiki_create_node(
    space_id: str,
    obj_type: str,
    parent_node_token: str = "",
    title: str = "",
    obj_token: str = "",
) -> Dict[str, Any]:
    """创建知识库节点（或移入已有文档）

    Args:
        obj_type: doc / sheet / bitable / mindnote / docx / file
        obj_token: 已有文档的 token（移入知识库）
    """
    payload: Dict[str, Any] = {"obj_type": obj_type}
    if parent_node_token:
        payload["parent_node_token"] = parent_node_token
    if title:
        payload["title"] = title
    if obj_token:
        payload["obj_token"] = obj_token
    return _post(f"/wiki/v2/spaces/{space_id}/nodes", payload,
                 action="创建知识库节点")


def wiki_search(
    keyword: str,
    space_id: str = "",
    page_size: int = 20,
) -> Dict[str, Any]:
    """搜索知识库"""
    payload: Dict[str, Any] = {"query": keyword, "page_size": page_size}
    if space_id:
        payload["space_id"] = space_id
    return _post("/wiki/v1/nodes/search", payload, action="搜索知识库")


# ============================================================
# 云空间 / 文件管理 (drive/v1)
# ============================================================

def drive_create_folder(
    name: str,
    folder_token: str = "",
) -> Dict[str, Any]:
    """创建文件夹"""
    payload: Dict[str, Any] = {"name": name, "folder_token": folder_token}
    return _post("/drive/v1/files/create_folder", payload, action="创建文件夹")


def drive_upload_file(
    file_path: str,
    parent_node: str,
    file_name: str = "",
) -> Dict[str, Any]:
    """上传文件到云空间

    注意: 此函数使用 upload_all 单次上传，适合 < 20MB 的文件
    """
    name = file_name or os.path.basename(file_path)
    size = os.path.getsize(file_path)
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/drive/v1/files/upload_all",
            headers={"Authorization": f"Bearer {get_tenant_access_token()}"},
            data={"file_name": name, "parent_type": "explorer", "parent_node": parent_node, "size": str(size)},
            files={"file": (name, f)},
            timeout=60,
        )
    return _check(resp.json(), "上传文件")


def drive_download_file(file_token: str, save_path: str) -> str:
    """下载文件"""
    resp = requests.get(
        f"{BASE_URL}/drive/v1/files/{file_token}/download",
        headers=_headers(), stream=True, timeout=60,
    )
    resp.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    return save_path


def drive_move_file(file_token: str, dst_folder_token: str) -> Dict[str, Any]:
    """移动文件"""
    return _post(f"/drive/v1/files/{file_token}/move",
                 {"folder_token": dst_folder_token}, action="移动文件")


def drive_copy_file(file_token: str, dst_folder_token: str, name: str = "") -> Dict[str, Any]:
    """复制文件"""
    payload: Dict[str, Any] = {"folder_token": dst_folder_token}
    if name:
        payload["name"] = name
    return _post(f"/drive/v1/files/{file_token}/copy", payload, action="复制文件")


def drive_delete_file(file_token: str) -> Dict[str, Any]:
    """删除文件"""
    return _delete(f"/drive/v1/files/{file_token}", action="删除文件")


def drive_add_permission(
    token: str,
    member_type: str,
    member_id: str,
    perm: str = "view",
    token_type: str = "doc",
) -> Dict[str, Any]:
    """添加文档权限

    Args:
        token: 文档 token
        member_type: user / chat / department / openchat
        member_id: 成员 ID
        perm: view / edit / full_access
        token_type: doc / sheet / bitable / folder / docx
    """
    return _post(f"/drive/v1/permissions/{token}/members",
                 {"member_type": member_type, "member_id": member_id, "perm": perm},
                 params={"type": token_type}, action="添加文档权限")


# ============================================================
# 百科 (baike/v1)
# ============================================================

def baike_search(query: str, page_size: int = 20) -> Dict[str, Any]:
    """搜索百科词条"""
    return _post("/baike/v1/entities/search",
                 {"query": query, "page_size": page_size}, action="搜索百科词条")


def baike_get_entity(entity_id: str) -> Dict[str, Any]:
    """获取百科词条详情"""
    return _get(f"/baike/v1/entities/{entity_id}", action="获取百科词条详情")


def baike_create_entity(
    main_keys: List[str],
    description: str,
    aliases: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """创建百科词条"""
    payload: Dict[str, Any] = {
        "main_keys": [{"key": k, "display_status": {"allow_highlight": True, "allow_search": True}}
                      for k in main_keys],
        "description": description,
    }
    if aliases:
        payload["aliases"] = [{"key": a, "display_status": {"allow_highlight": True, "allow_search": True}}
                              for a in aliases]
    return _post("/baike/v1/entities", payload, action="创建百科词条")


def baike_update_entity(entity_id: str, fields: dict) -> Dict[str, Any]:
    """更新百科词条"""
    return _put(f"/baike/v1/entities/{entity_id}", fields, action="更新百科词条")


def baike_highlight(content: str) -> Dict[str, Any]:
    """词条高亮（在文本中标记匹配的词条）"""
    return _post("/baike/v1/entities/highlight", {"text": content}, action="百科词条高亮")


# ============================================================
# 人事 / 请假记录 (corehr/v1)
# ============================================================

def hr_leave_request_history(
    employment_id: str = "",
    leave_type_id: str = "",
    start_date: str = "",
    end_date: str = "",
    page_size: int = 50,
    page_token: str = "",
    user_id_type: str = "open_id",
) -> Dict[str, Any]:
    """查询请假记录

    Args:
        employment_id: 雇员 ID
        start_date: "2026-01-01"
        end_date: "2026-03-12"
    """
    params: Dict[str, Any] = {
        "page_size": page_size,
        "user_id_type": user_id_type,
    }
    if employment_id:
        params["employment_id"] = employment_id
    if leave_type_id:
        params["leave_type_id"] = leave_type_id
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if page_token:
        params["page_token"] = page_token
    return _get("/corehr/v1/leaves/leave_request_history", params,
                action="查询请假记录")


def hr_get_employee(employment_id: str, user_id_type: str = "open_id") -> Dict[str, Any]:
    """查询员工花名册信息"""
    return _get(f"/corehr/v1/employments/{employment_id}",
                {"user_id_type": user_id_type}, action="查询员工信息")


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu_api", description="飞书统一 API 命令行工具")
    sub = parser.add_subparsers(dest="module", help="模块")

    # --- chat ---
    p_chat = sub.add_parser("chat", help="群组管理")
    cs = p_chat.add_subparsers(dest="action")
    p = cs.add_parser("list", help="列出群组")
    p.add_argument("--limit", type=int, default=20)
    p = cs.add_parser("info", help="获取群信息")
    p.add_argument("--chat-id", required=True)
    p = cs.add_parser("members", help="获取群成员")
    p.add_argument("--chat-id", required=True)
    p.add_argument("--all", action="store_true")
    p.add_argument("--limit", type=int, default=100)

    # --- message ---
    p_msg = sub.add_parser("message", help="消息操作")
    ms = p_msg.add_subparsers(dest="action")
    p = ms.add_parser("history", help="会话历史")
    p.add_argument("--chat-id", required=True)
    p.add_argument("--start-time", default="")
    p.add_argument("--end-time", default="")
    p.add_argument("--limit", type=int, default=20)
    p = ms.add_parser("send", help="发送文本")
    p.add_argument("--receive-id", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--id-type", default="chat_id")
    p = ms.add_parser("get", help="获取单条消息")
    p.add_argument("--message-id", required=True)

    # --- contact ---
    p_ct = sub.add_parser("contact", help="通讯录")
    cts = p_ct.add_subparsers(dest="action")
    p = cts.add_parser("user", help="获取用户信息")
    p.add_argument("--user-id", required=True)
    p.add_argument("--id-type", default="open_id")
    p = cts.add_parser("dept-users", help="部门用户列表")
    p.add_argument("--department-id", default="0")
    p.add_argument("--limit", type=int, default=50)
    p = cts.add_parser("dept", help="部门信息")
    p.add_argument("--department-id", required=True)
    p = cts.add_parser("dept-children", help="子部门列表")
    p.add_argument("--parent-id", default="0")
    p.add_argument("--limit", type=int, default=50)

    # --- attendance ---
    p_att = sub.add_parser("attendance", help="考勤查询")
    ats = p_att.add_subparsers(dest="action")
    p = ats.add_parser("query", help="查询打卡")
    p.add_argument("--user-ids", required=True, help="employee_id,逗号分隔")
    p.add_argument("--date-from", type=int, required=True, help="yyyyMMdd")
    p.add_argument("--date-to", type=int, required=True, help="yyyyMMdd")

    # --- doc ---
    p_doc = sub.add_parser("doc", help="云文档")
    ds = p_doc.add_subparsers(dest="action")
    p = ds.add_parser("list", help="列出文件")
    p.add_argument("--parent-node", default="")
    p.add_argument("--limit", type=int, default=20)
    p = ds.add_parser("read", help="读取文档")
    p.add_argument("--document-id", required=True)
    p = ds.add_parser("search", help="搜索文档")
    p.add_argument("--keyword", required=True)
    p.add_argument("--limit", type=int, default=10)

    # --- bitable ---
    p_bt = sub.add_parser("bitable", help="多维表格")
    bs = p_bt.add_subparsers(dest="action")
    p = bs.add_parser("tables", help="列出数据表")
    p.add_argument("--app-token", required=True)
    p = bs.add_parser("fields", help="获取字段定义")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p = bs.add_parser("list", help="查询记录")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--limit", type=int, default=20)
    p = bs.add_parser("add", help="创建记录")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--fields", required=True, help="字段 JSON")
    p = bs.add_parser("update", help="更新记录")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--record-id", required=True)
    p.add_argument("--fields", required=True, help="字段 JSON")
    p = bs.add_parser("delete", help="删除记录")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--record-id", required=True)
    p = bs.add_parser("daily-add", help="录入日报")
    p.add_argument("--user-id", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--hours", type=float, required=True)
    p = bs.add_parser("daily-query", help="查询日报")
    p.add_argument("--limit", type=int, default=10)
    p = bs.add_parser("task-add", help="录入任务")
    p.add_argument("--name", required=True)
    p.add_argument("--serial", type=int, required=True)
    p.add_argument("--project", required=True, help="项目 record_id")
    p.add_argument("--executor", required=True, help="执行人 open_id")
    p.add_argument("--status", default="进行中")
    p.add_argument("--deadline", type=int, default=7)
    p.add_argument("--hours", type=int, default=2)
    p.add_argument("--description", default="")
    p.add_argument("--table", default=TASK_TABLE_ID)
    p = bs.add_parser("task-query", help="查询任务")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--table", default=TASK_TABLE_ID)

    # --- approval ---
    p_ap = sub.add_parser("approval", help="审批")
    aps = p_ap.add_subparsers(dest="action")
    p = aps.add_parser("definition", help="获取审批定义")
    p.add_argument("--code", required=True)
    p = aps.add_parser("list", help="列出实例")
    p.add_argument("--code", required=True)
    p.add_argument("--limit", type=int, default=20)
    p = aps.add_parser("get", help="获取实例详情")
    p.add_argument("--instance-code", required=True)
    p = aps.add_parser("create", help="创建实例")
    p.add_argument("--code", required=True)
    p.add_argument("--user-id", required=True)
    p.add_argument("--form", required=True, help="表单 JSON")

    # --- calendar ---
    p_cal = sub.add_parser("calendar", help="日历与日程")
    cas = p_cal.add_subparsers(dest="action")
    p = cas.add_parser("list", help="列出日历")
    p = cas.add_parser("events", help="列出日程")
    p.add_argument("--calendar-id", default="primary")
    p.add_argument("--start-time", default="")
    p.add_argument("--end-time", default="")
    p.add_argument("--limit", type=int, default=50)
    p = cas.add_parser("create-event", help="创建日程")
    p.add_argument("--calendar-id", default="primary")
    p.add_argument("--summary", required=True)
    p.add_argument("--start-time", required=True)
    p.add_argument("--end-time", required=True)
    p.add_argument("--description", default="")

    # --- task ---
    p_task = sub.add_parser("task", help="任务管理")
    ts = p_task.add_subparsers(dest="action")
    p = ts.add_parser("list", help="列出任务")
    p.add_argument("--limit", type=int, default=50)
    p = ts.add_parser("get", help="获取任务")
    p.add_argument("--task-id", required=True)
    p = ts.add_parser("create", help="创建任务")
    p.add_argument("--summary", required=True)
    p.add_argument("--description", default="")
    p = ts.add_parser("complete", help="完成任务")
    p.add_argument("--task-id", required=True)

    # --- wiki ---
    p_wiki = sub.add_parser("wiki", help="知识库")
    ws = p_wiki.add_subparsers(dest="action")
    p = ws.add_parser("spaces", help="列出知识空间")
    p = ws.add_parser("nodes", help="列出节点")
    p.add_argument("--space-id", required=True)
    p.add_argument("--parent-node", default="")
    p = ws.add_parser("search", help="搜索知识库")
    p.add_argument("--keyword", required=True)
    p.add_argument("--space-id", default="")

    # --- drive ---
    p_drv = sub.add_parser("drive", help="云空间/文件管理")
    drs = p_drv.add_subparsers(dest="action")
    p = drs.add_parser("mkdir", help="创建文件夹")
    p.add_argument("--name", required=True)
    p.add_argument("--folder-token", default="")
    p = drs.add_parser("upload", help="上传文件")
    p.add_argument("--file", required=True)
    p.add_argument("--parent-node", required=True)
    p = drs.add_parser("download", help="下载文件")
    p.add_argument("--file-token", required=True)
    p.add_argument("--save-path", required=True)

    # --- baike ---
    p_bk = sub.add_parser("baike", help="百科")
    bks = p_bk.add_subparsers(dest="action")
    p = bks.add_parser("search", help="搜索词条")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=20)
    p = bks.add_parser("get", help="获取词条详情")
    p.add_argument("--entity-id", required=True)
    p = bks.add_parser("highlight", help="词条高亮")
    p.add_argument("--text", required=True)

    # --- hr ---
    p_hr = sub.add_parser("hr", help="人事")
    hrs = p_hr.add_subparsers(dest="action")
    p = hrs.add_parser("leave-history", help="请假记录")
    p.add_argument("--employment-id", default="")
    p.add_argument("--start-date", default="")
    p.add_argument("--end-date", default="")
    p.add_argument("--limit", type=int, default=50)
    p = hrs.add_parser("employee", help="员工信息")
    p.add_argument("--employment-id", required=True)

    return parser


def _run_cli(args: argparse.Namespace) -> None:
    mod = args.module
    act = getattr(args, "action", None)

    if mod == "chat":
        if act == "list":
            _pp(list_chats(args.limit))
        elif act == "info":
            _pp(get_chat(args.chat_id))
        elif act == "members":
            if args.all:
                _pp(get_chat_members_all(args.chat_id))
            else:
                _pp(get_chat_members(args.chat_id, page_size=args.limit))

    elif mod == "message":
        if act == "history":
            _pp(get_chat_history(args.chat_id, args.start_time, args.end_time, args.limit))
        elif act == "send":
            _pp(send_text(args.receive_id, args.text, args.id_type))
        elif act == "get":
            _pp(get_message(args.message_id))

    elif mod == "contact":
        if act == "user":
            _pp(get_user(args.user_id, args.id_type))
        elif act == "dept-users":
            _pp(list_department_users(args.department_id, page_size=args.limit))
        elif act == "dept":
            _pp(get_department(args.department_id))
        elif act == "dept-children":
            _pp(list_departments(args.parent_id, page_size=args.limit))

    elif mod == "attendance":
        if act == "query":
            _pp(get_attendance(args.user_ids.split(","), args.date_from, args.date_to))

    elif mod == "doc":
        if act == "list":
            _pp(list_files(args.parent_node, args.limit))
        elif act == "read":
            print(read_doc(args.document_id))
        elif act == "search":
            _pp(search_docs(args.keyword, args.limit))

    elif mod == "bitable":
        if act == "tables":
            _pp(bitable_list_tables(args.app_token))
        elif act == "fields":
            _pp(bitable_get_fields(args.app_token, args.table_id))
        elif act == "list":
            _pp(bitable_list_records(args.app_token, args.table_id, args.limit))
        elif act == "add":
            _pp(bitable_add_record(args.app_token, args.table_id, json.loads(args.fields)))
        elif act == "update":
            _pp(bitable_update_record(args.app_token, args.table_id, args.record_id,
                                      json.loads(args.fields)))
        elif act == "delete":
            _pp(bitable_delete_record(args.app_token, args.table_id, args.record_id))
        elif act == "daily-add":
            _pp(bitable_add_daily_report(args.user_id, args.date, args.project,
                                         args.content, args.hours))
        elif act == "daily-query":
            _pp(bitable_query_daily_reports(args.limit))
        elif act == "task-add":
            _pp(bitable_add_task(args.name, args.serial, args.project, args.executor,
                                 args.status, args.deadline, args.hours, args.description,
                                 args.table))
        elif act == "task-query":
            _pp(bitable_query_tasks(args.limit, args.table))

    elif mod == "approval":
        if act == "definition":
            _pp(approval_get_definition(args.code))
        elif act == "list":
            _pp(approval_list_instances(args.code, page_size=args.limit))
        elif act == "get":
            _pp(approval_get_instance(args.instance_code))
        elif act == "create":
            _pp(approval_create_instance(args.code, args.user_id, args.form))

    elif mod == "calendar":
        if act == "list":
            _pp(calendar_list())
        elif act == "events":
            _pp(calendar_list_events(args.calendar_id, args.start_time or None,
                                     args.end_time or None, args.limit))
        elif act == "create-event":
            _pp(calendar_create_event(args.calendar_id, args.summary,
                                      args.start_time, args.end_time, args.description))

    elif mod == "task":
        if act == "list":
            _pp(task_list(args.limit))
        elif act == "get":
            _pp(task_get(args.task_id))
        elif act == "create":
            _pp(task_create(args.summary, args.description))
        elif act == "complete":
            _pp(task_complete(args.task_id))

    elif mod == "wiki":
        if act == "spaces":
            _pp(wiki_list_spaces())
        elif act == "nodes":
            _pp(wiki_list_nodes(args.space_id, args.parent_node))
        elif act == "search":
            _pp(wiki_search(args.keyword, args.space_id))

    elif mod == "drive":
        if act == "mkdir":
            _pp(drive_create_folder(args.name, args.folder_token))
        elif act == "upload":
            _pp(drive_upload_file(args.file, args.parent_node))
        elif act == "download":
            print(drive_download_file(args.file_token, args.save_path))

    elif mod == "baike":
        if act == "search":
            _pp(baike_search(args.query, args.limit))
        elif act == "get":
            _pp(baike_get_entity(args.entity_id))
        elif act == "highlight":
            _pp(baike_highlight(args.text))

    elif mod == "hr":
        if act == "leave-history":
            _pp(hr_leave_request_history(args.employment_id, start_date=args.start_date,
                                         end_date=args.end_date, page_size=args.limit))
        elif act == "employee":
            _pp(hr_get_employee(args.employment_id))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.module:
        parser.print_help()
        return 1
    if not getattr(args, "action", None):
        parser.parse_args([args.module, "--help"])
        return 1
    try:
        _run_cli(args)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
