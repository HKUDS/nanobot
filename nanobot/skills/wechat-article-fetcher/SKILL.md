---
name: wechat-article-fetcher
description: 微信公众号文章抓取工具，基于Playwright，可绕过微信的反爬机制获取完整文章内容
---
# WeChat Article Fetcher

微信公众号文章抓取工具，基于 Playwright，可绕过微信的反爬机制获取完整文章内容。

## 解决的问题

微信公众号文章有严格的反爬机制，常规方法（如 `web_fetch`）无法获取内容：
- ❌ `web_fetch` 只能获取标题，正文被拦截
- ❌ 浏览器自动化需要连接已授权的 Chrome 实例
- ✅ Playwright 可模拟真实浏览器访问，成功抓取全文

## 安装依赖

```bash
pip install playwright
playwright install chromium
```

## 使用方法

### 命令行

```bash
# 基本用法
python3 skills/wechat-article-fetcher/wechat_fetcher.py "https://mp.weixin.qq.com/s/xxxxx"

# 保存到文件
python3 skills/wechat-article-fetcher/wechat_fetcher.py \
  "https://mp.weixin.qq.com/s/xxxxx" \
  -o "output/article.md"
```

### Python API

```python
from skills.wechat-article-fetcher.wechat_fetcher import fetch_wechat_article

result = fetch_wechat_article(
    url="https://mp.weixin.qq.com/s/xxxxx",
    output_path="output/article.md"
)

if result['success']:
    print(f"标题: {result['title']}")
    print(f"内容: {result['content'][:500]}")
```

## 返回格式

```python
{
    'title': '文章标题',
    'content': '完整正文内容（纯文本）',
    'url': '原始链接',
    'fetch_time': '2026-02-12 11:00:00',
    'success': True
}
```

## 使用场景

### 1. 写书项目素材收集

```python
import os
from datetime import datetime

url = "https://mp.weixin.qq.com/s/xxxxx"
filename = f"article-{datetime.now().strftime('%Y%m%d')}.md"
output_path = f"01-Projects/book-openclaw/01-raw-materials/community-cases/{filename}"

# 确保目录存在
os.makedirs(os.path.dirname(output_path), exist_ok=True)

# 抓取并保存
result = fetch_wechat_article(url, output_path)
```

### 2. 批量抓取多个链接

```python
urls = [
    "https://mp.weixin.qq.com/s/xxx1",
    "https://mp.weixin.qq.com/s/xxx2",
    "https://mp.weixin.qq.com/s/xxx3",
]

for url in urls:
    result = fetch_wechat_article(url)
    if result['success']:
        print(f"✅ {result['title']}")
    else:
        print(f"❌ 失败: {url}")
```

### 3. 作为子 Agent 任务

在需要抓取微信文章时，调用此 skill：

```
使用 wechat-article-fetcher skill 抓取链接 https://mp.weixin.qq.com/s/xxxxx
保存到 01-Projects/book-openclaw/01-raw-materials/community-cases/
```

## 技术细节

### 为什么使用 Playwright？

| 方法 | 可行性 | 说明 |
|------|--------|------|
| `web_fetch` | ❌ | 微信反爬，只能获取标题 |
| `browser` (Chrome) | ⚠️ | 需要连接已授权的 Chrome 实例，不稳定 |
| `Playwright` | ✅ | 模拟真实浏览器，稳定可靠 |

### 抓取策略

1. 启动 headless Chromium
2. 访问目标 URL，等待网络空闲
3. 执行 JS 提取正文（`#js_content` 选择器）
4. 返回纯文本内容

### 限制

- 需要系统安装 Chromium（约 100MB）
- 首次运行需下载浏览器二进制文件
- 不处理图片/视频，仅提取文本

## 故障排除

### 问题：提示缺少 Chromium

```bash
# 安装浏览器
playwright install chromium
```

### 问题：抓取内容为空

- 检查链接是否有效（非临时链接）
- 临时分享链接（含 `tempkey` 参数）会过期
- 尝试使用原始永久链接

### 问题：Timeout 错误

- 网络问题，重试即可
- 微信服务器偶尔响应慢

## 相关技能

- `daily-report`: AI 日报生成
- `feishu-chat-extractor`: 飞书群聊记录提取
- `twitter-scraper`: Twitter 内容抓取

## 更新日志

### v1.0.0 (2026-02-12)
- 初始版本
- 基于 Playwright 实现微信文章抓取
- 支持命令行和 Python API
