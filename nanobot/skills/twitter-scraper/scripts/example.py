#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitter/X Scraper Skill - 使用示例

此脚本演示如何在 OpenClaw 环境中使用 twitter-scraper skill
"""

import sys
from pathlib import Path

# 确保技能模块在路径中 - 从 scripts 目录向上两级到 workspace
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from skills.twitter_scraper.scripts.scraper import (
        parse_tweets_from_html,
        format_tweets_for_report,
        save_tweets
    )
except ImportError:
    # 直接导入
    import scraper
    parse_tweets_from_html = scraper.parse_tweets_from_html
    format_tweets_for_report = scraper.format_tweets_for_report
    save_tweets = scraper.save_tweets


def example_single_user():
    """示例1: 抓取单个用户"""
    print("=" * 60)
    print("示例 1: 抓取单个用户 (@sama)")
    print("=" * 60)
    
    # 在 OpenClaw 中执行:
    # 1. browser open "https://xcancel.com/sama"
    # 2. browser act wait 3000
    # 3. browser snapshot
    
    # 假设我们已经获取了 HTML 内容（实际使用时从 browser 获取）
    # html_content = browser_snapshot_html
    
    # tweets = parse_tweets_from_html(html_content, "sama")
    
    print("\n步骤:")
    print("1. browser open 'https://xcancel.com/sama'")
    print("2. browser act wait 3000")
    print("3. browser snapshot")
    print("4. 从 snapshot 中提取 HTML 并调用 parse_tweets_from_html()")
    
    print("\n预期输出:")
    print(format_tweets_for_report([]))  # 空列表作为示例


def example_batch_users():
    """示例2: 批量抓取多个用户"""
    print("\n" + "=" * 60)
    print("示例 2: 批量抓取多个用户")
    print("=" * 60)
    
    users = ["sama", "gdb", "elonmusk"]
    
    print(f"\n目标账号: {', '.join(users)}")
    print("\n步骤:")
    for username in users:
        print(f"\n@{username}:")
        print(f"  1. browser open 'https://xcancel.com/{username}'")
        print(f"  2. browser act wait 3000")
        print(f"  3. browser snapshot")
        print(f"  4. tweets = parse_tweets_from_html(html, '{username}')")


def example_format_for_report():
    """示例3: 格式化为早报内容"""
    print("\n" + "=" * 60)
    print("示例 3: 格式化为早报内容")
    print("=" * 60)
    
    # 示例数据
    sample_tweets = [
        {
            "username": "sama",
            "text": "How would you prefer us to charge for Codex? 83% Flat monthly subscription...",
            "date": "22h",
            "likes": 2341,
            "retweets": 82
        },
        {
            "username": "sama", 
            "text": "The 5.3 lovefest is so nice to see. Don't think we've had so much excitement...",
            "date": "22h",
            "likes": 1848,
            "retweets": 220
        },
        {
            "username": "gdb",
            "text": "Excited about the new model releases today...",
            "date": "1d",
            "likes": 542,
            "retweets": 89
        }
    ]
    
    report = format_tweets_for_report(sample_tweets)
    print("\n格式化后的早报内容:")
    print("-" * 40)
    print(report)
    print("-" * 40)


def example_save_to_file():
    """示例4: 保存到文件"""
    print("\n" + "=" * 60)
    print("示例 4: 保存到 JSON 文件")
    print("=" * 60)
    
    sample_tweets = [
        {
            "id": "2019814741129195576",
            "username": "sama",
            "text": "How would you prefer us to charge for Codex?",
            "date": "22h",
            "likes": 2341,
            "retweets": 82,
            "replies": 1941,
            "url": "https://xcancel.com/sama/status/2019814741129195576"
        }
    ]
    
    # save_tweets(sample_tweets, "tweets.json")
    print("\n代码:")
    print("save_tweets(tweets, 'tweets.json')")
    print("\n输出文件格式:")
    print("""
[
  {
    "id": "2019814741129195576",
    "username": "sama",
    "text": "How would you prefer us to charge for Codex?",
    "date": "22h",
    "likes": 2341,
    "retweets": 82,
    "replies": 1941,
    "url": "https://xcancel.com/sama/status/2019814741129195576"
  }
]
    """)


def main():
    """主函数：运行所有示例"""
    print("🦞 Twitter/X Scraper Skill - 使用示例")
    print(f"时间: 2026-02-07")
    print()
    
    example_single_user()
    example_batch_users()
    example_format_for_report()
    example_save_to_file()
    
    print("\n" + "=" * 60)
    print("示例结束")
    print("=" * 60)
    print("\n提示: 实际使用时，请在 OpenClaw Agent 环境中调用")
    print("参考 SKILL.md 获取完整文档")


if __name__ == "__main__":
    main()
