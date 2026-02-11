#!/usr/bin/env python3
"""
豆瓣电影查询工具 - 通过 Folo RSS API 获取豆瓣电影数据
数据源：
  - 一周口碑电影榜 (weekly)
  - 即将上映 (coming)
  - 本周口碑榜 (top)
"""

import argparse
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser

FEEDS = {
    "weekly": {
        "id": "48039983835900997",
        "name": "一周口碑电影榜",
        "desc": "每周五更新，豆瓣一周口碑最佳影片",
    },
    "coming": {
        "id": "58294482107464704",
        "name": "豆瓣电影·即将上映",
        "desc": "即将在中国大陆上映的电影",
    },
    "top": {
        "id": "55576111518416909",
        "name": "豆瓣电影本周口碑榜",
        "desc": "本周口碑最佳影片（feedx源）",
    },
}

class TextExtractor(HTMLParser):
    """Extract plain text from HTML."""
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)
    def get_text(self):
        return "".join(self.parts).strip()

def html_to_text(html_str):
    if not html_str:
        return ""
    extractor = TextExtractor()
    extractor.feed(html_str)
    return extractor.get_text()

def fetch_feed(feed_key, limit=8):
    """Fetch entries from a feed."""
    feed_info = FEEDS.get(feed_key)
    if not feed_info:
        print(f"Error: Unknown feed '{feed_key}'. Use: {', '.join(FEEDS.keys())}", file=sys.stderr)
        sys.exit(1)

    url = f"https://api.folo.is/feeds?id={feed_info['id']}&entriesLimit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    return data.get("data", {})

def parse_movie(entry):
    """Parse a movie entry into structured data."""
    movie = {
        "title": entry.get("title", "未知"),
        "url": entry.get("url", ""),
        "rating": None,
        "year": None,
        "country": None,
        "genres": None,
        "director": None,
        "cast": None,
        "summary": entry.get("summary") or "",
        "poster": None,
        "published": entry.get("publishedAt", ""),
    }

    # Parse description text for structured info
    desc = entry.get("description") or html_to_text(entry.get("content", ""))

    # Extract rating
    m = re.search(r"评分[：:]\s*(\d+\.?\d*)\s*分?", desc)
    if m:
        movie["rating"] = float(m.group(1))

    # Extract tags line (year / country / genres / director / cast)
    m = re.search(r"标签[：:]\s*(.+)", desc)
    if m:
        tag_line = m.group(1).strip()
        parts = [p.strip() for p in tag_line.split("/")]
        if parts:
            # First part: year + country
            first = parts[0].strip()
            year_match = re.match(r"(\d{4})", first)
            if year_match:
                movie["year"] = int(year_match.group(1))
            if len(parts) > 1:
                movie["country"] = parts[1].strip()
            if len(parts) > 2:
                movie["genres"] = parts[2].strip()
            if len(parts) > 3:
                movie["director"] = parts[3].strip()
            if len(parts) > 4:
                movie["cast"] = parts[4].strip()

    # Extract movie info/synopsis
    m = re.search(r"影片信息[：:]\s*(.+)", desc)
    if m and not movie["summary"]:
        movie["summary"] = m.group(1).strip()

    # Get poster from media
    media = entry.get("media", [])
    if media and media[0].get("type") == "photo":
        movie["poster"] = media[0]["url"]

    return movie

def format_movie(movie, index=None, verbose=False):
    """Format a movie for display."""
    parts = []
    prefix = f"{index}. " if index else ""

    # Title line
    title_line = f"{prefix}🎬 **{movie['title']}**"
    if movie["rating"]:
        title_line += f"  ⭐ {movie['rating']}分"
    parts.append(title_line)

    # Info line
    info = []
    if movie["year"]:
        info.append(str(movie["year"]))
    if movie["country"]:
        info.append(movie["country"])
    if movie["genres"]:
        info.append(movie["genres"])
    if info:
        parts.append(f"   📌 {' / '.join(info)}")

    if movie["director"]:
        line = f"   🎬 导演: {movie['director']}"
        if movie["cast"]:
            line += f" | 主演: {movie['cast']}"
        parts.append(line)

    if verbose and movie["summary"]:
        parts.append(f"   📝 {movie['summary'][:100]}{'...' if len(movie['summary']) > 100 else ''}")

    if movie["url"]:
        parts.append(f"   🔗 {movie['url']}")

    return "\n".join(parts)

