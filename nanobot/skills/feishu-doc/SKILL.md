---
name: feishu-doc
description: |
  Feishu 文档**只读**工具。
  
  ⚠️ **重要**: 本技能仅用于读取文档，禁止写入操作。
  如需创建或修改文档，请使用 feishu-doc-orchestrator 技能。
---

# Feishu Document Tool (Read-Only)

飞书文档**只读**工具。支持读取、解析文档内容。

## ⚠️ 写入操作已禁用

本技能**不支持**以下操作：
- ❌ `create` - 创建文档
- ❌ `write` - 写入内容
- ❌ `append` - 追加内容
- ❌ `update_block` - 更新块
- ❌ `delete_block` - 删除块

**如需创建或修改文档，请使用**: `feishu-doc-orchestrator`

---

## Token 提取

从 URL `https://xxx.feishu.cn/docx/ABC123def` → `doc_token` = `ABC123def`

---

## 允许的操作

### 读取文档（快速预览）

```json
{ "action": "read", "doc_token": "ABC123def" }
```

**返回**：标题、纯文本内容、块统计

**适用场景**：快速了解文档内容，不需要结构化数据

**注意**：如果 `hint` 字段存在，表示有结构化内容（表格、图片等），需要使用 `list_blocks`

---

### 列出所有块（结构化内容）

```json
{ "action": "list_blocks", "doc_token": "ABC123def" }
```

**返回**：完整的块数据，包括表格、图片、代码块等

**适用场景**：需要提取表格数据、处理结构化内容

---

### 获取单个块

```json
{
  "action": "get_block",
  "doc_token": "ABC123def",
  "block_id": "doxcnXXX"
}
```

**返回**：指定块的详细内容

**适用场景**：只需要文档中的特定部分

---

## 读取工作流程

### 快速读取流程

```
1. 从 URL 提取 doc_token
2. 执行 read 获取纯文本内容
3. 检查 block_types 是否包含 Table/Image
4. 如需结构化数据，执行 list_blocks
```

### 示例

```json
// 第一步：快速读取
{ "action": "read", "doc_token": "ABC123def" }

// 响应包含 block_types: { "Table": 3, "Image": 2 }
// 表示有3个表格和2张图片

// 第二步：获取结构化数据
{ "action": "list_blocks", "doc_token": "ABC123def" }
```

---

## 使用场景

| 需求 | 推荐操作 | 说明 |
|------|----------|------|
| 快速了解文档内容 | `read` | 纯文本，速度快 |
| 需要表格数据 | `list_blocks` | 包含完整结构化数据 |
| 只需要特定部分 | `get_block` | 精准获取，节省Token |
| 检查文档是否存在 | `read` | 轻量级验证 |

---

## 与编排技能的分工

```
读取需求 → feishu-doc (本技能)
    ↓
创建/修改需求 → feishu-doc-orchestrator
    ↓
知识库需求 → feishu-wiki-orchestrator
```

---

## 配置

```yaml
channels:
  feishu:
    tools:
      doc: true  # 只读模式
```

---

## 权限要求

- `docx:document:readonly` - 文档读取权限

---

## 常见问题

### Q1: 如何创建新文档？
A: 请使用 `feishu-doc-orchestrator` 技能，支持原子操作创建+权限分配。

### Q2: 如何修改现有文档？
A: 请使用 `feishu-doc-orchestrator` 技能，支持断点续传和批量更新。

### Q3: 为什么禁用写入操作？
A: 原 `feishu-doc` 技能的写入操作存在以下问题：
- `create` 和 `write` 分离，容易创建空文档
- 表格格式不支持
- 位置控制弱（容易创建到错误位置）
- 无原子性保证

编排技能解决了这些问题，提供更可靠的文档创建流程。

---

*版本: v2.0 (Read-Only)*
*更新: 2026-02-24*
