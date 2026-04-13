
# docs +update（更新飞书云文档）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

更新飞书云文档内容，支持 7 种更新模式。优先使用局部更新（replace_range/append/insert_before/insert_after），慎用 overwrite（会清空文档重写，可能丢失图片、评论等）。

## 重要说明
> **⚠️ 本文档中提到的 html 标签不需要在 Markdown 中转义！若转义，会导致相关的表格，多维表格，画板等 block 插入失败**

## 命令

```bash
# 追加内容
lark-cli docs +update --doc "<doc_id_or_url>" --mode append --markdown "## 新章节\n\n追加内容"

# 定位替换（内容定位）
lark-cli docs +update --doc "<doc_id>" --mode replace_range --selection-with-ellipsis "旧标题...旧结尾" --markdown "## 新内容"

# 定位替换（标题定位）
lark-cli docs +update --doc "<doc_id>" --mode replace_range --selection-by-title "## 功能说明" --markdown "## 功能说明\n\n新内容"

# 全文替换
lark-cli docs +update --doc "<doc_id>" --mode replace_all --selection-with-ellipsis "张三" --markdown "李四"

# 前插入
lark-cli docs +update --doc "<doc_id>" --mode insert_before --selection-with-ellipsis "## 危险操作" --markdown "> 警告：以下需谨慎！"

# 后插入
lark-cli docs +update --doc "<doc_id>" --mode insert_after --selection-with-ellipsis "代码示例" --markdown "**输出示例**：result = 42"

# 删除内容
lark-cli docs +update --doc "<doc_id>" --mode delete_range --selection-by-title "## 废弃章节"

# 覆盖（慎用）
lark-cli docs +update --doc "<doc_id>" --mode overwrite --markdown "# 全新内容"

# 同时更新标题
lark-cli docs +update --doc "<doc_id>" --mode append --markdown "## 更新日志" --new-title "文档 v2.0"

# 在指定内容后新增两个空白画板
lark-cli docs +update --doc "<doc_id>" --mode insert_after --selection-with-ellipsis "有序列表" --markdown $'<whiteboard type="blank"></whiteboard>\n<whiteboard type="blank"></whiteboard>'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--doc` | 是 | 文档 URL 或 token |
| `--mode` | 是 | 更新模式（见下方 7 种模式说明） |
| `--markdown` | 视模式 | 新内容（Lark-flavored Markdown）。delete_range 模式不需要，其他模式必填。若要新增空白画板，直接传 `<whiteboard type="blank"></whiteboard>`；需要多个画板时，在同一个 markdown 里重复多个标签 |
| `--selection-with-ellipsis` | 视模式 | 内容定位（如 `"开头...结尾"`）。与 `--selection-by-title` 互斥 |
| `--selection-by-title` | 视模式 | 标题定位（如 `"## 章节名"`）。与 `--selection-with-ellipsis` 互斥 |
| `--new-title` | 否 | 同时更新文档标题 |

# 定位方式

定位模式（replace_range/replace_all/insert_before/insert_after/delete_range）支持两种定位方式，二选一：

## selection-with-ellipsis - 内容定位

支持两种格式：

1. **范围匹配**：`开头内容...结尾内容`
   - 匹配从开头到结尾的所有内容（包含中间内容）
   - 建议 10-20 字符确保唯一性

2. **精确匹配**：`完整内容`（不含 `...`）
   - 匹配完整的文本内容
   - 适合替换短文本、关键词等

**转义说明**：如果要匹配的内容本身包含 `...`，使用 `\.\.\.` 表示字面量的三个点。

示例：
- `你好...世界` → 匹配从"你好"到"世界"之间的任意内容
- `你好\.\.\.世界` → 匹配字面量 "你好...世界"

**建议**：如果文档中有多个 `...`，建议使用更长的上下文来精确定位，避免歧义。

## selection-by-title - 标题定位

格式：`## 章节标题`（可带或不带 # 前缀）

自动定位整个章节（从该标题到下一个同级或更高级标题之前）。

**示例**：
- `## 功能说明` → 定位二级标题"功能说明"及其下所有内容
- `功能说明` → 定位任意级别的"功能说明"标题及其内容

# 可选参数

## new-title

更新文档标题。如果提供此参数，将在更新文档内容后同步更新文档标题。

**特性**：
- 仅支持纯文本，不支持富文本格式
- 长度限制：1-800 字符
- 可以与任何 mode 配合使用
- 标题更新在内容更新之后执行

# 返回值

## 成功

```json
{
  "success": true,
  "doc_id": "文档ID",
  "mode": "使用的模式",
  "board_tokens": ["可选：新建画板 token 列表"],
  "message": "文档更新成功（xxx模式）",
  "warnings": ["可选警告列表"],
  "log_id": "请求日志ID"
}
```

如果本次 `docs +update` 创建了画板，响应会额外返回 `board_tokens`。在 CLI 的成功 JSON 输出里，后续编辑画板应读取 `data.board_tokens`。

## 异步模式（大文档超时）