def cmd_list(args):
    """List movies from a feed."""
    data = fetch_feed(args.feed, limit=args.limit)
    feed_info = data.get("feed", {})
    entries = data.get("entries", [])

    print(f"📋 **{feed_info.get('title', FEEDS[args.feed]['name'])}**")
    print(f"   {FEEDS[args.feed]['desc']}")
    print()

    movies = [parse_movie(e) for e in entries]

    # Apply filters
    if args.min_rating:
        movies = [m for m in movies if m["rating"] and m["rating"] >= args.min_rating]
    if args.genre:
        genre_kw = args.genre.lower()
        movies = [m for m in movies if m["genres"] and genre_kw in m["genres"].lower()]
    if args.keyword:
        kw = args.keyword.lower()
        movies = [m for m in movies if kw in m["title"].lower() or kw in (m["summary"] or "").lower()
                  or kw in (m["director"] or "").lower() or kw in (m["cast"] or "").lower()]

    if not movies:
        print("没有找到符合条件的电影 😿")
        return

    for i, movie in enumerate(movies, 1):
        print(format_movie(movie, index=i, verbose=args.verbose))
        print()

def cmd_all(args):
    """Show movies from all feeds."""
    for feed_key in ["weekly", "top", "coming"]:
        data = fetch_feed(feed_key, limit=args.limit)
        feed_info = data.get("feed", {})
        entries = data.get("entries", [])

        print(f"{'='*50}")
        print(f"📋 **{feed_info.get('title', FEEDS[feed_key]['name'])}**")
        print(f"{'='*50}")
        print()

        movies = [parse_movie(e) for e in entries]
        if args.min_rating:
            movies = [m for m in movies if m["rating"] and m["rating"] >= args.min_rating]

        for i, movie in enumerate(movies, 1):
            print(format_movie(movie, index=i, verbose=args.verbose))
            print()

def cmd_recommend(args):
    """Recommend a movie based on criteria."""
    import random

    all_movies = []
    for feed_key in ["weekly", "top"]:
        data = fetch_feed(feed_key, limit=10)
        entries = data.get("entries", [])
        all_movies.extend([parse_movie(e) for e in entries])

    # Deduplicate by URL
    seen = set()
    unique = []
    for m in all_movies:
        if m["url"] not in seen:
            seen.add(m["url"])
            unique.append(m)
    all_movies = unique

    # Apply filters
    if args.min_rating:
        all_movies = [m for m in all_movies if m["rating"] and m["rating"] >= args.min_rating]
    if args.genre:
        genre_kw = args.genre.lower()
        all_movies = [m for m in all_movies if m["genres"] and genre_kw in m["genres"].lower()]

    if not all_movies:
        print("没有找到符合条件的电影，放宽条件试试？😿")
        return

    # Pick top rated or random
    if args.lucky:
        pick = random.choice(all_movies)
        print("🎲 **今晚看这个！**\n")
    else:
        all_movies.sort(key=lambda m: m["rating"] or 0, reverse=True)
        pick = all_movies[0]
        print("🏆 **最佳推荐：**\n")

    print(format_movie(pick, verbose=True))

def cmd_json(args):
    """Output raw JSON for programmatic use."""
    data = fetch_feed(args.feed, limit=args.limit)
    entries = data.get("entries", [])
    movies = [parse_movie(e) for e in entries]
    print(json.dumps(movies, ensure_ascii=False, indent=2))

def main():
    parser = argparse.ArgumentParser(description="豆瓣电影查询工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # list command
    p_list = subparsers.add_parser("list", help="列出电影")
    p_list.add_argument("feed", choices=["weekly", "coming", "top"], help="数据源")
    p_list.add_argument("-n", "--limit", type=int, default=8, help="数量限制 (默认8)")
    p_list.add_argument("-r", "--min-rating", type=float, help="最低评分筛选")
    p_list.add_argument("-g", "--genre", help="类型筛选 (如: 剧情, 喜剧, 动作)")
    p_list.add_argument("-k", "--keyword", help="关键词搜索")
    p_list.add_argument("-v", "--verbose", action="store_true", help="显示详细信息")
    p_list.set_defaults(func=cmd_list)

    # all command
    p_all = subparsers.add_parser("all", help="显示所有榜单")
    p_all.add_argument("-n", "--limit", type=int, default=5, help="每个榜单数量 (默认5)")
    p_all.add_argument("-r", "--min-rating", type=float, help="最低评分筛选")
    p_all.add_argument("-v", "--verbose", action="store_true", help="显示详细信息")
    p_all.set_defaults(func=cmd_all)

    # recommend command
    p_rec = subparsers.add_parser("recommend", help="推荐电影")
    p_rec.add_argument("-r", "--min-rating", type=float, help="最低评分")
    p_rec.add_argument("-g", "--genre", help="类型偏好")
    p_rec.add_argument("--lucky", action="store_true", help="随机推荐（手气不错）")
    p_rec.set_defaults(func=cmd_recommend)

    # json command
    p_json = subparsers.add_parser("json", help="JSON输出")
    p_json.add_argument("feed", choices=["weekly", "coming", "top"])
    p_json.add_argument("-n", "--limit", type=int, default=8)
    p_json.set_defaults(func=cmd_json)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)

if __name__ == "__main__":
    main()
