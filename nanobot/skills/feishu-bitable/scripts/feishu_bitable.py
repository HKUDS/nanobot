#!/usr/bin/env python3
"""feishu_bitable - 飞书多维表格 API（增强版）

凭据获取优先级：~/.hiperone/config.json > 环境变量
"""

import argparse
import json
import os
import sys
import time as _time
import requests
from datetime import datetime, timedelta, timezone
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
        raise RuntimeError(f"获取 Token 失败：{data}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires"] = now + data.get("expire", 7200) - 60
    return _token_cache["token"]


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {get_tenant_access_token()}"}


# ============================================================
# 错误码映射（优化错误提示）
# ============================================================

_ERROR_HINTS = {
    1254045: "字段名不存在，请先调用 bitable_get_fields 查看字段定义",
    1254064: "日期字段格式错误，请使用毫秒时间戳或 YYYY-MM-DD 格式",
    1254066: "用户字段格式错误，请提供有效的 open_id 或 union_id",
    1254063: "单选/多选字段值错误，请检查选项是否存在",
}


def _check(data: dict, action: str) -> dict:
    if data.get("code") != 0:
        code = data.get("code")
        hint = _ERROR_HINTS.get(code, "")
        msg = f"{action}失败：[{code}] {data.get('msg', 'Unknown error')}"
        if hint:
            msg += f" - {hint}"
        raise RuntimeError(msg)
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


def _delete(path: str, *, timeout: int = 10, action: str = "") -> dict:
    resp = requests.delete(f"{BASE_URL}{path}", headers=_headers(), timeout=timeout)
    return _check(resp.json(), action or path)


