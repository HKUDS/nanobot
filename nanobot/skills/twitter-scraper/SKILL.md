---
name: twitter-scraper
description: 基于 xcancel.com 的 Twitter/X 推文抓取工具，使用浏览器自动化获取公开推文数据。...
---

# Twitter/X Scraper Skill

基于 xcancel.com 的 Twitter/X 推文抓取工具，使用浏览器自动化获取公开推文数据。

## 功能

- 抓取指定用户的最新推文
- 支持批量抓取多个账号
- 输出 JSON/CSV 格式
- 自动处理 xcancel 的反爬虫验证

## 安装

无需额外依赖，直接使用 OpenClaw 内置 browser 工具。

## 使用方法

### 1. 抓取单个用户

```python
from skills.twitter_scraper.scripts.scrape import scrape_user

# 抓取 @sama 的最新5条推文
tweets = scrape_user("sama", max_tweets=5)

for tweet in tweets:
    print(f"{tweet['date']}: {tweet['text'][:100]}...")
```

### 2. 批量抓取多个用户

```python
from skills.twitter_scraper.scripts.scrape import scrape_multiple_users

users = ["sama", "gdb", "deepseek_ai", "elonmusk"]
results = scrape_multiple_users(users, max_tweets=5)

for username, tweets in results.items():
    print(f"@{username}: {len(tweets)} 条推文")
```

### 3. 命令行使用

```bash
# 抓取单个用户
python3 skills/twitter_scraper/scripts/scrape.py --user sama --max 10

# 批量抓取
python3 skills/twitter_scraper/scripts/scrape.py --users sama,gdb,elonmusk --max 5

# 保存到文件
python3 skills/twitter_scraper/scripts/scrape.py --user sama --output tweets.json
```

## 输出格式

```json
[
  {
    "id": "2019814741129195576",
    "username": "sama",
    "text": "How would you prefer us to charge for Codex?...",
    "date": "22h",
    "likes": 2341,
    "retweets": 82,
    "replies": 1941,
    "url": "https://xcancel.com/sama/status/2019814741129195576"
  }
]
```

## 支持的账号

已测试可用的账号：
- @sama (Sam Altman)
- @gdb (Greg Brockman)
- @elonmusk (Elon Musk)
- @deepseek_ai (DeepSeek)

## 限制

- 依赖 xcancel.com 服务可用性
- 需要浏览器环境（启动约需 3-5 秒）
- 每次抓取需等待 JS 验证（约 2-3 秒）
- 建议单次抓取不超过 20 条，避免超时

## 数据来源

- 数据来源：xcancel.com (Nitter 替代品)
- 数据类型：公开推文（无需登录）
- 更新频率：实时

## 故障排除

### 问题：抓取结果为空
- 检查用户名是否正确
- 确认 xcancel.com 可访问
- 检查用户是否设为私密

### 问题：超时错误
- 减少 max_tweets 数量
- 检查网络连接
- 稍后重试

## 更新日志

- 2026-02-07: 初始版本，支持基本抓取功能

## 作者

HiperOne (Zhuoran) for 非凡产研
