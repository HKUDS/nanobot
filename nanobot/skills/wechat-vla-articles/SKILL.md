---
name: wechat-vla-articles
description: Query and summarize recent WeChat public account articles about embodied AI and Vision-Language-Action (VLA). Use when user asks for recent WeChat articles on embodied AI, VLA, robotic manipulation, or navigation from Chinese tech media. Supports filtering by date range (today, 2 days, 1 week) and sorting by popularity (likes, comments, shares). Automatically summarizes articles focusing on key innovations, methods, and insights. IMPORTANT: Always use web_search tool (Brave Search API) to find articles first, NOT direct web scraping. Direct scraping of WeChat websites will fail due to anti-crawling measures.
---

# WeChat VLA Articles

Query and summarize recent WeChat public account articles about embodied AI and Vision-Language-Action (VLA), focusing on robotic manipulation and navigation.

## Overview

This skill helps find and summarize recent articles from major Chinese tech media WeChat public accounts that cover embodied AI, VLA, robotic manipulation, and navigation topics. It searches across multiple accounts, filters by relevance and date, and provides concise summaries.

**IMPORTANT**: This skill uses `web_search` tool (Brave Search API) to find articles, NOT direct web scraping. Direct scraping of WeChat public account websites will fail due to anti-crawling mechanisms and JavaScript rendering. Always use `web_search` first to find article URLs, then use `web_fetch` only for specific article URLs found in search results.

## Quick Start

### Option 1: Direct search (requires Brave API key)

Search directly and get article titles and snippets:

```bash
export BRAVE_API_KEY="your-api-key"
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_search.py --days 7 --max-results 20
```

This will return articles with titles, URLs, descriptions, and source accounts.

### Option 2: Generate queries only

Generate search queries for use with nanobot agent's `web_search` tool:

```bash
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --days 7 --queries-only
```

Then use the queries with `web_search` tool via nanobot agent.

### Search and fetch articles

**Correct workflow**:
1. **First**: Use `web_search` tool (via agent) to find article URLs - DO NOT try to directly scrape WeChat websites
2. **Then**: Use `web_fetch` to get content from the specific article URLs found in search results
3. **Finally**: Use `summarize` to create summaries

**Why web_search first?** WeChat public account websites use anti-crawling measures and JavaScript rendering. Direct scraping will return empty content. Use Brave Search API via `web_search` tool to find article URLs, then fetch those specific URLs.

## Workflow

### 1. Generate search queries

Use the script to generate search queries for target accounts and keywords:

```bash
# Last 7 days (default)
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --days 7 --queries-only

# Last 2 days
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --days 2 --queries-only

# Today only
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --days 1 --queries-only

# Custom accounts
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --accounts "机器之心" "量子位" --days 7
```

The script generates queries like:
- `机器之心 具身智能 最近7天`
- `量子位 vision-language-action 最近7天`
- `新智元 机器人操作 最近7天`

### 2. Search for articles

**IMPORTANT**: Use `web_search` tool (via Brave Search API), NOT direct web scraping. Direct scraping of WeChat public account pages will fail due to anti-crawling measures.

**IMPORTANT**: Brave Search API does NOT filter by date automatically. The query text "最近7天" is just a hint and won't actually filter results. You MUST post-process results to filter by date.

For each query, use `web_search` with improved query format:

```json
{
  "tool": "web_search",
  "query": "机器之心 具身智能 site:mp.weixin.qq.com",
  "count": 20
}
```

**Query optimization tips**:
- Add `site:mp.weixin.qq.com` to limit results to WeChat articles
- Request more results (count: 20-30) since you'll filter by date later
- Don't rely on "最近7天" in query - it won't actually filter results
- Use specific date keywords if needed: "2025年1月" or "January 2025"

**Note**: After getting search results, you MUST use `web_fetch` on each article URL to extract the publication date, then filter articles that are actually within the target date range.

### 3. Filter and process results

**CRITICAL**: Brave Search API does NOT filter results by date based on query text alone. You MUST post-process results to filter by date.

**Required steps**:
1. Extract article titles and URLs from `web_search` results
2. **For each article URL**, use `web_fetch` to get the article content
3. **Extract publication date** from the fetched content (look for date patterns like "2025-01-15", "1月15日", etc.)
4. **Filter articles** by comparing publication date with target date range (e.g., last 7 days)
5. Remove duplicates
6. Identify source accounts from article content or URL patterns

**Example date extraction pattern**:
- Look for date strings in formats: "YYYY-MM-DD", "YYYY年MM月DD日", "MM月DD日"
- Parse and compare with current date minus target days
- Only keep articles within the date range

### 4. Fetch article content and extract dates

**CRITICAL**: For each article URL from search results, use `web_fetch` to:
1. Get article content
2. **Extract publication date** from the content
3. **Filter by date range** before proceeding

For each article URL, use `web_fetch`:

```json
{
  "url": "https://mp.weixin.qq.com/s/...",
  "extractMode": "markdown",
  "maxChars": 10000
}
```

**Date extraction from article content**:
- Look for date patterns in the fetched content:
  - "YYYY-MM-DD" (e.g., "2025-01-15")
  - "YYYY年MM月DD日" (e.g., "2025年1月15日")
  - "MM月DD日" (e.g., "1月15日") - compare with current date
