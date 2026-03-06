#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feishu Bitable API - 飞书多维表 Python API
支持日报和任务的增删改查操作
"""

import os
import json
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta


# ============================================================
# 配置
# ============================================================

# 表 ID
DAILY_TABLE_ID = "tblYWOnDxGsVSfDN"
TASK_TABLE_ID = "tblH6xn2dp6E1UtD"

# 默认项目关联记录
DEFAULT_PROJECT_RECORD = "recvcGZsmzHcCF"  # HiperOne


# ============================================================
# 工具函数
# ============================================================

APP_TOKEN = "JXdtbkkchaSXmksx6eFc2Eatn45"


def load_config() -> Dict:
    """从系统环境变量加载飞书凭据"""
    config = {
        "APP_ID": os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_ID', ''),
        "APP_SECRET": os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_SECRET', ''),
        "APP_TOKEN": APP_TOKEN,
        "BASE_URL": "https://open.feishu.cn/open-apis",
    }
    if not config['APP_ID'] or not config['APP_SECRET']:
        raise Exception("缺少飞书凭据，请设置环境变量 NANOBOT_CHANNELS__FEISHU__APP_ID / NANOBOT_CHANNELS__FEISHU__APP_SECRET")
    return config


def get_tenant_token(config: Dict) -> str:
    """获取 tenant_access_token"""
    url = f"{config['BASE_URL']}/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    payload = {
        "app_id": config['APP_ID'],
        "app_secret": config['APP_SECRET']
    }
    response = requests.post(url, json=payload, headers=headers)
    result = response.json()
    
    if result.get("code") != 0:
        raise Exception(f"获取 token 失败：{result}")
    
    return result["tenant_access_token"]


def api_request(method: str, url: str, token: str, **kwargs) -> Dict:
    """通用 API 请求"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.request(method, url, headers=headers, **kwargs)
    result = response.json()
    
    if result.get("code") != 0:
        raise Exception(f"API 请求失败：{result}")
    
    return result


# ============================================================
# 日报 API
# ============================================================

def daily_add(
    user_id: str,
    date: str,
    project: str,
    content: str,
    hours: float,
    table_id: str = DAILY_TABLE_ID
) -> Dict:
    """
    录入日报
    
    Args:
        user_id: 用户飞书 ID (ou_xxx)
        date: 日期 (YYYY-MM-DD)
        project: 项目名称
        content: 工作内容
        hours: 工时
        table_id: 表 ID
    
    Returns:
        {"record_id": "...", "success": True}
    """
    config = load_config()
    token = get_tenant_token(config)
    
    # 获取项目关联记录 ID
    project_record_id = _get_project_record_id(config, token, project)
    
    # 构建字段
    fields = {
        "日期": date,
        "姓名": [{"id": user_id}],
        "项目": project,
        "工作内容": content,
        "时长": str(hours)
    }
    
    # 关联项目（如果有）- 日报表没有关联项目字段，跳过
    # if project_record_id:
    #     fields["关联项目"] = [project_record_id]
    
    # 创建记录
    url = f"{config['BASE_URL']}/bitable/v1/apps/{config['APP_TOKEN']}/tables/{table_id}/records"
    payload = {"fields": fields}
    
    result = api_request("POST", url, token, json=payload)
    
    return {
        "record_id": result["data"]["record"]["record_id"],
        "success": True
    }


