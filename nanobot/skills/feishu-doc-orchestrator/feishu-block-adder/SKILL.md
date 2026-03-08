---
name: feishu-block-adder
description: 块添加子技能 - 将解析后的块数据添加到飞书文档，分批处理，支持表格和普通块。
---

# 块添加子技能

## 职责
将解析后的块数据添加到飞书文档，分批处理以避免 API 限制。

## 输入
- `blocks.json` - 由 feishu-md-parser 生成
- `doc_info.json` - 由 feishu-doc-creator-v2 生成

## 输出
- `output/add_result.json` - 添加结果统计

## 工作流程

### 第一步：加载块数据
从 `blocks.json` 加载解析后的块。

### 第二步：加载文档信息
从 `doc_info.json` 加载文档 ID。

### 第三步：分批添加块
- 每批最多 20 个块
- 表格单独处理
- 普通块批量添加

### 第四步：保存结果
保存添加结果到 `output/add_result.json`。

## 数据格式

### add_result.json 格式
```json
{
  "success": true,
  "document_id": "U2wNd2rMkot6fzxr67ScN7hJn7c",
  "total_blocks": 290,
  "tables_created": 10,
  "regular_blocks": 280,
  "batches": 15,
  "duration_seconds": 5.2
}
```

## 使用方式

### 命令行
```bash
python scripts/block_adder.py workflow/step1_parse/blocks.json workflow/step2_create/doc_info.json output
```

### 作为子技能被调用
```python
result = call_skill("feishu-block-adder", {
    "blocks_file": "workflow/step1_parse/blocks.json",
    "doc_info_file": "workflow/step2_create/doc_info.json",
    "output_dir": "workflow/step3_add_blocks"
})
```

## 与其他技能的协作
- 接收来自 `feishu-md-parser` 的块数据
- 接收来自 `feishu-doc-creator-with-permission` 的文档信息
- 输出给 `feishu-doc-verifier` 和 `feishu-logger`

## 支持的块类型

### 当前支持的块类型（13种）

| block_type | 名称 | 状态 | 说明 |
|------------|------|------|------|
| 2 | text | ✅ | 普通文本 |
| 3-8 | heading1-6 | ✅ | 一到六级标题 |
| 12 | bullet | ✅ | 无序列表 |
| 13 | ordered | ✅ | 有序列表 |
| 14 | code | ✅ | 代码块 |
| 15 | quote | ✅ | 引用块 |
| 22 | divider | ✅ | 分割线 |
| 31 | table | ✅ | 表格（特殊处理） |

### 完整块类型参考

详细的块类型支持情况请查看：
- `.claude/skills/feishu-md-parser/BLOCK_TYPES.md`

### 添加新块类型

1. 在 `feishu-md-parser/scripts/md_parser.py` 中添加解析逻辑
2. 在 `scripts/block_adder.py` 的有效块类型检查中添加新类型
3. 参考 `BLOCK_TYPES.md` 中的示例代码

```python
# 在 block_adder.py 中添加新块类型（约第 247 行）
if block_copy.get("block_type") in [
    2, 3, 4, 5, 6, 7, 8,      # text, headings
    12, 13,                    # lists
    14,                        # code
    15,                        # quote
    19,                        # callout (新增示例)
    22,                        # divider
]:
    valid_blocks.append(block_copy)
```

---

## ⚠️ 重要：Callout 块 (block_type: 19) 的特殊处理

### 关键问题
**Callout 块的颜色字段必须直接放在 `callout` 对象下，不能嵌套在 `style` 中。**

### 正确格式
```json
{
    "block_type": 19,
    "callout": {
        "elements": [{"text_run": {"content": "警告信息"}}],
        "emoji_id": "warning",
        "background_color": 1,
        "border_color": 1,
        "text_color": 1
    }
}
```

### 代码实现
在 `block_adder.py` 第 130-178 行：

```python
def create_callout_with_children(token, config, document_id, callout_style, callout_content):
    payload = {
        "children": [{
            "block_type": 19,
            "callout": {
                "elements": [{"text_run": {"content": callout_content}}],
                **callout_style  # 关键：使用展开操作符
            }
        }],
        "index": -1
    }
    # ... 调用 API
```

### 验证方法
检查 API 返回的 callout 对象是否包含颜色字段：

```python
returned_callout = result["data"]["children"][0].get("callout", {})
if "background_color" not in returned_callout:
    print("❌ 格式错误：颜色字段未被保存")
```

### 详细说明
- 代码注释：第 130-178 行
- 问题排查：`../feishu-doc-orchestrator/TROUBLESHOOTING.md`
- 测试脚本：`../feishu-doc-orchestrator/test_callout_only.py`
