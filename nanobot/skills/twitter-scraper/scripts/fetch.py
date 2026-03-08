#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitter/X 抓取工具 - 可直接调用版本

此脚本通过 OpenClaw browser 工具抓取推文

使用方法:
    python3 skills/twitter_scraper/scripts/fetch.py --user sama --max 5
    python3 skills/twitter_scraper/scripts/fetch.py --users sama,gdb,elonmusk
    
注意: 此脚本需要在 OpenClaw 环境中运行，使用 browser 工具
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 添加技能目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from skills.twitter_scraper.scripts.scraper import parse_tweets_from_html, save_tweets


def fetch_with_browser(username: str, max_tweets: int = 10) -> list:
    """
    使用 OpenClaw browser 工具抓取推文
    
    注意：此函数需要在 OpenClaw 环境中执行
    """
    print(f"🔍 正在抓取 @{username} 的推文...")
    print(f"   目标: 获取 {max_tweets} 条最新推文")
    print(f"   来源: https://xcancel.com/{username}")
    
    # 这里只是占位，实际需要使用 browser 工具
    # 在 OpenClaw 环境中调用方式：
    # 1. browser open "https://xcancel.com/{username}"
    # 2. browser act wait 3000
    # 3. browser snapshot
    # 4. 解析 HTML 获取推文
    
    print("\n⚠️  提示：此脚本需要在 OpenClaw Agent 环境中运行")
    print("   请使用以下方式调用：")
    print(f"""
   browser open "https://xcancel.com/{username}"
   browser act wait 3000
   browser snapshot
   
   然后使用 scraper.py 中的 parse_tweets_from_html() 解析
   """)
    
    return []


def main():
    parser = argparse.ArgumentParser(description='Twitter/X 推文抓取工具')
    parser.add_argument('--user', '-u', type=str, help='抓取单个用户')
    parser.add_argument('--users', type=str, help='批量抓取，逗号分隔用户名')
    parser.add_argument('--max', '-m', type=int, default=10, help='最大抓取数量 (默认: 10)')
    parser.add_argument('--output', '-o', type=str, help='输出文件路径 (JSON)')
    
    args = parser.parse_args()
    
    if not args.user and not args.users:
        parser.print_help()
        print("\n❌ 错误: 需要指定 --user 或 --users 参数")
        sys.exit(1)
    
    # 确定要抓取的用户列表
    if args.users:
        users = [u.strip() for u in args.users.split(',')]
    else:
        users = [args.user]
    
    print("🚀 Twitter/X 抓取工具")
    print("=" * 50)
    print(f"目标账号: {', '.join(users)}")
    print(f"抓取数量: {args.max} 条/账号")
    print("=" * 50)
    
    all_tweets = []
    for username in users:
        tweets = fetch_with_browser(username, args.max)
        all_tweets.extend(tweets)
        print(f"@{username}: 获取 {len(tweets)} 条推文\n")
    
    # 保存结果
    if args.output:
        save_tweets(all_tweets, args.output)
    else:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        default_output = f"twitter_data_{timestamp}.json"
        save_tweets(all_tweets, default_output)
    
    print(f"\n✅ 完成! 共获取 {len(all_tweets)} 条推文")


if __name__ == "__main__":
    main()
