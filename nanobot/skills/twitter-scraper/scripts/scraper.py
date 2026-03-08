#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitter/X 推文抓取模块
用于 skills/twitter_scraper

使用方式：
1. 通过 OpenClaw browser 工具访问 xcancel.com/{username}
2. 使用本模块解析页面内容，提取推文数据
"""

import json
import re
from datetime import datetime
from typing import List, Dict, Optional


def parse_tweets_from_html(html_content: str, username: str) -> List[Dict]:
    """
    从 xcancel.com 页面 HTML 中解析推文数据
    
    注意：此函数需要配合 browser 工具使用，先获取页面 HTML
    
    Args:
        html_content: xcancel 页面的 HTML 内容
        username: Twitter 用户名
        
    Returns:
        List[Dict]: 推文列表
    """
    tweets = []
    
    # 使用正则表达式提取推文数据
    # xcancel 的 HTML 结构：每个推文在一个 .timeline-item 中
    
    # 查找所有推文块
    tweet_pattern = r'<div class="timeline-item"[^>]*>.*?<div class="tweet-content"[^>]*>(.*?)</div>\s*</div>'
    tweet_blocks = re.findall(tweet_pattern, html_content, re.DOTALL)
    
    for block in tweet_blocks:
        tweet = _parse_tweet_block(block, username)
        if tweet:
            tweets.append(tweet)
    
    return tweets


def _parse_tweet_block(html: str, username: str) -> Optional[Dict]:
    """解析单个推文块"""
    try:
        # 提取推文 ID
        id_match = re.search(r'/status/(\d+)', html)
        tweet_id = id_match.group(1) if id_match else None
        
        # 提取推文内容
        text_match = re.search(r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
        if text_match:
            text = _clean_html(text_match.group(1))
        else:
            text = ""
        
        # 提取发布时间
        date_match = re.search(r'<span[^>]*class="[^"]*tweet-date[^"]*"[^>]*>(.*?)</span>', html, re.DOTALL)
        date_str = _clean_html(date_match.group(1)) if date_match else ""
        
        # 提取互动数据
        likes = _extract_count(html, r'(\d+)\s*likes?')
        retweets = _extract_count(html, r'(\d+)\s*retweets?')
        replies = _extract_count(html, r'(\d+)\s*replies?')
        
        if tweet_id and text:
            return {
                "id": tweet_id,
                "username": username,
                "text": text.strip(),
                "date": date_str.strip(),
                "likes": likes,
                "retweets": retweets,
                "replies": replies,
                "url": f"https://xcancel.com/{username}/status/{tweet_id}"
            }
    except Exception as e:
        print(f"解析推文失败: {e}")
    
    return None


def _clean_html(html: str) -> str:
    """清理 HTML 标签"""
    # 移除 HTML 标签
    text = re.sub(r'<[^>]+>', '', html)
    # 解码 HTML 实体
    text = text.replace('&quot;', '"')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&#39;', "'")
    # 清理多余空白
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _extract_count(html: str, pattern: str) -> int:
    """提取数字计数"""
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except:
            pass
    return 0


def format_tweets_for_report(tweets: List[Dict]) -> str:
    """
    将推文格式化为早报可用的文本格式
    
    Returns:
        str: 格式化后的文本
    """
    if not tweets:
        return "暂无推文数据"
    
    lines = []
    for i, tweet in enumerate(tweets[:5], 1):  # 最多显示5条
        text = tweet['text'][:120] + "..." if len(tweet['text']) > 120 else tweet['text']
        lines.append(f"{i}. [{tweet['username']}] {text} ({tweet['date']})")
    
    return "\n".join(lines)


def save_tweets(tweets: List[Dict], filepath: str):
    """保存推文到 JSON 文件"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(tweets, f, ensure_ascii=False, indent=2)
    print(f"✅ 已保存 {len(tweets)} 条推文到: {filepath}")


# 使用示例
if __name__ == "__main__":
    print("Twitter/X Scraper Skill")
    print("=" * 50)
    print("\n使用方式：")
    print("1. 使用 OpenClaw browser 工具访问 xcancel.com/{username}")
    print("2. 将页面 HTML 保存到变量")
    print("3. 调用 parse_tweets_from_html(html_content, username) 解析")
    print("\n示例代码：")
    print("""
from skills.twitter_scraper.scripts.scraper import parse_tweets_from_html

# 从 browser 获取的 HTML
html = browser_snapshot_content
tweets = parse_tweets_from_html(html, "sama")

for tweet in tweets[:3]:
    print(f"{tweet['date']}: {tweet['text'][:80]}...")
    """)
