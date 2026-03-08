---
name: feishu-doc-creator
description: 飞书文档创建统一入口技能。支持云盘和知识库两种方式创建文档并写入内容。...
---

# Feishu Document Creator

飞书文档创建统一入口技能。支持云盘和知识库两种方式创建文档并写入内容。

## 功能

- **云盘文档创建**：在指定云盘文件夹中创建文档
- **知识库文档创建**：在指定知识库节点下创建子文档
- **自动写入内容**：创建文档后自动写入 Markdown 内容
- **权限管理**：自动添加协作者权限

## 使用方法

### Python API

```python
from skills.feishu_doc_creator import create_drive_doc, create_wiki_doc

# 创建云盘文档
result = create_drive_doc(
    title="文档标题",
    content="# 正文\n\n内容...",
    folder_token="DYPXf8ZktlOCIXdmGq3cfjevn2F"  # 可选
)

# 创建知识库文档
result = create_wiki_doc(
    title="文档标题",
    content="# 正文\n\n内容...",
    parent_node_token="LmZ6wKwTViA4bSkVSYfcJGFcnRf"  # 可选
)
```

### 命令行

```bash
# 云盘方式
python3 skills/feishu-doc-creator/scripts/create_doc.py drive "标题" input.md

# 知识库方式
python3 skills/feishu-doc-creator/scripts/create_doc.py wiki "标题" input.md
```

## 配置

依赖飞书配置：`~/.claude/feishu-config.env`

- `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
- `FEISHU_DRIVE_FOLDER_TOKEN`（默认云盘文件夹）
- `FEISHU_PARENT_DAILY_REPORT`（默认知识库父节点）
- `FEISHU_AUTO_COLLABORATOR_ID`（自动添加权限的用户）

## 与旧技能的区别

| 旧技能 | 新技能 | 说明 |
|--------|--------|------|
| feishu-drive-doc-creator | feishu-doc-creator | 整合创建+写入 |
| feishu-wiki-doc-creator | feishu-doc-creator | 整合创建+写入 |
| feishu-wiki-child-creator | feishu-doc-creator | 整合创建+写入 |

## 底层实现

使用 `feishu-doc-orchestrator`（.agents/skills/）作为底层引擎。