```json
{
  "task_id": "async_task_xxxx",
  "message": "文档更新已提交异步处理，请使用 task_id 查询状态",
  "log_id": "请求日志ID"
}
```

## 错误

```json
{
  "error": "[错误码] 错误消息\n💡 Suggestion: 修复建议\n📍 Context: 上下文信息",
  "log_id": "请求日志ID"
}
```

---

# 使用示例

## append - 追加到末尾

```bash
lark-cli docs +update --doc "文档ID或URL" --mode append --markdown "## 新章节\n\n追加的内容..."
```

## replace_range - 定位替换

使用 `--selection-with-ellipsis`：
```bash
lark-cli docs +update --doc "文档ID" --mode replace_range --selection-with-ellipsis "## 旧标题...旧结尾。" --markdown "## 新标题\n\n新的内容..."
```

使用 `--selection-by-title`（替换整个章节）：
```bash
lark-cli docs +update --doc "文档ID" --mode replace_range --selection-by-title "## 功能说明" --markdown "## 功能说明\n\n更新后的内容..."
```

## replace_all - 全文替换

```bash
lark-cli docs +update --doc "文档ID" --mode replace_all --selection-with-ellipsis "张三" --markdown "李四"
```

返回值包含 `replace_count` 字段，表示替换的次数。

**注意**：
- 与 `replace_range` 不同，`replace_all` 允许多个匹配
- 如果没有找到匹配内容，会返回错误
- `--markdown` 可以为空字符串，表示删除所有匹配内容

## delete_range - 删除内容

```bash
lark-cli docs +update --doc "文档ID" --mode delete_range --selection-by-title "## 废弃章节"
```

注意：delete_range 模式不需要 `--markdown` 参数。

## overwrite - 完全覆盖

⚠️ 会清空文档后重写，可能丢失图片、评论等，仅在需要完全重建文档时使用。

```bash
lark-cli docs +update --doc "文档ID" --mode overwrite --markdown "# 新文档\n\n全新的内容..."
```

## 创建空白画板

当用户要“新增空白画板”时，不要用 Mermaid 占位图；直接按 whiteboard 标签传 `--markdown`。

自然语言请求示例：
- “给我在这个文档末尾新增一个空白画板”

```bash
# 追加一个空白画板
lark-cli docs +update --doc "文档ID" --mode append --markdown '<whiteboard type="blank"></whiteboard>'

# 在指定内容后新增两个空白画板
lark-cli docs +update --doc "文档ID" --mode insert_after --selection-with-ellipsis "有序列表" --markdown $'<whiteboard type="blank"></whiteboard>\n<whiteboard type="blank"></whiteboard>'
```

成功后，响应里的 `data.board_tokens` 就是新建画板的 token 列表；如果后续要继续编辑这些画板，直接使用这些 token。

---

# 最佳实践

## 重要：画板编辑

> **⚠️ docs +update 不能编辑已有画板内容，但可以创建新的空白画板**

画板编辑：详见 [SKILL.md](../SKILL.md#重要说明画板编辑)

## 小粒度精确替换

修改文档内容时，**定位范围越小越安全**。尤其是表格、分栏等嵌套块，应精确定位到需要修改的文本，避免影响其他内容。

## 保护不可重建的内容

图片、画板、电子表格、多维表格、任务等内容以 token 形式存储，**无法读出后原样写入**。

**保护策略**：
- 替换时避开包含这些内容的区域
- 精确定位到纯文本部分进行修改

## 分步更新优于整体覆盖

修改多处内容时：
- ✅ 多次小范围替换，逐步修改
- ⚠️ 谨慎使用 `overwrite` 重写整个文档，除非你认为风险完全可控

**原因**：局部更新保留原有媒体、评论、协作历史，更安全可靠。

## insert 模式扩大定位范围时注意插入位置

使用 `insert_before` 或 `insert_after` 时，如果目标内容重复出现，需要扩大 `--selection-with-ellipsis` 范围来唯一定位。

**关键**：插入位置基于匹配范围的**边界**：
- `insert_after` → 插入在匹配范围的**结尾**之后
- `insert_before` → 插入在匹配范围的**开头**之前

## 修复画板语法错误

当 `docs +create` 或 `docs +update` 返回画板写入失败的 warning 时：
1. warning 中包含 whiteboard 标签（如 `<whiteboard token="xxx"/>`）
2. 分析错误信息，修正 Mermaid/PlantUML 语法
3. 用 `--mode replace_range` 替换：`--selection-with-ellipsis` 使用 warning 中的 whiteboard 标签，`--markdown` 提供修正后的代码块
4. 重新提交验证

---

# 注意事项

- **Markdown 语法**：支持飞书扩展语法，详见 [lark-doc-create](lark-doc-create.md) 工具文档

## 参考

- [lark-doc-fetch](lark-doc-fetch.md) — 获取文档
- [lark-doc-create](lark-doc-create.md) — 创建文档（含完整 Markdown 格式参考）
- [lark-doc-media-insert](lark-doc-media-insert.md) — 插入图片/文件到文档
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
