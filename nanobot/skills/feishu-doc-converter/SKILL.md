---
name: feishu-doc-converter
description: 飞书文档格式转换技能。支持文档与 Markdown 互转，以及外部链接转 Markdown。...
---

# Feishu Document Converter

飞书文档格式转换技能。支持文档与 Markdown 互转，以及外部链接转 Markdown。

## 功能

- **云文档 → Markdown**：将飞书文档导出为 Markdown
- **外部链接 → Markdown**：微信公众号、网页文章等转为 Markdown
- **批量转换**：支持批量处理多个文档/链接

## 使用方法

### Python API

```python
from skills.feishu_doc_converter import doc_to_md, url_to_md

# 云盘文档转 Markdown
md_content = doc_to_md("docx/UD18dxyZfoo4uRx4cTNchIc8nBe")
md_content = doc_to_md("https://feishu.cn/docx/xxx")

# 知识库文档（需在同一空间内有权限）
md_content = doc_to_md("https://uniquecapital.feishu.cn/wiki/xxx")

# 链接转 Markdown
md_content = url_to_md("https://mp.weixin.qq.com/s/xxx")
```

### 命令行

```bash
# 文档转 MD
python3 skills/feishu-doc-converter/scripts/convert.py doc "https://feishu.cn/docx/xxx" output.md

# 链接转 MD
python3 skills/feishu-doc-converter/scripts/convert.py url "https://mp.weixin.qq.com/s/xxx" output.md
```

## 支持的外部链接

| 平台 | 状态 | 说明 |
|------|------|------|
| 飞书云盘文档 | ✅ 支持 | API 方式（`doc_to_md`）或 Browser 方式（`url_to_md`） |
| 飞书知识库文档 | ✅ 支持 | Browser 方式（`url_to_md`，推荐） |
| 外部知识库 | ✅ 支持 | Browser 方式（`url_to_md`） |
| 微信公众号 | ✅ 支持 | API 方式（`url_to_md`） |
| 知乎 | 🚧 待实现 | - |
| 普通网页 | 🚧 待实现 | - |

## 使用建议

### 云盘文档导出
```python
# 方式1：API 方式（速度快，无需登录）
md = doc_to_md("docx/xxx")
md = doc_to_md("https://feishu.cn/docx/xxx")

# 方式2：Browser 方式（备用）
md = url_to_md("https://feishu.cn/docx/xxx")
```

### 知识库文档导出
```python
# 统一使用 url_to_md（Browser 方式，支持所有知识库）
md = url_to_md("https://waytoagi.feishu.cn/wiki/xxx")
md = url_to_md("https://uniquecapital.feishu.cn/wiki/xxx")
```

- 飞书配置：环境变量 `NANOBOT_CHANNELS__FEISHU__APP_ID` / `NANOBOT_CHANNELS__FEISHU__APP_SECRET`
- 微信抓取：复用 `content-extractor/wechat_fetcher`

## 与旧技能的关系

| 旧技能 | 功能迁移 |
|--------|---------|
| wechat-article-fetcher | 整合入 content-extractor 和 url_to_md |
