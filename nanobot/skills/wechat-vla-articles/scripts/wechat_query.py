#!/usr/bin/env python3
"""
Query and collect WeChat public account articles about embodied AI and VLA.

This script helps search for articles from specified WeChat public accounts
related to Vision-Language-Action (VLA) and embodied AI, focusing on robotic
manipulation and navigation.

Since WeChat doesn't provide a public API, this script generates search queries
that can be used with web_search tool, and provides utilities for processing
the results.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Any

# Target WeChat public accounts
WECHAT_ACCOUNTS = [
    "机器之心",
    "量子位",
    "新智元",
    "智源社区",
    "深蓝具身智能",
    "BAAI具身智能",
    "具身智能之心",
    "智元AGIBOT",
    "Lumina具身智能",
    "灵初智能",
    "简智机器人",
]

# Keywords for VLA and embodied AI
VLA_KEYWORDS = [
    "具身智能",
    "embodied AI",
    "vision-language-action",
    "VLA",
    "机器人操作",
    "robotic manipulation",
    "机器人导航",
    "robotic navigation",
    "视觉语言动作",
    "语言条件",
    "language-conditioned",
    "指令跟随",
    "instruction following",
]


def generate_search_queries(accounts: list[str], keywords: list[str], days: int) -> list[dict[str, Any]]:
    """
    Generate search queries for web_search tool.
    
    Note: Brave Search API does NOT filter by date automatically. The date_context
    is just a hint. Results must be post-processed to filter by actual publication date.
    
    Returns a list of query objects with account name, keywords, and date context.
    """
    date_context = ""
    if days == 1:
        date_context = "今天"
    elif days == 2:
        date_context = "最近两天"
    else:
        date_context = f"最近{days}天"
    
    queries = []
    for account in accounts:
        for keyword in keywords:
            # Build search query: account name + keyword + site filter
            # Add site:mp.weixin.qq.com to limit to WeChat articles
            # Note: date_context is included but won't actually filter results
            query = f"{account} {keyword} site:mp.weixin.qq.com"
            queries.append({
                "account": account,
                "keyword": keyword,
                "query": query,
                "date_context": date_context,
                "days": days,  # Store days for post-processing
            })
    
    return queries


def parse_date_range(days: int) -> tuple[str, str]:
    """Calculate date range for filtering articles."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def estimate_popularity_score(article: dict[str, Any]) -> float:
    """
    Estimate popularity score from available metrics.
    
    Since WeChat doesn't expose exact metrics via public APIs,
    this function provides a placeholder for when metrics are available
    from web scraping or third-party services.
    """
    # Placeholder: if metrics are available, calculate weighted score
    # Weight: likes=0.3, comments=0.3, shares=0.2, views=0.2
    likes = article.get("likes", 0) or 0
    comments = article.get("comments", 0) or 0
    shares = article.get("shares", 0) or 0
    views = article.get("views", 0) or 0
    
    score = (
        likes * 0.3 +
        comments * 0.3 +
        shares * 0.2 +
        views * 0.2
    )
    return score


def format_article_output(articles: list[dict[str, Any]], json_output: bool = False) -> str:
    """Format articles for output."""
    if json_output:
        return json.dumps(articles, indent=2, ensure_ascii=False)
    
    # Human-readable output
    output = []
    output.append(f"找到 {len(articles)} 篇相关文章\n")
    
    for i, article in enumerate(articles, 1):
        output.append(f"{i}. {article.get('title', 'Unknown')}")
        output.append(f"   来源: {article.get('account', 'Unknown')}")
        output.append(f"   发布时间: {article.get('published', 'Unknown')}")
        output.append(f"   URL: {article.get('url', 'N/A')}")
        if article.get('popularity_score'):
            output.append(f"   热度评分: {article['popularity_score']:.2f}")
        if article.get('snippet'):
            output.append(f"   摘要: {article['snippet'][:150]}...")
        output.append("")
    
    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description="Generate search queries for WeChat VLA articles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)",
    )
    parser.add_argument(
        "--accounts",
        nargs="+",
        default=WECHAT_ACCOUNTS,
        help="WeChat public accounts to search (default: all)",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=VLA_KEYWORDS,
        help="Keywords to search (default: VLA keywords)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--queries-only",
        action="store_true",
        help="Only output search queries (for use with web_search tool)",
    )
    
    args = parser.parse_args()
    
    # Generate search queries
    queries = generate_search_queries(args.accounts, args.keywords, args.days)
    
    if args.queries_only:
        # Output just the search query strings, one per line
        for q in queries:
            print(q["query"])
        return
    
    # Output query objects
    if args.json:
        print(json.dumps(queries, indent=2, ensure_ascii=False))
    else:
        print(f"生成了 {len(queries)} 个搜索查询\n")
        print("示例查询:")
        for i, q in enumerate(queries[:5], 1):
            print(f"{i}. {q['query']}")
        if len(queries) > 5:
            print(f"... 还有 {len(queries) - 5} 个查询")
        print("\n提示: 使用 --queries-only 输出所有查询字符串，配合 web_search 工具使用")


if __name__ == "__main__":
    main()
