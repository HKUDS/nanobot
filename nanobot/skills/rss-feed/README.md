# RSS 抓取技能

从多个RSS源自动抓取AI新闻，输出结构化数据供早报生成使用。

## 数据源

| 名称 | URL | 分类 |
|------|-----|------|
| 机器之心 | https://www.jiqizhixin.com/rss | 国内AI媒体 |
| 量子位 | https://www.qbitai.com/feed | 国内AI媒体 |
| 虎嗅 | https://www.huxiu.com/rss | 商业视角 |
| TechCrunch AI | https://techcrunch.com/category/artificial-intelligence/feed/ | AI创业/融资 |
| Wired AI | https://www.wired.com/feed/tag/ai/latest/rss | 深度分析 |
| Ars Technica | https://arstechnica.com/tag/artificial-intelligence/feed/ | 技术视角 |

## 使用方法

```bash
# 直接运行
python3 rss_fetcher.py

# 输出
- rss_data_YYYYMMDD_HHMM.json  # 带时间戳的完整数据
- latest_rss_data.json         # 最新数据（供早报使用）
```

## 配置说明

- 超时设置：30秒（socket级别）
- 重试次数：3次（指数退避）
- 总执行时间限制：300秒（5分钟）
- 去重策略：基于标题完全相同
- 过滤：仅保留24小时内的新闻

## 输出格式

```json
{
  "title": "文章标题",
  "link": "https://...",
  "published": "发布日期",
  "summary": "摘要（前500字符）",
  "source": "来源名称",
  "category": "分类",
  "fetched_at": "抓取时间"
}
```

## 依赖

```bash
pip install feedparser
```

## 定时任务建议

```cron
# 每小时抓取一次
0 * * * * cd /path/to/skills/rss-feed && python3 rss_fetcher.py
```
