#!/usr/bin/env python3
"""
Feishu Bitable CLI - 飞书多维表命令行工具
支持日报和任务的增删改查操作
"""

import argparse
import json
import os
import sys
import requests
from datetime import datetime, timedelta


# ============================================================
# 配置常量
# ============================================================
APP_ID = os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_ID', '')
APP_SECRET = os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_SECRET', '')
APP_TOKEN = "JXdtbkkchaSXmksx6eFc2Eatn45"
BASE_URL = "https://open.feishu.cn/open-apis"

DAILY_TABLE_ID = "tblYWOnDxGsVSfDN"       # 日报表
TASK_TABLE_ID = "tblH6xn2dp6E1UtD"        # 任务表 1 (状态=多选)
TASK_TABLE_ID_2 = "tblszl72smxKsxY4"      # 任务表 2 (状态=单选)
PROJECT_TABLE_ID = "tblvcGZsmzHcCF"       # 项目表


# ============================================================
# 核心 API 函数
# ============================================================

def get_tenant_access_token():
    """获取飞书 tenant_access_token，有效期 2 小时"""
    if not APP_ID or not APP_SECRET:
        raise Exception("缺少飞书凭据，请设置环境变量 NANOBOT_CHANNELS__FEISHU__APP_ID / NANOBOT_CHANNELS__FEISHU__APP_SECRET")
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    resp = requests.post(url, json=payload)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取 Token 失败：{data}")
    return data["tenant_access_token"]


def get_table_fields(table_id):
    """获取指定表的字段定义"""
    token = get_tenant_access_token()
    url = f"{BASE_URL}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/fields"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取字段失败：{data}")
    return data["data"]


def add_record(table_id, fields):
    """创建新记录"""
    token = get_tenant_access_token()
    url = f"{BASE_URL}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {"fields": fields}
    resp = requests.post(url, json=payload, headers=headers)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"创建记录失败：{data}")
    record = data["data"]["record"]
    return {"record_id": record["record_id"], "fields": fields}


def update_record(table_id, record_id, fields):
    """更新现有记录"""
    token = get_tenant_access_token()
    url = f"{BASE_URL}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {"fields": fields}
    resp = requests.put(url, json=payload, headers=headers)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"更新记录失败：{data}")
    return {"record_id": record_id, "fields": fields}


def query_records(table_id, page_size=20, filter=None):
    """查询记录"""
    token = get_tenant_access_token()
    url = f"{BASE_URL}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"page_size": page_size}
    if filter:
        params["filter"] = json.dumps(filter)
    resp = requests.get(url, headers=headers, params=params)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"查询记录失败：{data}")
    return data["data"]


def delete_record(table_id, record_id):
    """删除记录"""
    token = get_tenant_access_token()
    url = f"{BASE_URL}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.delete(url, headers=headers)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"删除记录失败：{data}")
    return True


def add_daily_report(user_id, date, project, content, hours):
    """录入日报（便捷函数）"""
    fields = {
        "姓名": [{"id": user_id}],
        "日期": date,
        "项目": project,
        "工作内容": content,
        "时长": str(hours)
    }
    result = add_record(DAILY_TABLE_ID, fields)
    return result


def add_task(task_name, serial_number, project_record_id, executor_id, 
             status, deadline_days, estimated_hours, description="", 
             table_id=TASK_TABLE_ID):
    """录入任务（便捷函数）"""
    # 获取字段定义以确定状态字段类型
    fields_info = get_table_fields(table_id)
    status_field_type = None
    for f in fields_info.get("items", []):
        if f["field_name"] == "状态":
            status_field_type = f["type"]
            break
    
    # 根据状态字段类型构造值（多选=列表，单选=字符串）
    if status_field_type == 4:  # 多选
        status_value = [status]
    else:  # 单选或其他
        status_value = status
    
    # 计算截止时间（毫秒时间戳）
    deadline = int((datetime.now() + timedelta(days=deadline_days)).timestamp() * 1000)
    
    fields = {
        "任务名称": task_name,
        "序号": serial_number,
        "所属项目": [project_record_id],
        "执行人": [{"id": executor_id}],
        "状态": status_value,
        "计划截止时间": deadline,
        "预计耗时": estimated_hours,
        "说明": description
    }
    
    result = add_record(table_id, fields)
    return result


# ============================================================
# 命令行处理函数
# ============================================================