def daily_query(
    user_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
    table_id: str = DAILY_TABLE_ID
) -> List[Dict]:
    """
    查询日报
    
    Args:
        user_id: 用户飞书 ID（可选，筛选特定用户）
        date_from: 开始日期（可选）
        date_to: 结束日期（可选）
        limit: 返回数量限制
        table_id: 表 ID
    
    Returns:
        日报记录列表
    """
    config = load_config()
    token = get_tenant_token(config)
    
    # 构建筛选条件
    filter_conditions = []
    
    if user_id:
        filter_conditions.append({
            "conjunction": "and",
            "conditions": [{
                "field_name": "姓名",
                "operator": "in",
                "value": [user_id]
            }]
        })
    
    if date_from:
        filter_conditions.append({
            "conjunction": "and",
            "conditions": [{
                "field_name": "日期",
                "operator": ">=",
                "value": date_from
            }]
        })
    
    if date_to:
        filter_conditions.append({
            "conjunction": "and",
            "conditions": [{
                "field_name": "日期",
                "operator": "<=",
                "value": date_to
            }]
        })
    
    # 查询记录
    url = f"{config['BASE_URL']}/bitable/v1/apps/{config['APP_TOKEN']}/tables/{table_id}/records"
    params = {"page_size": min(limit, 100)}
    
    if filter_conditions:
        params["filter"] = json.dumps({
            "conjunction": "and",
            "conditions": filter_conditions
        })
    
    result = api_request("GET", url, token, params=params)
    
    items = result["data"].get("items", [])
    return items[:limit]


def daily_update(
    record_id: str,
    fields: Dict,
    table_id: str = DAILY_TABLE_ID
) -> Dict:
    """
    更新日报
    
    Args:
        record_id: 记录 ID
        fields: 要更新的字段（如 {"时长": "8", "工作内容": "新内容"}）
        table_id: 表 ID
    
    Returns:
        {"record_id": "...", "success": True}
    """
    config = load_config()
    token = get_tenant_token(config)
    
    url = f"{config['BASE_URL']}/bitable/v1/apps/{config['APP_TOKEN']}/tables/{table_id}/records/{record_id}"
    payload = {"fields": fields}
    
    result = api_request("PUT", url, token, json=payload)
    
    return {
        "record_id": result["data"]["record"]["record_id"],
        "success": True
    }


def daily_delete(
    record_id: str,
    table_id: str = DAILY_TABLE_ID
) -> Dict:
    """
    删除日报
    
    Args:
        record_id: 记录 ID
        table_id: 表 ID
    
    Returns:
        {"success": True}
    """
    config = load_config()
    token = get_tenant_token(config)
    
    url = f"{config['BASE_URL']}/bitable/v1/apps/{config['APP_TOKEN']}/tables/{table_id}/records/{record_id}"
    
    result = api_request("DELETE", url, token)
    
    return {"success": True}


# ============================================================
# 任务 API
# ============================================================

def task_add(
    name: str,
    serial: int,
    project: str,
    executor: str,
    status: str,
    deadline: int,
    hours: float,
    description: str = "",
    table_id: str = TASK_TABLE_ID
) -> Dict:
    """
    录入任务
    
    Args:
        name: 任务名称
        serial: 序号
        project: 项目记录 ID (rec_xxx)
        executor: 执行人飞书 ID (ou_xxx)
        status: 状态（如 "进行中"）
        deadline: 截止日期（毫秒时间戳）
        hours: 预计耗时
        description: 任务描述
        table_id: 表 ID
    
    Returns:
        {"record_id": "...", "success": True}
    """
    config = load_config()
    token = get_tenant_token(config)
    
    # 构建字段
    fields = {
        "任务名称": name,
        "序号": serial,
        "所属项目": [project],  # 关联字段
        "执行人": [{"id": executor}],
        "状态": [status],  # 多选字段
        "计划截止时间": deadline,
        "预计耗时": hours,
        "说明": description
    }
    
    # 创建记录
    url = f"{config['BASE_URL']}/bitable/v1/apps/{config['APP_TOKEN']}/tables/{table_id}/records"
    payload = {"fields": fields}
    
    result = api_request("POST", url, token, json=payload)
    
    return {
        "record_id": result["data"]["record"]["record_id"],
        "success": True
    }


