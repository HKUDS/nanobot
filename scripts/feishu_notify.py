#!/usr/bin/env python3
"""
飞书机器人推送通知
用法: python feishu_notify.py --webhook "YOUR_WEBHOOK" --message "消息内容"
"""
import json
import argparse
import requests
from datetime import datetime


def send_message(webhook: str, message: str, msg_type: str = "text") -> bool:
    """发送飞书消息"""

    if msg_type == "text":
        payload = {
            "msg_type": "text",
            "content": {
                "text": message
            }
        }
    elif msg_type == "post":
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": message.get("title", ""),
                        "content": message.get("content", [])
                    }
                }
            }
        }
    else:
        print(f"不支持的消息类型: {msg_type}")
        return False

    try:
        response = requests.post(webhook, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                print("消息发送成功")
                return True
            else:
                print(f"发送失败: {result.get('msg', '未知错误')}")
                return False
        else:
            print(f"HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"发送异常: {e}")
        return False


def send_card(webhook: str, title: str, content: str, color: str = "green") -> bool:
    """发送卡片消息"""

    colors = {
        "green": "green",
        "red": "red",
        "blue": "blue",
        "yellow": "yellow",
        "grey": "grey"
    }

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": colors.get(color, "green")
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "查看详情"
                            },
                            "type": "primary",
                            "url": "https://example.com"
                        }
                    ]
                }
            ]
        }
    }

    try:
        response = requests.post(webhook, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            return result.get("code") == 0
        return False
    except Exception as e:
        print(f"发送异常: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="飞书机器人推送")
    parser.add_argument("--webhook", required=True, help="飞书机器人 Webhook URL")
    parser.add_argument("--message", required=True, help="消息内容")
    parser.add_argument("--type", default="text", choices=["text", "card"], help="消息类型")
    parser.add_argument("--title", help="卡片标题")
    parser.add_argument("--color", default="green", choices=["green", "red", "blue", "yellow", "grey"], help="卡片颜色")
    args = parser.parse_args()

    if args.type == "card":
        if not args.title:
            print("卡片消息需要 --title 参数")
            return
        send_card(args.webhook, args.title, args.message, args.color)
    else:
        send_message(args.webhook, args.message, args.type)


if __name__ == "__main__":
    main()
