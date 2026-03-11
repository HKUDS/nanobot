---
name: feishu-card-parser
description: 飞书卡片消息解析器 - 解析飞书 Interactive Card 消息为可读文本
platform: feishu
version: 1.0.0
---

# Feishu Card Parser

飞书卡片消息解析器 - 将飞书的富文本卡片解析为 Markdown 或纯文本格式。

## 功能

- 解析飞书卡片消息的 JSON 结构
- 提取文本内容（包括 `text`、`lark_md` 格式）
- 提取图片 key 列表
- 提取链接、@用户等信息
- 转换为 Markdown 格式

## 使用方法

### Python API

```python
from skills.feishu_card_parser import parse_card_message, card_to_markdown

# 解析卡片消息
card_json = '{"title":"","content":[[{"tag":"text","text":"内容"}]]}'
result = parse_card_message(card_json)

# 转换为 Markdown
markdown = card_to_markdown(card_json)
```

### 命令行

```bash
# 解析 JSON 文件
python3 skills/feishu-card-parser/card_parser.py --input card.json --format markdown

# 解析字符串
python3 skills/feishu-card-parser/card_parser.py --text '{"title":"标题","content":[[{"tag":"text","text":"内容"}]]}'
```

## 支持的卡片元素

| 标签 | 说明 | 解析方式 |
|------|------|---------|
| `text` | 普通文本 | ✅ 直接提取 |
| `lark_md` | Lark Markdown | ✅ 转换为标准 Markdown |
| `img` | 图片 | ✅ 提取 image_key |
| `link` | 链接 | ✅ 提取 URL |
| `at` | @用户 | ✅ 提取用户ID和名称 |
| `code_block` | 代码块 | ✅ 提取代码内容 |
| `url` | 预览卡片 | ✅ 提取链接和标题 |

## 输出格式

### Markdown 格式
```markdown
# 卡片标题

正文内容...

![图片](img_v3_xxx)

[@用户名](ou_xxx)
```

### JSON 格式
```json
{
  "title": "卡片标题",
  "text_content": "纯文本内容",
  "markdown_content": "Markdown 内容",
  "images": ["img_v3_xxx"],
  "links": ["https://..."],
  "mentions": [{"id": "ou_xxx", "name": "用户"}]
}
```

## 依赖

```bash
pip install json
```

## 示例

```python
from skills.feishu_card_parser import parse_card_message

# 示例：解析收到的飞书消息
raw_content = '{"title":"","content":[[{"tag":"text","text":"项目更新"}]]}'
result = parse_card_message(raw_content)

print(result['text_content'])  # 输出: 项目更新
```
