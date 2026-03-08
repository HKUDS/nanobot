#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书消息撤回工具
支持删除普通群消息和话题消息
"""

import requests
import json
import argparse
import sys
from pathlib import Path

import os
APP_ID = os.getenv("NANOBOT_CHANNELS__FEISHU__APP_ID")
APP_SECRET = os.getenv("NANOBOT_CHANNELS__FEISHU__APP_SECRET")


def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    """获取 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    data = {"app_id": app_id, "app_secret": app_secret}
    
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    
    if result.get("code") == 0:
        return result.get("tenant_access_token")
    else:
        raise Exception(f"获取 token 失败: {result}")


def delete_message(message_id: str, token: str = None) -> dict:
    """
    删除单条消息
    
    Args:
        message_id: 消息 ID
        token: 可选，tenant_access_token
    
    Returns:
        删除结果
    """
    if not token:
        token = get_tenant_access_token(APP_ID, APP_SECRET)
    
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.delete(url, headers=headers)
    
    try:
        result = response.json()
        return {
            "success": result.get("code") == 0,
            "code": result.get("code"),
            "msg": result.get("msg", ""),
            "message_id": message_id
        }
    except:
        return {
            "success": False,
            "code": -1,
            "msg": f"HTTP {response.status_code}",
            "message_id": message_id
        }


def get_thread_messages(thread_id: str, token: str = None) -> list:
    """
    获取话题中的所有消息
    
    Args:
        thread_id: 话题 ID
        token: 可选，tenant_access_token
    
    Returns:
        消息列表
    """
    if not token:
        token = get_tenant_access_token(APP_ID, APP_SECRET)
    
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "container_id": thread_id,
        "container_id_type": "thread",
        "sort_type": "ByCreateTimeAsc",
        "page_size": 50
    }
    
    response = requests.get(url, headers=headers, params=params)
    result = response.json()
    
    if result.get("code") == 0:
        return result.get("data", {}).get("items", [])
    else:
        raise Exception(f"获取话题消息失败: {result}")


def delete_thread_messages(thread_id: str, my_sender_id: str = None, token: str = None) -> dict:
    """
    批量删除话题中我发送的所有消息
    
    Args:
        thread_id: 话题 ID
        my_sender_id: 我的发送者 ID
        token: 可选，tenant_access_token
    
    Returns:
        删除结果统计
    """
    if my_sender_id is None:
        my_sender_id = APP_ID or ""
    if not token:
        token = get_tenant_access_token(APP_ID, APP_SECRET)
    
    # 获取话题中的所有消息
    messages = get_thread_messages(thread_id, token)
    
    # 找到我发送的消息
    my_messages = [msg for msg in messages if msg.get("sender", {}).get("id") == my_sender_id]
    
    # 批量删除
    success_count = 0
    failed_count = 0
    failed_msgs = []
    
    for msg in my_messages:
        msg_id = msg.get("message_id")
        result = delete_message(msg_id, token)
        
        if result["success"]:
            success_count += 1
        else:
            failed_count += 1
            failed_msgs.append({
                "message_id": msg_id,
                "error": result.get("msg", "Unknown error")
            })
    
    return {
        "success": success_count,
        "failed": failed_count,
        "total": len(my_messages),
        "failed_messages": failed_msgs
    }


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="飞书消息撤回工具")
    parser.add_argument("--msg-id", help="删除单条消息")
    parser.add_argument("--thread-id", help="删除话题中我发送的所有消息")
    parser.add_argument("--list-thread", help="查询话题中的消息")
    
    args = parser.parse_args()
    
    if args.msg_id:
        # 删除单条消息
        print(f"正在删除消息: {args.msg_id}")
        result = delete_message(args.msg_id)
        if result["success"]:
            print(f"✅ 删除成功")
        else:
            print(f"❌ 删除失败: {result.get('msg')}")
    
    elif args.thread_id:
        # 删除话题中的所有消息
        print(f"正在删除话题 {args.thread_id} 中我发送的消息...")
        results = delete_thread_messages(args.thread_id)
        print(f"删除结果: 成功 {results['success']} 条, 失败 {results['failed']} 条")
        
        if results["failed_messages"]:
            print("\n失败的消息:")
            for msg in results["failed_messages"]:
                print(f"  - {msg['message_id']}: {msg['error']}")
    
    elif args.list_thread:
        # 查询话题中的消息
        print(f"查询话题 {args.list_thread} 中的消息...")
        messages = get_thread_messages(args.list_thread)
        print(f"共 {len(messages)} 条消息\n")
        
        for i, msg in enumerate(messages[:10], 1):
            sender = msg.get("sender", {}).get("id", "")
            msg_type = msg.get("msg_type", "")
            print(f"[{i}] {msg.get('message_id')} - 发送者: {sender[:20]}... - 类型: {msg_type}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
