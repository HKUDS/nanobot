---
name: feishu-card-parser
description: Parse Feishu/Lark interactive card messages to readable text. Use when extracting text, images, links, and mentions from Feishu card message JSON. Supports converting card content to Markdown or plain text format.
---

# Feishu Card Parser

Parse Feishu interactive card messages to readable text formats.

## When to Use This Skill

- Extract text content from Feishu card messages
- Parse rich text elements (text, lark_md, links, images)
- Extract @mentions and user references
- Convert card JSON to Markdown or plain text
- Process bot messages with interactive cards

## Quick Start

### Python API

```python
from skills.feishu_card_parser import parse_card_message, card_to_markdown

# Parse card JSON
card_json = '{"content":[[{"tag":"text","text":"Hello"}]]}'
result = parse_card_message(card_json)

print(result['text_content'])      # Plain text
print(result['markdown_content'])  # Markdown
print(result['images'])            # Image keys list
```

### Command Line

```bash
# Parse JSON file
python3 scripts/card_parser.py --input card.json --format markdown

# Parse raw string
python3 scripts/card_parser.py --text '{"content":[[{"tag":"text","text":"Hi"}]]}'
```

## Supported Card Elements

| Tag | Description | Output |
|-----|-------------|--------|
| `text` | Plain text | Text with style applied |
| `lark_md` | Lark Markdown | Standard Markdown |
| `img` | Image | Image key extracted |
| `link` | Link | URL + text |
| `at` | @mention | User ID + name |
| `code_block` | Code block | Language + code |
| `url` | URL preview | Link + title |

## Output Format

### JSON Output
```json
{
  "title": "Card Title",
  "text_content": "Plain text...",
  "markdown_content": "Markdown...",
  "images": ["img_v3_xxx"],
  "links": ["https://..."],
  "mentions": [{"id": "ou_xxx", "name": "User"}]
}
```

## Examples

### Extract Text from Bot Message
```python
from skills.feishu_card_parser import parse_card_message

# Raw card content from Feishu webhook
card_content = '{"title":"Alert","content":[[{"tag":"text","text":"Server down!"}]]}'
result = parse_card_message(card_content)

# Use extracted text
alert_text = result['text_content']  # "Server down!"
```

### Convert to Markdown
```python
from skills.feishu_card_parser import card_to_markdown

markdown = card_to_markdown(card_json)
# Returns formatted Markdown with headers, links, images
```
