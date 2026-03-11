#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feishu-approval-leave - 飞书请假审批工具

调用飞书审批 API v4 创建/查询/撤回请假审批实例。
凭据通过环境变量获取（与其他飞书 skill 共用）：
  NANOBOT_CHANNELS__FEISHU__APP_ID
  NANOBOT_CHANNELS__FEISHU__APP_SECRET

注意：user_id 参数实际使用 open_id 值（企业可能未配置自定义 user_id）
"""

import os
import requests
import json
import argparse
from typing import Dict, Any, Optional, List

BASE_URL = "https://open.feishu.cn/open-apis"
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


def load_config() -> Dict[str, str]:
    """从环境变量加载飞书凭据"""
    app_id = os.environ.get("NANOBOT_CHANNELS__FEISHU__APP_ID", "")
    app_secret = os.environ.get("NANOBOT_CHANNELS__FEISHU__APP_SECRET", "")
    if not app_id or not app_secret:
        raise Exception(
            "缺少飞书凭据，请设置环境变量 "
            "NANOBOT_CHANNELS__FEISHU__APP_ID / NANOBOT_CHANNELS__FEISHU__APP_SECRET"
        )
    return {"app_id": app_id, "app_secret": app_secret}


def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    """获取 tenant_access_token"""
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
    result = resp.json()
    if result.get("code") != 0:
        raise Exception(f"获取 token 失败：{result}")
    return result["tenant_access_token"]


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
    """
    创建请假审批实例

    Args:
        approval_code: 审批模板码
        user_id: 申请人的 open_id
        leave_type: 假期类型名称（如"年假"）或 leave_id
        start_time: 开始时间 (RFC3339)
        end_time: 结束时间 (RFC3339)
        reason: 请假事由
        unit: 时长单位 (DAY / HOUR / HALF_DAY)
        interval: 时长计算方式

    Returns:
        {"success": bool, "instance_code": str, "instance_id": str, "error": str}
    """
    config = load_config()
    token = get_tenant_access_token(config["app_id"], config["app_secret"])

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

    payload = {
        "approval_code": approval_code,
        "open_id": user_id,
        "form": json.dumps(form_array, ensure_ascii=False),
    }

    url = f"{BASE_URL}/approval/v4/instances"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        result = resp.json()

        if result.get("code") == 0:
            data = result.get("data", {})
            return {
                "success": True,
                "instance_code": data.get("instance_code", "N/A"),
                "instance_id": data.get("instance_id", "N/A"),
                "data": data,
            }
        else:
            return {
                "success": False,
                "error": f"{result.get('code')}: {result.get('msg', 'Unknown error')}",
                "data": result.get("data"),
            }
    except Exception as e:
        return {"success": False, "error": f"请求异常：{e}"}


def cancel_approval_instance(
    instance_code: str,
    user_id: str,
    approval_code: str = DEFAULT_APPROVAL_CODE,
    reason: str = "",
) -> Dict[str, Any]:
    """
    撤回审批实例

    Args:
        instance_code: 审批实例码
        user_id: 操作人的 open_id
        approval_code: 审批模板码
        reason: 撤回原因（可选）

    Returns:
        {"success": bool, "error": str}
    """
    config = load_config()
    token = get_tenant_access_token(config["app_id"], config["app_secret"])

    payload = {
        "approval_code": approval_code,
        "instance_code": instance_code,
        "user_id": user_id,
    }
    if reason:
        payload["reason"] = reason

    url = f"{BASE_URL}/approval/v4/instances/cancel?user_id_type=open_id"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        result = resp.json()

        if result.get("code") == 0:
            return {"success": True}
        else:
            return {
                "success": False,
                "error": f"{result.get('code')}: {result.get('msg', 'Unknown error')}",
            }
    except Exception as e:
        return {"success": False, "error": f"请求异常：{e}"}


def get_approval_instance(
    instance_code: str,
) -> Dict[str, Any]:
    """
    获取单个审批实例详情

    Args:
        instance_code: 审批实例码

    Returns:
        {"success": bool, "data": dict, "error": str}
    """
    config = load_config()
    token = get_tenant_access_token(config["app_id"], config["app_secret"])

    url = f"{BASE_URL}/approval/v4/instances/{instance_code}"
    headers = {
        "Authorization": f"Bearer {token}",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        result = resp.json()

        if result.get("code") == 0:
            data = result.get("data", {})
            return {"success": True, "data": data}
        else:
            return {
                "success": False,
                "error": f"{result.get('code')}: {result.get('msg', 'Unknown error')}",
            }
    except Exception as e:
        return {"success": False, "error": f"请求异常：{e}"}


def list_approval_instances(
    approval_code: str = DEFAULT_APPROVAL_CODE,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page_size: int = 100,
    page_token: str = "",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    批量获取审批实例 ID

    Args:
        approval_code: 审批模板码
        start_time: 开始时间戳（毫秒）或 ISO 格式
        end_time: 结束时间戳（毫秒）或 ISO 格式
        page_size: 每页数量（默认 100，最大 100）
        page_token: 分页令牌
        user_id: 申请人 open_id（可选，筛选特定用户）

    Returns:
        {"success": bool, "instances": list, "has_more": bool, "page_token": str, "error": str}
    """
    config = load_config()
    token = get_tenant_access_token(config["app_id"], config["app_secret"])

    params = {
        "approval_code": approval_code,
        "page_size": page_size,
    }
    if page_token:
        params["page_token"] = page_token
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    if user_id:
        params["user_id"] = user_id

    url = f"{BASE_URL}/approval/v4/instances"
    headers = {
        "Authorization": f"Bearer {token}",
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        result = resp.json()

        if result.get("code") == 0:
            data = result.get("data", {})
            return {
                "success": True,
                "instances": data.get("instance_code_list", []),
                "has_more": data.get("has_more", False),
                "page_token": data.get("page_token", ""),
            }
        else:
            return {
                "success": False,
                "error": f"{result.get('code')}: {result.get('msg', 'Unknown error')}",
            }
    except Exception as e:
        return {"success": False, "error": f"请求异常：{e}"}


def main():
    parser = argparse.ArgumentParser(
        description="飞书请假审批工具 - 创建/查询/撤回审批实例",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
凭据通过环境变量获取（与其他飞书 skill 共用）：
  NANOBOT_CHANNELS__FEISHU__APP_ID
  NANOBOT_CHANNELS__FEISHU__APP_SECRET

注意：user_id 参数实际使用 open_id 值（企业可能未配置自定义 user_id）

示例:
  # 创建请假审批
  python feishu_approval_leave.py create \\
    --user-id ou_xxxxxxxxxxxx \\
    --leave-type 年假 \\
    --start-time "2026-03-11T09:00:00+08:00" \\
    --end-time "2026-03-11T18:00:00+08:00" \\
    --reason "API 测试"

  # 撤回审批实例
  python feishu_approval_leave.py cancel \\
    --instance-code 983DE237-3ED0-4649-80AE-332471ADA41A \\
    --user-id ou_xxxxxxxxxxxx \\
    --reason "撤销申请"

  # 获取审批实例详情
  python feishu_approval_leave.py get \\
    --instance-code 983DE237-3ED0-4649-80AE-332471ADA41A

  # 批量获取审批实例
  python feishu_approval_leave.py list \\
    --user-id ou_xxxxxxxxxxxx \\
    --start-time "1710000000000" \\
    --end-time "1710100000000"
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # create 子命令
    create_parser = subparsers.add_parser("create", help="创建请假审批实例")
    create_parser.add_argument("--approval-code", default=DEFAULT_APPROVAL_CODE, help=f"审批模板码 (默认：{DEFAULT_APPROVAL_CODE})")
    create_parser.add_argument("--user-id", required=True, help="申请人的 open_id")
    create_parser.add_argument("--leave-type", required=True, help="假期类型 (如：年假、事假、病假)")
    create_parser.add_argument("--start-time", required=True, help="开始时间 (RFC3339 格式)")
    create_parser.add_argument("--end-time", required=True, help="结束时间 (RFC3339 格式)")
    create_parser.add_argument("--reason", required=True, help="请假事由")
    create_parser.add_argument("--unit", default="DAY", choices=["DAY", "HOUR", "HALF_DAY"], help="时长单位 (默认：DAY)")
    create_parser.add_argument("--interval", default="1", help="时长计算方式 (默认：1)")

    # cancel 子命令
    cancel_parser = subparsers.add_parser("cancel", help="撤回审批实例")
    cancel_parser.add_argument("--instance-code", required=True, help="审批实例码")
    cancel_parser.add_argument("--approval-code", default=DEFAULT_APPROVAL_CODE, help=f"审批模板码 (默认：{DEFAULT_APPROVAL_CODE})")
    cancel_parser.add_argument("--user-id", required=True, help="操作人的 open_id")
    cancel_parser.add_argument("--reason", default="", help="撤回原因（可选）")

    # get 子命令
    get_parser = subparsers.add_parser("get", help="获取审批实例详情")
    get_parser.add_argument("--instance-code", required=True, help="审批实例码")

    # list 子命令
    list_parser = subparsers.add_parser("list", help="批量获取审批实例")
    list_parser.add_argument("--approval-code", default=DEFAULT_APPROVAL_CODE, help=f"审批模板码 (默认：{DEFAULT_APPROVAL_CODE})")
    list_parser.add_argument("--start-time", help="开始时间戳（毫秒）或 ISO 格式")
    list_parser.add_argument("--end-time", help="结束时间戳（毫秒）或 ISO 格式")
    list_parser.add_argument("--page-size", type=int, default=100, help="每页数量 (默认：100, 最大：100)")
    list_parser.add_argument("--page-token", default="", help="分页令牌")
    list_parser.add_argument("--user-id", help="申请人 open_id（可选，筛选特定用户）")

    # 全局参数
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细输出")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "create":
        if args.verbose:
            print("=" * 70)
            print("飞书请假审批创建")
            print("=" * 70)
            print(f"  审批模板：{args.approval_code}")
            print(f"  open_id: {args.user_id}")
            print(f"  假期类型：{args.leave_type}")
            print(f"  时间：{args.start_time} - {args.end_time}")
            print(f"  事由：{args.reason}")
            print()

        result = create_leave_approval(
            approval_code=args.approval_code,
            user_id=args.user_id,
            leave_type=args.leave_type,
            start_time=args.start_time,
            end_time=args.end_time,
            reason=args.reason,
            unit=args.unit,
            interval=args.interval,
        )

        if result["success"]:
            print(f"✅ 审批实例创建成功")
            print(f"   实例码：{result['instance_code']}")
            print(f"   实例 ID: {result['instance_id']}")
            return 0
        else:
            print(f"❌ 创建失败")
            print(f"   错误：{result['error']}")
            if result.get("data"):
                print(f"   详情：{result['data']}")
            return 1

    elif args.command == "cancel":
        if args.verbose:
            print("=" * 70)
            print("撤回审批实例")
            print("=" * 70)
            print(f"  实例码：{args.instance_code}")
            print(f"  审批模板：{args.approval_code}")
            print(f"  操作人：{args.user_id}")
            print(f"  原因：{args.reason or '无'}")
            print()

        result = cancel_approval_instance(
            instance_code=args.instance_code,
            approval_code=args.approval_code,
            user_id=args.user_id,
            reason=args.reason,
        )

        if result["success"]:
            print(f"✅ 审批实例已撤回")
            return 0
        else:
            print(f"❌ 撤回失败")
            print(f"   错误：{result['error']}")
            return 1

    elif args.command == "get":
        if args.verbose:
            print("=" * 70)
            print("获取审批实例详情")
            print("=" * 70)
            print(f"  实例码：{args.instance_code}")
            print()

        result = get_approval_instance(instance_code=args.instance_code)

        if result["success"]:
            print(f"✅ 获取成功")
            print(json.dumps(result["data"], indent=2, ensure_ascii=False))
            return 0
        else:
            print(f"❌ 获取失败")
            print(f"   错误：{result['error']}")
            return 1

    elif args.command == "list":
        if args.verbose:
            print("=" * 70)
            print("批量获取审批实例")
            print("=" * 70)
            print(f"  审批模板：{args.approval_code}")
            print(f"  时间范围：{args.start_time or '无'} - {args.end_time or '无'}")
            print(f"  用户：{args.user_id or '全部'}")
            print(f"  页大小：{args.page_size}")
            print()

        result = list_approval_instances(
            approval_code=args.approval_code,
            start_time=args.start_time,
            end_time=args.end_time,
            page_size=args.page_size,
            page_token=args.page_token,
            user_id=args.user_id,
        )

        if result["success"]:
            print(f"✅ 获取成功")
            print(f"   实例数量：{len(result['instances'])}")
            print(f"   更多数据：{'是' if result['has_more'] else '否'}")
            if result["page_token"]:
                print(f"   下一页 token: {result['page_token']}")
            print()
            for inst_code in result["instances"]:
                print(f"   - {inst_code}")
            return 0
        else:
            print(f"❌ 获取失败")
            print(f"   错误：{result['error']}")
            return 1

    return 0


if __name__ == "__main__":
    exit(main())
