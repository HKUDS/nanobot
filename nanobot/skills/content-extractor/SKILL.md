---
name: content-extractor
description: 支持多平台内容抓取：小宇宙播客、抖音、微信公众号、B站、小红书等。...
---

# Content Extractor - 统一内容提取中心

支持多平台内容抓取：小宇宙播客、抖音、微信公众号、B站、小红书等。

## 安装依赖

```bash
pip install playwright requests
playwright install chromium
```

## 核心功能

### 1. 单链接提取

#### 快速模式（推荐）
```python
from skills.content_extractor.content_extractor import extract, extract_fast

# 快速提取（默认）- 使用curl直接获取音频URL，速度最快
result = extract("https://www.xiaoyuzhoufm.com/episode/xxx")
print(result.title)           # 播客标题
print(result.media_urls)      # 音频下载链接
print(result.author)          # 播客名称

# 快速提取 + 下载音频
result = extract_fast(
    "https://www.xiaoyuzhoufm.com/episode/xxx",
    download=True,
    save_path="./downloads"
)
```

#### 完整模式（需要Playwright）
```python
from skills.content_extractor.content_extractor import extract_full

# 完整提取 - 使用浏览器渲染，获取更完整的信息
result = extract_full("https://www.xiaoyuzhoufm.com/episode/xxx")
print(result.content)         # 详细描述
print(result.metadata)        # 完整元数据
```

### 2. 批量提取

```python
from skills.content_extractor.content_extractor import batch_extract

urls = [
    "https://www.xiaoyuzhoufm.com/episode/xxx",
    "https://mp.weixin.qq.com/s/xxx",
    "https://www.bilibili.com/video/xxx",
]

results = batch_extract(urls, download_media=False)
for result in results:
    print(f"{result.platform.value}: {result.title}")
```

### 3. 平台检测

```python
from skills.content_extractor.content_extractor import detect_platform

platform = detect_platform("https://www.xiaoyuzhoufm.com/episode/xxx")
print(platform)  # Platform.XIAOYUZHOU
```

## 支持的平台

| 平台 | 支持内容 | 音频 | 视频 | 文字 | 图片 |
|------|---------|------|------|------|------|
| 小宇宙 | 播客 | ✅ | - | ✅ | - |
| 抖音 | 短视频 | ✅ | ✅ | - | - |
| 微信公众号 | 文章 | - | ✅ | ✅ | ✅ |
| B站 | 视频 | ✅ | ✅ | ✅ | - |
| 小红书 | 笔记 | - | ✅ | ✅ | ✅ |

## 提取模式对比

| 模式 | 速度 | 信息完整度 | 依赖 | 适用场景 |
|------|------|-----------|------|---------|
| **快速模式** | ⚡ 3-5秒 | ⭐⭐⭐ 标题+音频URL+简介 | curl | 仅需要音频下载链接 |
| **完整模式** | 🐢 10-30秒 | ⭐⭐⭐⭐⭐ 完整信息 | Playwright | 需要详细描述和元数据 |

**推荐策略**：
- 快速提取音频 → 使用 **快速模式**（默认）
- 生成完整笔记 → 使用 **完整模式**

```python
@dataclass
class ExtractResult:
    platform: Platform          # 平台类型
    title: str                  # 标题
    content: str                # 内容/描述
    author: Optional[str]       # 作者
    publish_time: Optional[str] # 发布时间
    media_urls: List[str]       # 音频/视频URL列表
    images: List[str]           # 图片URL列表
    metadata: Dict[str, Any]    # 元数据（包含原始URL等）
```

## 选项参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `download_media` | bool | False | 是否下载音视频 |
| `save_path` | str | None | 下载保存路径 |
| `extract_text` | bool | True | 是否提取文字内容 |

## 工作流集成

### 工作流1：播客内容提取 → 生成文档

```python
from skills.content_extractor.content_extractor import extract
from skills.document_hub.document_hub import write

# 提取播客
result = extract("https://www.xiaoyuzhoufm.com/episode/xxx")

# 生成Word文档
content = {
    "title": result.title,
    "paragraphs": [
        f"来源：小宇宙播客",
        f"作者：{result.author}",
        "",
        "内容描述：",
        result.content
    ]
}
write("播客笔记.docx", content)
```