def cmd_daily_add(args):
    """录入日报"""
    result = add_daily_report(
        user_id=args.user_id,
        date=args.date,
        project=args.project,
        content=args.content,
        hours=args.hours
    )
    print(f"✅ 日报创建成功")
    print(f"   record_id: {result['record_id']}")
    print(f"   项目：{result['fields'].get('项目')}")
    print(f"   工作内容：{result['fields'].get('工作内容')}")
    return result


def cmd_daily_query(args):
    """查询日报"""
    result = query_records(DAILY_TABLE_ID, page_size=args.limit)
    items = result.get('items', [])
    print(f"📋 查询到 {len(items)} 条日报记录\n")
    
    for i, item in enumerate(items, 1):
        record_id = item.get('record_id', 'N/A')
        fields = item.get('fields', {})
        date_val = fields.get('日期') or 'N/A'
        name_val = fields.get('姓名') or 'N/A'
        project_val = fields.get('项目') or 'N/A'
        content_val = fields.get('工作内容') or 'N/A'
        hours_val = fields.get('时长') or 'N/A'
        
        print(f"[{i}] {record_id} | {date_val}")
        name_str = name_val[0].get('name', 'N/A') if isinstance(name_val, list) and name_val else str(name_val)
        print(f"    姓名：{name_str}")
        print(f"    项目：{project_val}")
        content_str = content_val[:50] if isinstance(content_val, str) else str(content_val)
        print(f"    内容：{content_str}")
        print(f"    时长：{hours_val} 小时")
        print()
    
    return items


def cmd_daily_update(args):
    """更新日报"""
    fields = json.loads(args.fields)
    result = update_record(DAILY_TABLE_ID, args.record_id, fields)
    print(f"✅ 日报更新成功")
    print(f"   record_id: {result['record_id']}")
    return result


def cmd_daily_delete(args):
    """删除日报"""
    success = delete_record(DAILY_TABLE_ID, args.record_id)
    if success:
        print(f"✅ 日报已删除：{args.record_id}")
    return success


def cmd_task_add(args):
    """录入任务"""
    result = add_task(
        task_name=args.name,
        serial_number=args.serial,
        project_record_id=args.project,
        executor_id=args.executor,
        status=args.status,
        deadline_days=args.deadline,
        estimated_hours=args.hours,
        description=args.description or "",
        table_id=args.table or TASK_TABLE_ID
    )
    print(f"✅ 任务创建成功")
    print(f"   record_id: {result['record_id']}")
    print(f"   任务名称：{result['fields'].get('任务名称')}")
    print(f"   状态：{result['fields'].get('状态')}")
    print(f"   预计耗时：{result['fields'].get('预计耗时')}")
    return result


def cmd_task_query(args):
    """查询任务"""
    table_id = args.table or TASK_TABLE_ID
    result = query_records(table_id, page_size=args.limit)
    items = result.get('items', [])
    print(f"📋 查询到 {len(items)} 条任务记录\n")
    
    for i, item in enumerate(items, 1):
        record_id = item.get('record_id', 'N/A')
        fields = item.get('fields', {})
        name_val = fields.get('任务名称') or 'N/A'
        serial_val = fields.get('序号') or 'N/A'
        status_val = fields.get('状态') or 'N/A'
        executor_val = fields.get('执行人') or 'N/A'
        hours_val = fields.get('预计耗时') or 'N/A'
        
        print(f"[{i}] {record_id} | {name_val}")
        print(f"    序号：{serial_val}")
        status_str = status_val[0] if isinstance(status_val, list) and status_val else str(status_val)
        print(f"    状态：{status_str}")
        executor_str = executor_val[0].get('name', 'N/A') if isinstance(executor_val, list) and executor_val else str(executor_val)
        print(f"    执行人：{executor_str}")
        print(f"    预计耗时：{hours_val}")
        print()
    
    return items


def cmd_task_update(args):
    """更新任务"""
    fields = json.loads(args.fields)
    table_id = args.table or TASK_TABLE_ID
    result = update_record(table_id, args.record_id, fields)
    print(f"✅ 任务更新成功")
    print(f"   record_id: {result['record_id']}")
    return result


def cmd_task_delete(args):
    """删除任务"""
    table_id = args.table or TASK_TABLE_ID
    success = delete_record(table_id, args.record_id)
    if success:
        print(f"✅ 任务已删除：{args.record_id}")
    return success


