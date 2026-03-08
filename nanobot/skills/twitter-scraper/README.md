# Twitter/X Scraper Skill

Twitter/X 推文抓取技能，基于 xcancel.com 的浏览器自动化方案。

## 目录结构

```
skills/twitter-scraper/
├── SKILL.md              # 技能文档
├── README.md             # 本文件
└── scripts/
    ├── scraper.py        # 核心解析模块
    └── fetch.py          # 命令行工具
```

## 快速开始

### 在 OpenClaw 中使用

```python
# 1. 使用 browser 工具访问 xcancel
browser open "https://xcancel.com/sama"
browser act wait 3000  # 等待 JS 验证

# 2. 获取页面快照
browser snapshot

# 3. 在 Python 中解析推文
from skills.twitter_scraper.scripts.scraper import parse_tweets_from_html

# 从 browser snapshot 获取的 HTML（需要提取）
tweets = parse_tweets_from_html(html_content, "sama")

for tweet in tweets[:3]:
    print(f"[{tweet['date']}] {tweet['text'][:80]}...")
```

### 批量抓取多个用户

```python
from skills.twitter_scraper.scripts.scraper import parse_tweets_from_html

users = ["sama", "gdb", "elonmusk"]
all_tweets = []

for username in users:
    # 使用 browser 访问 xcancel.com/{username}
    # 获取 HTML 后解析
    tweets = parse_tweets_from_html(html_content, username)
    all_tweets.extend(tweets)
```

### 格式化为早报内容

```python
from skills.twitter_scraper.scripts.scraper import format_tweets_for_report

report = format_tweets_for_report(tweets)
print(report)
```

## API 参考

### `parse_tweets_from_html(html_content: str, username: str) -> List[Dict]`

从 xcancel.com 页面 HTML 中解析推文数据。

**参数：**
- `html_content`: xcancel 页面的 HTML 内容
- `username`: Twitter 用户名

**返回：**
```python
[
  {
    "id": "2019814741129195576",
    "username": "sama",
    "text": "推文内容...",
    "date": "22h",
    "likes": 2341,
    "retweets": 82,
    "replies": 1941,
    "url": "https://xcancel.com/sama/status/2019814741129195576"
  }
]
```

### `format_tweets_for_report(tweets: List[Dict]) -> str`

将推文格式化为早报可用的文本格式。

**返回示例：**
```
1. [sama] How would you prefer us to charge for Codex?... (22h)
2. [sama] The 5.3 lovefest is so nice to see... (22h)
3. [sama] First, the good part of the Anthropic ads... (Feb 4)
```

### `save_tweets(tweets: List[Dict], filepath: str)`

保存推文到 JSON 文件。

## 支持的账号

已测试可用的账号：
- @sama (Sam Altman, OpenAI CEO)
- @gdb (Greg Brockman, OpenAI 联创)
- @elonmusk (Elon Musk, xAI/Tesla)
- @deepseek_ai (DeepSeek 官方)

## 数据来源

- **xcancel.com**: Nitter 的替代品，提供 Twitter 公开数据镜像
- **数据类型**: 公开推文（无需登录）
- **更新频率**: 实时

## 限制

1. **浏览器依赖**: 需要使用 OpenClaw browser 工具访问页面
2. **JS 验证**: 每次访问需等待 2-3 秒完成验证
3. **服务稳定性**: 依赖 xcancel.com 的可用性
4. **抓取频率**: 建议不要过于频繁，避免被封

## 故障排除

### 抓取结果为空
- 检查用户名是否正确（不含 @ 符号）
- 确认 xcancel.com 可访问
- 检查用户是否设为私密账号

### 解析失败
- HTML 结构可能已变更
- 检查 xcancel.com 是否有更新
- 更新 scraper.py 中的解析逻辑

## 更新日志

- **2026-02-07**: 初始版本
  - 支持基本推文解析
  - 支持批量抓取
  - 支持 JSON 输出

## 待办事项

- [ ] 添加更多数据源（如 nitter.poast.org）
- [ ] 支持搜索关键词抓取
- [ ] 支持推文图片/视频链接提取
- [ ] 添加代理支持

## 作者

HiperOne (Zhuoran) for 非凡产研