### 工作流2：抖音视频 → 提取音频 → 转文字

```python
from skills.content_extractor.content_extractor import extract
from skills.document_hub.document_hub import get_hub

hub = get_hub()

# 提取抖音视频并下载
result = extract(
    "https://v.douyin.com/xxx",
    download_media=True,
    save_path="./downloads"
)

# 提取音频（视频→音频）
video_path = result.metadata['downloaded_video']
audio_path = video_path.replace('.mp4', '.mp3')
hub.convert_media(video_path, audio_path)

# 后续：音频转文字（需要额外的STT服务）
```

### 工作流3：微信公众号 → 归档PDF

```python
from skills.content_extractor.content_extractor import extract
from skills.document_hub.document_hub import write, convert

# 提取公众号文章
result = extract("https://mp.weixin.qq.com/s/xxx")

# 生成Word
doc_content = {
    "title": result.title,
    "paragraphs": [
        f"作者：{result.author}",
        f"发布时间：{result.publish_time}",
        "",
        result.content
    ]
}
write("文章.docx", doc_content)

# 转换为PDF
convert("文章.docx", "文章.pdf")
```

### 工作流4：多平台内容汇总

```python
from skills.content_extractor.content_extractor import batch_extract
import pandas as pd

# 批量提取多个平台的内容
urls = [
    "https://www.xiaoyuzhoufm.com/episode/xxx",  # 小宇宙
    "https://mp.weixin.qq.com/s/xxx",              # 公众号
    "https://www.bilibili.com/video/xxx",          # B站
]

results = batch_extract(urls)

# 汇总到Excel
excel_data = []
for result in results:
    excel_data.append({
        "平台": result.platform.value,
        "标题": result.title,
        "作者": result.author,
        "类型": "音频" if result.media_urls and result.platform.value in ['xiaoyuzhou'] else "视频/文章"
    })

# 保存Excel
import json
excel_content = {
    "sheets": {
        "内容汇总": {
            "data": excel_data
        }
    }
}
write("内容汇总.xlsx", excel_content)
```

## Skill映射关系

```
┌─────────────────────────────────────────────────────────────┐
│                    Content Extractor                         │
│                   (内容提取中心)                              │
└──────────────────┬──────────────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┬──────────────┐
    │              │              │              │
    ▼              ▼              ▼              ▼
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│小宇宙    │  │抖音      │  │微信公众号│  │B站      │
│播客      │  │短视频    │  │文章      │  │视频     │
└────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘
     │            │            │            │
     └────────────┴────────────┴────────────┘
                   │
                   ▼
          ┌─────────────────┐
          │ Document Hub    │
          │ (文档处理)       │
          │  • Word生成      │
          │  • PDF转换       │
          │  • Excel汇总     │
          └─────────────────┘
                   │
                   ▼
          ┌─────────────────┐
          │ MediaHub        │
          │ (音视频处理)     │
          │  • 音频提取      │
          │  • 视频转换      │
          │  • 格式转换      │
          └─────────────────┘
```

## 错误处理

```python
from skills.content_extractor.content_extractor import ExtractError

try:
    result = extract("https://invalid-url.com")
except ExtractError as e:
    print(f"提取失败: {e}")
```

## 扩展新平台

```python
# 在 ContentExtractor 类中添加新的提取方法
def _extract_new_platform(self, url: str, **options) -> ExtractResult:
    # 实现提取逻辑
    return ExtractResult(
        platform=Platform.NEW_PLATFORM,
        title="...",
        content="...",
        metadata={"url": url}
    )

# 在 __init__ 中注册
self.extractors[Platform.NEW_PLATFORM] = self._extract_new_platform
```

## 注意事项

1. **依赖浏览器**: 大部分平台需要使用Playwright模拟浏览器访问
2. **反爬限制**: 频繁提取可能触发平台反爬机制，建议添加延迟
3. **版权问题**: 下载内容仅供个人学习使用，请勿商用
4. **链接时效**: 部分平台链接有时效性，过期后无法提取

## 待办功能

- [ ] 自动处理滑动验证码
- [ ] 支持登录态提取
- [ ] 批量下载队列管理
- [ ] 提取历史记录
- [ ] 自动重试机制
