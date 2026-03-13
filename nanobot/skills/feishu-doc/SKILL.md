---
name: feishu-doc
description: 飞书云文档 — 创建文档、读取文档内容、添加内容块、搜索文档、删除文档。当用户提及云文档、飞书文档、创建文档、读文档、写文档、文档内容、docx、doc时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 飞书云文档 (Doc)

飞书云文档 API，支持创建、读取、搜索、删除云文档，以及向文档中添加内容块。

## 使用流程

1. 根据下方 API 函数说明确认所需操作
2. 通过 `exec` 工具调用脚本执行

## API 函数

### list_files

获取云文档文件列表。

```
python3 scripts/feishu_doc.py list --limit 20
python3 scripts/feishu_doc.py list --parent-node fldcnXXX
```

返回: [{name, token, type, url, ...}]，type: "docx" / "sheet" / "bitable" / "folder" / "mindnote"

### get_doc

获取文档元信息（标题、创建时间、修订版本等）。

```
python3 scripts/feishu_doc.py get --document-id doxcnXXX
```

返回: {document_id, title, revision_id, ...}

### read_doc

读取云文档内容，返回 Markdown 格式纯文本。

```
python3 scripts/feishu_doc.py read --document-id doxcnXXX
```

### create_doc

创建新的云文档。支持通过 Markdown 一次性写入带样式的内容（标题、列表、加粗、斜体、引用）。

**推荐方式 — Markdown 内容写入（样式完整）：**

```
python3 scripts/feishu_doc.py create --title "周报" --content "# 本周重点\n\n## 技术\n\n- **项目A**进展顺利\n- 完成代码重构\n\n> 下周计划：上线 v2.0"
python3 scripts/feishu_doc.py create --title "方案" --content-file design.md
```

**仅创建空文档：**

```
python3 scripts/feishu_doc.py create --title "会议纪要"
python3 scripts/feishu_doc.py create --title "会议纪要" --folder-token fldcnXXX
```

支持的 Markdown 语法: `# ~ ######` 标题、`- * +` 无序列表、`1. 2.` 有序列表、`> ` 引用、`**加粗**`、`*斜体*`

写入策略: 优先一次性提交全部内容块（保证样式完整），若失败自动分批逐个写入。

返回: {document_id, revision_id, title, url}

### create_text_blocks

在文档中添加文本段落。

```
python3 scripts/feishu_doc.py create-block --document-id doxcnXXX --texts '["第一段","第二段"]'
python3 scripts/feishu_doc.py create-block --document-id doxcnXXX --block-id blkXXX --texts '["子块内容"]'
```

### delete_doc

删除云文档（移至回收站）。

```
python3 scripts/feishu_doc.py delete --document-id doxcnXXX
```

### search_docs

搜索云文档。

```
python3 scripts/feishu_doc.py search --keyword "季度报告" --limit 10
```

返回: [{docs_token, docs_type, url, ...}]

## 文档类型

| token 前缀 | 类型 |
|------------|------|
| `doxcn` | 旧版文档 (doc) |
| `docx` | 新版文档 (docx) |
| `shtcn` | 电子表格 (sheet) |
| `bascn` | 多维表格 (bitable) |

## 从 URL 提取 Token

```
https://xxx.feishu.cn/docx/{doc_token}     → 新版文档
```

## 常见错误

| 错误 | 正确做法 |
|------|----------|
| 并发写入同一文档 | 飞书文档不支持并发写入，需串行操作 |
| 应用无法访问已有文档 | 需将应用添加为文档协作者 |
| 创建文档报权限错误 | 需在飞书开放平台开通 `docx:document` 或 `docx:document:create` 权限 |

## 所需权限

- `drive:drive:readonly` — 查看云空间文件
- `drive:drive` — 管理云空间文件（删除）
- `docx:document:readonly` — 查看文档内容
- `docx:document` — 读写文档（读取 + 添加内容块）
- `docx:document:create` — 创建文档（仅创建也可用此权限）
- `docs:doc:search` — 搜索文档

## 凭据

自动读取 `~/.hiperone/config.json` 或环境变量 `NANOBOT_CHANNELS__FEISHU__APP_ID` / `NANOBOT_CHANNELS__FEISHU__APP_SECRET`，无需手动配置。
