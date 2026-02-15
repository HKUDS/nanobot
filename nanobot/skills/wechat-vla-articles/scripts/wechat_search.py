#!/usr/bin/env python3
"""
Search for WeChat articles and return results with titles and snippets.

This script actually performs web searches using Brave Search API
and returns article titles, URLs, and snippets.

Requires BRAVE_API_KEY environment variable to be set.

Usage:
    export BRAVE_API_KEY="your-api-key"
    python3 wechat_search.py --days 7 --max-results 10
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

# Import query generation from wechat_query
sys.path.insert(0, os.path.dirname(__file__))
from wechat_query import WECHAT_ACCOUNTS, VLA_KEYWORDS, generate_search_queries


def search_brave(query: str, api_key: str, count: int = 10) -> dict[str, Any]:
    """Search using Brave Search API."""
    url = f"{BRAVE_SEARCH_ENDPOINT}?{urlencode({'q': query, 'count': count})}"
    
    req = Request(url)
    req.add_header("Accept", "application/json")
    req.add_header("X-Subscription-Token", api_key)
    
    try:
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data
    except Exception as e:
        print(f"Error searching Brave API: {e}", file=sys.stderr)
        return {}


def extract_wechat_articles(search_results: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract WeChat article URLs from search results."""
    articles = []
    
    # Brave API returns results in data.web.results
    results = search_results.get("web", {}).get("results", [])
    
    for result in results:
        url = result.get("url", "")
        if "mp.weixin.qq.com" in url:
            articles.append({
                "title": result.get("title", "Unknown"),
                "url": url,
                "description": result.get("description", ""),
                "age": result.get("age", ""),
            })
    
    return articles


def search_articles(
    queries: list[dict[str, Any]],
    api_key: str,
    max_results_per_query: int = 10,
    max_total_articles: int = 50,
) -> list[dict[str, Any]]:
    """Search for articles using multiple queries."""
    all_articles = []
    seen_urls = set()
    
    print(f"Searching {len(queries)} queries...", file=sys.stderr)
    
    for i, query_obj in enumerate(queries, 1):
        query = query_obj["query"]
        print(f"[{i}/{len(queries)}] Searching: {query}", file=sys.stderr)
        
        try:
            search_results = search_brave(query, api_key, count=max_results_per_query)
            articles = extract_wechat_articles(search_results)
            
            for article in articles:
                if article["url"] not in seen_urls:
                    seen_urls.add(article["url"])
                    article["account"] = query_obj["account"]
                    article["keyword"] = query_obj["keyword"]
                    all_articles.append(article)
                    
                    if len(all_articles) >= max_total_articles:
                        print(f"Reached max articles limit ({max_total_articles})", file=sys.stderr)
                        return all_articles
        except Exception as e:
            print(f"Error processing query '{query}': {e}", file=sys.stderr)
            continue
    
    return all_articles


def format_output(articles: list[dict[str, Any]], json_output: bool = False) -> str:
    """Format articles for output."""
    if json_output:
        return json.dumps(articles, indent=2, ensure_ascii=False)
    
    # Human-readable output
    output = []
    output.append(f"找到 {len(articles)} 篇相关文章\n")
    
    for i, article in enumerate(articles, 1):
        output.append(f"{i}. {article.get('title', 'Unknown')}")
        output.append(f"   来源: {article.get('account', 'Unknown')}")
        output.append(f"   关键词: {article.get('keyword', 'Unknown')}")
        output.append(f"   发布时间: {article.get('age', 'Unknown')}")
        output.append(f"   URL: {article.get('url', 'N/A')}")
        description = article.get('description', '')
        if description:
            output.append(f"   摘要: {description[:150]}{'...' if len(description) > 150 else ''}")
        output.append("")
    
    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description="Search for WeChat VLA articles and return results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        help="Maximum number of articles to return (default: 20)",
    )
    parser.add_argument(
        "--max-results-per-query",
        type=int,
        default=10,
        help="Maximum results per search query (default: 10)",
    )
    parser.add_argument(
        "--accounts",
        nargs="+",
        help="Specific accounts to search (default: all)",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        help="Specific keywords to search (default: VLA keywords)",
    )
    parser.add_argument(
        "--api-key",
        help="Brave API key (or set BRAVE_API_KEY env var)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--limit-queries",
        type=int,
        help="Limit number of queries to search (for testing)",
    )
    
    args = parser.parse_args()
    
    # Get API key
    api_key = args.api_key or os.getenv("BRAVE_API_KEY")
    if not api_key:
        print("Error: BRAVE_API_KEY not set. Set it as environment variable or use --api-key", file=sys.stderr)
        print("\nTo get a Brave API key:", file=sys.stderr)
        print("1. Visit https://brave.com/search/api/", file=sys.stderr)
        print("2. Sign up and get your API key", file=sys.stderr)
        print("3. Export it: export BRAVE_API_KEY='your-key'", file=sys.stderr)
        sys.exit(1)
    
    # Generate queries
    accounts = args.accounts if args.accounts else WECHAT_ACCOUNTS
    keywords = args.keywords if args.keywords else VLA_KEYWORDS
    queries = generate_search_queries(accounts, keywords, args.days)
    
    if args.limit_queries:
        queries = queries[:args.limit_queries]
        print(f"Limited to {len(queries)} queries for testing", file=sys.stderr)
    
    # Search for articles
    articles = search_articles(
        queries,
        api_key,
        max_results_per_query=args.max_results_per_query,
        max_total_articles=args.max_results,
    )
    
    # Output results
    print(format_output(articles, json_output=args.json))


if __name__ == "__main__":
    main()