def task_query(
    executor: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10,
    table_id: str = TASK_TABLE_ID
) -> List[Dict]:
    """
    查询任务
    
    Args:
        executor: 执行人飞书 ID（可选）
        status: 状态（可选）
        limit: 返回数量限制
        table_id: 表 ID
    
    Returns:
        任务记录列表
    """
    config = load_config()
    token = get_tenant_token(config)
    
    # 构建筛选条件
    filter_conditions = []
    
    if executor:
        filter_conditions.append({
            "conjunction": "and",
            "conditions": [{
                "field_name": "执行人",
                "operator": "in",
                "value": [executor]
            }]
        })
    
    if status:
        filter_conditions.append({
            "conjunction": "and",
            "conditions": [{
                "field_name": "状态",
                "operator": "in",
                "value": [status]
            }]
        })
    
    # 查询记录
    url = f"{config['BASE_URL']}/bitable/v1/apps/{config['APP_TOKEN']}/tables/{table_id}/records"
    params = {"page_size": min(limit, 100)}
    
    if filter_conditions:
        params["filter"] = json.dumps({
            "conjunction": "and",
            "conditions": filter_conditions
        })
    
    result = api_request("GET", url, token, params=params)
    
    items = result["data"].get("items", [])
    return items[:limit]


def task_update(
    record_id: str,
    fields: Dict,
    table_id: str = TASK_TABLE_ID
) -> Dict:
    """
    更新任务
    
    Args:
        record_id: 记录 ID
        fields: 要更新的字段
        table_id: 表 ID
    
    Returns:
        {"record_id": "...", "success": True}
    """
    config = load_config()
    token = get_tenant_token(config)
    
    url = f"{config['BASE_URL']}/bitable/v1/apps/{config['APP_TOKEN']}/tables/{table_id}/records/{record_id}"
    payload = {"fields": fields}
    
    result = api_request("PUT", url, token, json=payload)
    
    return {
        "record_id": result["data"]["record"]["record_id"],
        "success": True
    }


def task_delete(
    record_id: str,
    table_id: str = TASK_TABLE_ID
) -> Dict:
    """
    删除任务
    
    Args:
        record_id: 记录 ID
        table_id: 表 ID
    
    Returns:
        {"success": True}
    """
    config = load_config()
    token = get_tenant_token(config)
    
    url = f"{config['BASE_URL']}/bitable/v1/apps/{config['APP_TOKEN']}/tables/{table_id}/records/{record_id}"
    
    result = api_request("DELETE", url, token)
    
    return {"success": True}


# ============================================================
# 辅助函数
# ============================================================

def _get_project_record_id(config: Dict, token: str, project_name: str) -> Optional[str]:
    """根据项目名称获取关联记录 ID"""
    # 简化实现：返回默认项目记录 ID
    # 实际应该查询项目表
    project_map = {
        "HiperOne": DEFAULT_PROJECT_RECORD,
        "HiperOne 项目": DEFAULT_PROJECT_RECORD,
    }
    return project_map.get(project_name)


def get_fields(table_id: str) -> List[Dict]:
    """
    获取表字段定义
    
    Args:
        table_id: 表 ID
    
    Returns:
        字段定义列表
    """
    config = load_config()
    token = get_tenant_token(config)
    
    url = f"{config['BASE_URL']}/bitable/v1/apps/{config['APP_TOKEN']}/tables/{table_id}/fields"
    
    result = api_request("GET", url, token)
    
    return result["data"].get("items", [])


# ============================================================
# 便捷函数
# ============================================================

def add_daily(user_id: str, date: str, project: str, content: str, hours: float) -> Dict:
    """日报录入便捷函数"""
    return daily_add(user_id, date, project, content, hours)


def add_task(name: str, serial: int, project: str, executor: str, status: str, 
             deadline_days: int, hours: float, description: str = "") -> Dict:
    """
    任务录入便捷函数
    
    Args:
        deadline_days: 截止日期（从今天起的天数）
    """
    # 计算截止日期（毫秒时间戳）
    deadline = int((datetime.now() + timedelta(days=deadline_days)).timestamp() * 1000)
    
    return task_add(name, serial, project, executor, status, deadline, hours, description)


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import sys
    
    print("Feishu Bitable API")
    print("="*50)
    print("请使用命令行工具：python3 scripts/bitable.py")
    print("或直接导入本模块使用 Python API")
    print()
    print("示例:")
    print("  from feishu_bitable import daily_add, task_query")
    print("  result = daily_add('ou_xxx', '2026-03-06', 'HiperOne', '工作内容', 2)")
    print("  tasks = task_query(executor='ou_xxx', limit=5)")