- Parse the date and check if it's within the target range (e.g., last 7 days)
- **Only keep articles** that match the date filter
- **Skip articles** that are outside the date range

### 5. Extract popularity metrics

Try to extract or estimate popularity metrics:
- Likes (点赞)
- Comments (留言)
- Shares (分享)
- Views (阅读数)

If metrics are available, calculate popularity score:
```
热度评分 = 点赞数 × 0.3 + 留言数 × 0.3 + 分享数 × 0.2 + 阅读数 × 0.2
```

### 6. Sort by popularity

Sort articles by popularity score (if available) or use search ranking as fallback.

### 7. Summarize articles

Use the `summarize` skill to create concise summaries:

```bash
summarize "https://mp.weixin.qq.com/s/..." --model google/gemini-3-flash-preview --length medium
```

Or use LLM directly with a focused prompt:

```
Summarize this WeChat article about embodied AI/VLA focusing on:
1. Main topic and key points
2. Technical innovations or methods mentioned
3. Important insights or conclusions
4. Relevance to robotic manipulation/navigation
```

## Target Accounts

The skill searches these WeChat public accounts:

- 机器之心 (Machine Heart)
- 量子位 (QbitAI)
- 新智元 (AI Era)
- 智源社区 (BAAI Community)
- 深蓝具身智能 (DeepBlue Embodied AI)
- BAAI具身智能 (BAAI Embodied AI)
- 具身智能之心 (Embodied AI Heart)
- 智元AGIBOT (AGIBOT)
- Lumina具身智能 (Lumina Embodied AI)
- 灵初智能 (Lingchu Intelligence)
- 简智机器人 (Jianzhi Robotics)

## Keywords

Default keywords include:

- 具身智能 (embodied AI)
- vision-language-action / VLA
- 机器人操作 (robotic manipulation)
- 机器人导航 (robotic navigation)
- 视觉语言动作 (vision-language-action)
- 语言条件 (language-conditioned)
- 指令跟随 (instruction following)

## Customization

### Adjust date range

```bash
# Last week
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --days 7

# Last 2 days
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --days 2

# Today only
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --days 1
```

### Custom accounts

```bash
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --accounts "机器之心" "量子位"
```

### Additional keywords

```bash
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --keywords "mobile manipulation" "dexterous manipulation"
```

## Output Format

Articles are returned with:
- Title
- Source account
- Publication date
- URL
- Popularity score (if available)
- Snippet/summary

## Integration with Other Skills

### Use with summarize

After fetching article URLs, use `summarize` for detailed analysis:

```bash
# Get article list from search
# Then summarize each article
for url in $(cat article_urls.txt); do
  summarize "$url" --model google/gemini-3-flash-preview --length medium
done
```

### Use with web_fetch

Fetch full article content for deeper analysis:

```bash
# Get article URLs from search results
# Then fetch each article
for url in $(cat article_urls.txt); do
  web_fetch "$url" --extractMode markdown --maxChars 10000
done
```

## Focus Areas

When summarizing articles, emphasize:

1. **Key Topics**: What is the main subject? What problem does it address?
2. **Technical Content**: What methods, architectures, or approaches are discussed?
3. **Innovations**: What's new or different from prior work?
4. **Relevance**: How does it relate to VLA, robotic manipulation, or navigation?
5. **Insights**: What are the key takeaways or conclusions?

## Example Workflow

### Complete workflow: Query → Search → Fetch → Filter by Date → Summarize

**CRITICAL**: This workflow includes date filtering, which is REQUIRED because Brave Search API does not filter by date automatically.

```bash
# 1. Generate search queries (last 7 days)
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --days 7 --queries-only > queries.txt

# 2. Search for each query (use web_search tool via agent)
# Store results in articles.json

# 3. Filter and deduplicate articles
# Sort by popularity if metrics available

# 4. Fetch top articles (use web_fetch tool via agent)
# For each URL, call web_fetch with extractMode=markdown, maxChars=10000

# 5. Summarize each article
for url in $(jq -r '.[:10][].url' articles.json); do
  summarize "$url" --model google/gemini-3-flash-preview --length medium
done
```

### Quick summary of today's articles

```bash
# 1. Generate today's queries
python3 nanobot/skills/wechat-vla-articles/scripts/wechat_query.py --days 1 --queries-only > today_queries.txt

# 2. Search and collect articles (use web_search tool via agent)
# 3. Summarize top results
```

## Limitations

- WeChat doesn't provide a public API, so we rely on web search and scraping
- Popularity metrics may not be directly accessible
- Some articles may require login or special permissions
- Search results may be incomplete or inaccurate
- Rate limiting may apply when fetching multiple articles

## References

- `references/wechat_articles.md` - Detailed guide on fetching WeChat articles
- `scripts/wechat_query.py` - Query generation script

## Notes

- WeChat articles are typically in Chinese
- Focus on embodied AI, VLA, robotic manipulation, and navigation topics
- Popularity sorting requires metrics extraction, which may not always be possible
- Consider using caching to avoid repeated searches
- Batch processing with rate limiting to avoid triggering anti-scraping measures