def cmd_fields(args):
    """获取字段定义"""
    fields = get_table_fields(args.table)
    items = fields.get('items', [])
    print(f"📊 表 {args.table} 共有 {len(items)} 个字段\n")
    
    for f in items:
        print(f"  - {f['field_name']} (类型：{f['type']})")
    
    return fields


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="飞书多维表命令行工具")
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # ===== daily 命令组 =====
    daily_parser = subparsers.add_parser('daily', help='日报操作')
    daily_subparsers = daily_parser.add_subparsers(dest='subcommand')
    
    # daily add
    daily_add = daily_subparsers.add_parser('add', help='录入日报')
    daily_add.add_argument('--user-id', required=True, help='用户飞书 ID')
    daily_add.add_argument('--date', required=True, help='日期 (YYYY-MM-DD)')
    daily_add.add_argument('--project', required=True, help='项目名称')
    daily_add.add_argument('--content', required=True, help='工作内容')
    daily_add.add_argument('--hours', required=True, help='时长 (小时)')
    daily_add.set_defaults(func=cmd_daily_add)
    
    # daily query
    daily_query = daily_subparsers.add_parser('query', help='查询日报')
    daily_query.add_argument('--limit', type=int, default=10, help='返回数量')
    daily_query.set_defaults(func=cmd_daily_query)
    
    # daily update
    daily_update = daily_subparsers.add_parser('update', help='更新日报')
    daily_update.add_argument('--record-id', required=True, help='记录 ID')
    daily_update.add_argument('--fields', required=True, help='字段 JSON')
    daily_update.set_defaults(func=cmd_daily_update)
    
    # daily delete
    daily_delete = daily_subparsers.add_parser('delete', help='删除日报')
    daily_delete.add_argument('--record-id', required=True, help='记录 ID')
    daily_delete.set_defaults(func=cmd_daily_delete)
    
    # ===== task 命令组 =====
    task_parser = subparsers.add_parser('task', help='任务操作')
    task_subparsers = task_parser.add_subparsers(dest='subcommand')
    
    # task add
    task_add = task_subparsers.add_parser('add', help='录入任务')
    task_add.add_argument('--name', required=True, help='任务名称')
    task_add.add_argument('--serial', type=int, required=True, help='序号')
    task_add.add_argument('--project', required=True, help='项目记录 ID')
    task_add.add_argument('--executor', required=True, help='执行人飞书 ID')
    task_add.add_argument('--status', default='进行中', help='状态')
    task_add.add_argument('--deadline', type=int, default=7, help='截止天数')
    task_add.add_argument('--hours', type=int, default=2, help='预计耗时')
    task_add.add_argument('--description', help='任务说明')
    task_add.add_argument('--table', help='任务表 ID (默认 tblH6xn2dp6E1UtD)')
    task_add.set_defaults(func=cmd_task_add)
    
    # task query
    task_query = task_subparsers.add_parser('query', help='查询任务')
    task_query.add_argument('--limit', type=int, default=10, help='返回数量')
    task_query.add_argument('--table', help='任务表 ID')
    task_query.set_defaults(func=cmd_task_query)
    
    # task update
    task_update = task_subparsers.add_parser('update', help='更新任务')
    task_update.add_argument('--table', help='任务表 ID')
    task_update.add_argument('--record-id', required=True, help='记录 ID')
    task_update.add_argument('--fields', required=True, help='字段 JSON')
    task_update.set_defaults(func=cmd_task_update)
    
    # task delete
    task_delete = task_subparsers.add_parser('delete', help='删除任务')
    task_delete.add_argument('--table', help='任务表 ID')
    task_delete.add_argument('--record-id', required=True, help='记录 ID')
    task_delete.set_defaults(func=cmd_task_delete)
    
    # ===== fields 命令 =====
    fields_parser = subparsers.add_parser('fields', help='获取字段定义')
    fields_parser.add_argument('--table', required=True, help='表 ID')
    fields_parser.set_defaults(func=cmd_fields)
    
    # 解析参数
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command in ['daily', 'task'] and not args.subcommand:
        if args.command == 'daily':
            daily_parser.print_help()
        else:
            task_parser.print_help()
        sys.exit(1)
    
    # 执行命令
    if hasattr(args, 'func'):
        args.func(args)


if __name__ == '__main__':
    main()