def _pp(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# 字段类型枚举
# ============================================================

class FieldType:
    TEXT = 1
    NUMBER = 2
    SINGLE_SELECT = 3
    MULTI_SELECT = 4
    DATE_TIME = 5
    USER = 11
    LINK = 18
    AUTO_NUMBER = 1005


# ============================================================
# 字段格式自动转换
# ============================================================

_field_cache: Dict[str, Dict] = {}


def _get_field_map(app_token: str, table_id: str) -> Dict[str, Any]:
    """获取字段映射（带缓存）"""
    cache_key = f"{app_token}:{table_id}"
    if cache_key not in _field_cache:
        fields_data = bitable_get_fields(app_token, table_id)
        _field_cache[cache_key] = {
            f["field_name"]: f for f in fields_data.get("items", [])
        }
    return _field_cache[cache_key]


_CN_TZ = timezone(timedelta(hours=8))


def _convert_field_value(field_type: int, value: Any) -> Any:
    """自动转换字段值为 API 格式"""
    if value is None:
        return None

    if field_type == FieldType.DATE_TIME:
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"]:
                try:
                    dt = datetime.strptime(value, fmt).replace(tzinfo=_CN_TZ)
                    return int(dt.timestamp() * 1000)
                except ValueError:
                    continue
            return value

    elif field_type == FieldType.USER:
        if isinstance(value, str):
            return [{"id": value}]
        if isinstance(value, list):
            return [{"id": v} if isinstance(v, str) else v for v in value]
        return value

    elif field_type == FieldType.MULTI_SELECT:
        if isinstance(value, str):
            return [value]
        return value

    elif field_type == FieldType.SINGLE_SELECT:
        return value

    elif field_type == FieldType.NUMBER:
        if isinstance(value, str):
            try:
                return float(value) if '.' in value else int(value)
            except ValueError:
                return value
        return value

    return value


def bitable_add_record_smart(
    app_token: str,
    table_id: str,
    fields: Dict[str, Any],
    use_cache: bool = True,
) -> Dict[str, Any]:
    """智能创建记录（自动转换字段格式）
    
    Args:
        app_token: 多维表格 token
        table_id: 数据表 ID
        fields: 字段数据（使用自然格式）
        use_cache: 是否使用字段缓存
    
    Returns:
        创建的记录
    """
    if use_cache:
        field_map = _get_field_map(app_token, table_id)
        converted = {}
        for name, value in fields.items():
            if name in field_map:
                field_type = field_map[name].get("type", 1)
                converted[name] = _convert_field_value(field_type, value)
            else:
                converted[name] = value
    else:
        converted = fields
    
    return bitable_add_record(app_token, table_id, converted)


def bitable_update_record_smart(
    app_token: str,
    table_id: str,
    record_id: str,
    fields: Dict[str, Any],
    use_cache: bool = True,
) -> Dict[str, Any]:
    """智能更新记录（自动转换字段格式）"""
    if use_cache:
        field_map = _get_field_map(app_token, table_id)
        converted = {}
        for name, value in fields.items():
            if name in field_map:
                field_type = field_map[name].get("type", 1)
                converted[name] = _convert_field_value(field_type, value)
            else:
                converted[name] = value
    else:
        converted = fields
    return bitable_update_record(app_token, table_id, record_id, converted)


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


def bitable_batch_add_records(
    app_token: str,
    table_id: str,
    records_list: List[Dict[str, Any]],
    smart: bool = False,
) -> Dict[str, Any]:
    """批量创建记录（使用飞书批量 API，单次最多 500 条）

    Args:
        records_list: 字段字典列表，如 [{"名称":"A"}, {"名称":"B"}]
        smart: 是否对每条记录做智能字段转换
    """
    if smart:
        field_map = _get_field_map(app_token, table_id)
        converted = []
        for fields in records_list:
            row = {}
            for name, value in fields.items():
                if name in field_map:
                    row[name] = _convert_field_value(field_map[name].get("type", 1), value)
                else:
                    row[name] = value
            converted.append(row)
        records_list = converted

    payload = {"records": [{"fields": f} for f in records_list[:500]]}
    return _post(
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
        payload, action="批量创建记录",
    )


def bitable_batch_update_records(
    app_token: str,
    table_id: str,
    records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """批量更新记录（单次最多 500 条）

    Args:
        records: [{"record_id": "recXXX", "fields": {"字段名": "值"}}, ...]
    """
    payload = {"records": records[:500]}
    return _post(
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update",
        payload, action="批量更新记录",
    )


def bitable_batch_delete_records(
    app_token: str,
    table_id: str,
    record_ids: List[str],
) -> Dict[str, Any]:
    """批量删除记录（单次最多 500 条）

    Args:
        record_ids: ["recXXX", "recYYY", ...]
    """
    payload = {"records": record_ids[:500]}
    return _post(
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete",
        payload, action="批量删除记录",
    )


# ============================================================
# 便捷函数（业务场景）
# ============================================================

BITABLE_APP_TOKEN = "JXdtbkkchaSXmksx6eFc2Eatn45"
DAILY_TABLE_ID = "tblYWOnDxGsVSfDN"
TASK_TABLE_ID = "tblH6xn2dp6E1UtD"
PROJECT_TABLE_ID = "tblihZwJnOg84PUQ"


def bitable_add_daily_report(
    user_id: str,
    date: str,
    project: str,
    content: str,
    hours: float,
    app_token: str = BITABLE_APP_TOKEN,
) -> Dict[str, Any]:
    """录入日报（智能版）"""
    fields = {
        "姓名": user_id,  # User 字段会自动转换
        "日期": date,
        "项目": project,
        "工作内容": content,
        "时长": str(hours),  # 日报表时长是文本字段
    }
    return bitable_add_record_smart(app_token, DAILY_TABLE_ID, fields)


def _build_filter(*parts: Optional[str]) -> Optional[str]:
    """合并多个过滤条件为 AND 表达式，过滤空值"""
    valid = [p for p in parts if p and p.strip()]
    if not valid:
        return None
    return "&&".join(f"({p})" for p in valid)


def bitable_query_daily_reports(
    page_size: int = 20,
    filter_expr: Optional[str] = None,
    page_token: str = "",
    app_token: str = BITABLE_APP_TOKEN,
    table_id: Optional[str] = None,
    date: Optional[str] = None,
    user_id: Optional[str] = None,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """查询日报记录

    Args:
        page_size: 每页条数
        filter_expr: 过滤表达式，如 'CurrentValue.[项目]="xxx"'
        page_token: 分页标记
        app_token: 多维表格 app_token
        table_id: 日报表 ID，默认 DAILY_TABLE_ID
        date: 按日期筛选，如 "2026-03-13"
        user_id: 按姓名（执行人 open_id）筛选
        project: 按项目名筛选
    """
    tid = table_id or DAILY_TABLE_ID
    parts = []
    if date:
        parts.append(f'CurrentValue.[日期] = "{date}"')
    if user_id:
        parts.append(f'CurrentValue.[姓名].contains("{user_id}")')
    if project:
        parts.append(f'CurrentValue.[项目] = "{project}"')
    if filter_expr:
        parts.append(filter_expr)
    final_filter = _build_filter(*parts) if parts else None
    return bitable_list_records(app_token, tid, page_size=page_size,
                                filter_expr=final_filter, page_token=page_token)


def bitable_add_task(
    task_name: str,
    project_record_id: str,
    executor_id: str,
    status: str = "进行中",
    deadline_days: int = 7,
    estimated_hours: int = 2,
    description: str = "",
    table_id: str = TASK_TABLE_ID,
    app_token: str = BITABLE_APP_TOKEN,
) -> Dict[str, Any]:
    """录入任务（序号为自动编号字段，无需传入）

    Args:
        task_name: 任务名称
        project_record_id: 所属项目 record_id
        executor_id: 执行人 open_id
        status: 状态（待处理/进行中/完成）
        deadline_days: 截止日期（从今天起多少天）
        estimated_hours: 预计耗时
        description: 说明
    """
    deadline = int(
        datetime.now(_CN_TZ).replace(hour=23, minute=59, second=59)
        .timestamp() * 1000
    ) + deadline_days * 86400_000
    fields = {
        "任务名称": task_name,
        "所属项目": [project_record_id],
        "执行人": [{"id": executor_id}],
        "状态": status,
        "计划截止时间": deadline,
        "预计耗时": estimated_hours,
        "说明": description,
    }
    return bitable_add_record_smart(app_token, table_id, fields)


def bitable_query_tasks(
    page_size: int = 20,
    filter_expr: Optional[str] = None,
    page_token: str = "",
    table_id: str = TASK_TABLE_ID,
    app_token: str = BITABLE_APP_TOKEN,
    status: Optional[str] = None,
    executor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """查询任务记录

    Args:
        page_size: 每页条数
        filter_expr: 过滤表达式，如 'CurrentValue.[状态]="进行中"'
        page_token: 分页标记
        table_id: 任务表 ID
        app_token: 多维表格 app_token
        status: 按状态筛选，如 "进行中"、"待处理"、"完成"
        executor_id: 按执行人 open_id 筛选
    """
    parts = []
    if status:
        parts.append(f'CurrentValue.[状态] = "{status}"')
    if executor_id:
        parts.append(f'CurrentValue.[执行人].contains("{executor_id}")')
    if filter_expr:
        parts.append(filter_expr)
    final_filter = _build_filter(*parts) if parts else None
    return bitable_list_records(app_token, table_id, page_size=page_size,
                                filter_expr=final_filter, page_token=page_token)


def bitable_complete_task(
    record_id: str,
    table_id: str = TASK_TABLE_ID,
    app_token: str = BITABLE_APP_TOKEN,
) -> Dict[str, Any]:
    """将任务标记为完成（更新状态为「完成」）"""
    return bitable_update_record_smart(app_token, table_id, record_id, {"状态": "完成"})


def bitable_list_projects(
    page_size: int = 50,
    app_token: str = BITABLE_APP_TOKEN,
    table_id: Optional[str] = None,
) -> Dict[str, Any]:
    """查询项目列表"""
    tid = table_id or PROJECT_TABLE_ID
    return bitable_list_records(app_token, tid, page_size=page_size)


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu_bitable", description="飞书多维表格")
    sub = parser.add_subparsers(dest="action")
    
    p = sub.add_parser("tables", help="列出数据表")
    p.add_argument("--app-token", required=True)
    
    p = sub.add_parser("fields", help="获取字段定义")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    
    p = sub.add_parser("list", help="查询记录")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--filter", default="", help="过滤条件表达式")
    
    p = sub.add_parser("add", help="创建记录")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--fields", required=True, help="字段 JSON")
    
    p = sub.add_parser("add-smart", help="创建记录（智能转换格式）")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--fields", required=True, help="字段 JSON")
    
    p = sub.add_parser("update", help="更新记录")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--record-id", required=True)
    p.add_argument("--fields", required=True, help="字段 JSON")
    
    p = sub.add_parser("update-smart", help="智能更新记录（自动转换格式）")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--record-id", required=True)
    p.add_argument("--fields", required=True, help="字段 JSON")

    p = sub.add_parser("delete", help="删除记录")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--record-id", required=True)
    
    p = sub.add_parser("batch-add", help="批量创建记录")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--records", required=True, help="记录数组 JSON")
    p.add_argument("--smart", action="store_true", help="启用智能字段转换")
    
    p = sub.add_parser("batch-update", help="批量更新记录")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--records", required=True, help='JSON: [{"record_id":"recXXX","fields":{...}}, ...]')

    p = sub.add_parser("batch-delete", help="批量删除记录")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--record-ids", required=True, help='JSON: ["recXXX","recYYY"]')

    p = sub.add_parser("daily-add", help="录入日报")
    p.add_argument("--user-id", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--hours", type=float, required=True)
    
    p = sub.add_parser("daily-query", help="查询日报")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--filter", default="", help="过滤表达式")
    p.add_argument("--date", default="", help="按日期筛选，如 2026-03-13")
    p.add_argument("--user-id", default="", help="按姓名 open_id 筛选")
    p.add_argument("--project", default="", help="按项目名筛选")
    p.add_argument("--page-token", default="")
    p.add_argument("--app-token", default=BITABLE_APP_TOKEN)
    p.add_argument("--table-id", default="", help="日报表 ID，默认 DAILY_TABLE_ID")
    
    p = sub.add_parser("task-add", help="录入任务")
    p.add_argument("--name", required=True)
    p.add_argument("--project", required=True, help="项目 record_id")
    p.add_argument("--executor", required=True, help="执行人 open_id")
    p.add_argument("--status", default="进行中")
    p.add_argument("--deadline", type=int, default=7)
    p.add_argument("--hours", type=int, default=2)
    p.add_argument("--description", default="")
    p.add_argument("--table", default=TASK_TABLE_ID)
    
    p = sub.add_parser("task-query", help="查询任务")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--filter", default="", help="过滤表达式")
    p.add_argument("--status", default="", help="按状态筛选：待处理/进行中/完成")
    p.add_argument("--executor", default="", help="按执行人 open_id 筛选")
    p.add_argument("--page-token", default="")
    p.add_argument("--table", default=TASK_TABLE_ID)
    p.add_argument("--app-token", default=BITABLE_APP_TOKEN)

    p = sub.add_parser("task-complete", help="将任务标记为完成")
    p.add_argument("--record-id", required=True)
    p.add_argument("--table", default=TASK_TABLE_ID)
    p.add_argument("--app-token", default=BITABLE_APP_TOKEN)

    p = sub.add_parser("projects", help="查询项目列表")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--app-token", default=BITABLE_APP_TOKEN)
    p.add_argument("--table-id", default="", help="项目表 ID，默认 PROJECT_TABLE_ID")
    
    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "tables":
        _pp(bitable_list_tables(args.app_token))
    elif act == "fields":
        _pp(bitable_get_fields(args.app_token, args.table_id))
    elif act == "list":
        _pp(bitable_list_records(args.app_token, args.table_id, args.limit,
                                 filter_expr=args.filter or None))
    elif act == "add":
        _pp(bitable_add_record(args.app_token, args.table_id, json.loads(args.fields)))
    elif act == "add-smart":
        _pp(bitable_add_record_smart(args.app_token, args.table_id, json.loads(args.fields)))
    elif act == "update":
        _pp(bitable_update_record(args.app_token, args.table_id, args.record_id,
                                  json.loads(args.fields)))
    elif act == "update-smart":
        _pp(bitable_update_record_smart(args.app_token, args.table_id, args.record_id,
                                        json.loads(args.fields)))
    elif act == "delete":
        _pp(bitable_delete_record(args.app_token, args.table_id, args.record_id))
    elif act == "batch-add":
        _pp(bitable_batch_add_records(args.app_token, args.table_id,
                                      json.loads(args.records), smart=args.smart))
    elif act == "batch-update":
        _pp(bitable_batch_update_records(args.app_token, args.table_id,
                                         json.loads(args.records)))
    elif act == "batch-delete":
        _pp(bitable_batch_delete_records(args.app_token, args.table_id,
                                         json.loads(args.record_ids)))
    elif act == "daily-add":
        _pp(bitable_add_daily_report(args.user_id, args.date, args.project,
                                     args.content, args.hours))
    elif act == "daily-query":
        _pp(bitable_query_daily_reports(args.limit,
            filter_expr=args.filter or None, page_token=args.page_token or "",
            app_token=args.app_token, table_id=args.table_id or None,
            date=args.date or None, user_id=args.user_id or None,
            project=args.project or None))
    elif act == "task-add":
        _pp(bitable_add_task(args.name, args.project, args.executor,
                             args.status, args.deadline, args.hours, args.description,
                             args.table))
    elif act == "task-query":
        _pp(bitable_query_tasks(args.limit,
            filter_expr=args.filter or None, page_token=args.page_token or "",
            table_id=args.table, app_token=args.app_token,
            status=args.status or None, executor_id=args.executor or None))
    elif act == "task-complete":
        _pp(bitable_complete_task(args.record_id, args.table, args.app_token))
    elif act == "projects":
        _pp(bitable_list_projects(args.limit, args.app_token, args.table_id or None))


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
