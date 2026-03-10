---
name: feishu-md-parser
description: Markdown解析子技能 - 将Markdown文件解析为飞书文档块格式，输出JSON文件，支持25种块类型映射。
---

# Markdown 解析子技能

## 职责
将 Markdown 文件解析为飞书文档块格式，输出 JSON 文件。

## 输入
- Markdown 文件路径（命令行参数或配置文件）

## 输出
- `output/blocks.json` - 解析后的块数据
- `output/metadata.json` - 解析元数据（块数量、表格数量等）

## 工作流程

### 第一步：读取 Markdown 文件
从指定路径读取 Markdown 文件内容。

### 第二步：解析 Markdown 内容
- 解析标题（# - ######）
- 解析列表（无序、有序）
- 解析表格
- 解析代码块
- 解析引用块
- 解析粗体/斜体
- 解析分割线

### 第三步：清理内容
- 移除零宽字符（\u200b, \u200c, \u200d, \ufeff）
- 清理表格单元格内容
- 处理粗体标记

### 第四步：输出 JSON 文件
将解析结果保存到 `output/blocks.json`。

## 数据格式

### blocks.json 格式
```json
{
  "blocks": [
    {
      "block_type": 2,
      "text": {
        "elements": [{"text_run": {"content": "文本内容"}}],
        "style": {}
      }
    },
    {
      "block_type": 31,
      "table": {
        "property": {
          "row_size": 3,
          "column_size": 2,
          "header_row": true
        },
        "data": [
          ["标题1", "标题2"],
          ["数据1", "数据2"],
          ["数据3", "数据4"]
        ]
      }
    }
  ],
  "metadata": {
    "total_blocks": 50,
    "table_count": 5,
    "heading_count": 10
  }
}
```

## 使用方式

### 命令行
```bash
python scripts/md_parser.py input.md output/blocks.json
```

### 作为子技能被调用
```python
# 主技能只传递文件路径
result = call_skill("feishu-md-parser", {
    "input_file": "path/to/markdown.md",
    "output_dir": "workflow/step1_parse"
})
# 返回: {"blocks_file": "workflow/step1_parse/blocks.json"}
```

## 与其他技能的协作
- 输出给 `feishu-doc-creator` 和 `feishu-block-adder`
- 只传递文件路径，不传递内容

---

## ⚠️ 重要：Callout 块的特殊处理

### 问题说明
Callout（高亮块）的颜色字段必须直接放在 `callout` 对象下，不能嵌套在 `style` 中。

### 正确格式
```json
{
    "block_type": 19,
    "callout": {
        "elements": [{"text_run": {"content": "警告信息"}}],
        "emoji_id": "warning",        // 直接在 callout 下
        "background_color": 1,        // 直接在 callout 下
        "border_color": 1,            // 直接在 callout 下
        "text_color": 1               // 直接在 callout 下
    }
}
```

### 错误格式（不要使用）
```json
{
    "block_type": 19,
    "callout": {
        "elements": [{"text_run": {"content": "警告信息"}}],
        "style": {  // ❌ 错误：不要嵌套在 style 中
            "emoji_id": "warning",
            "background_color": 1,
            "border_color": 1
        }
    }
}
```

### 代码实现
在 `md_parser.py` 第 150-189 行使用 Python 展开操作符：
```python
blocks.append({
    "block_type": 19,
    "callout": {
        "elements": [{"text_run": {"content": callout_text}}],
        **style  # 使用展开操作符，将样式字段直接展开到 callout 下
    }
})
```

### 验证方法
如果 API 返回的 callout 只有 `emoji_id` 而没有颜色字段，说明格式错误。详见 `TROUBLESHOOTING.md`。
