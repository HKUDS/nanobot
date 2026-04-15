# base +form-create

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

在多维表格数据表中创建新表单。

## ⚠️ 注意事项

- **表格选择**：创建问卷前先考虑：这是新的业务领域吗？如果是，建议先用 `+table-create` 创建新表格
- **命名一致性**：问卷名称应与表格用途相关，避免在通用表格（如"收集表"）中创建不相关的问卷

## 命令

```bash
# 创建表单（仅必填参数）
lark-cli base +form-create \
  --base-token <base_token> \
  --table-id <table_id> \
  --name "用户调研问卷"

# 创建时附带描述（纯文本）
lark-cli base +form-create \
  --base-token <base_token> \
  --table-id <table_id> \
  --name "用户调研问卷" \
  --description "2024年度用户满意度调研"

# 创建时附带描述（含链接）
lark-cli base +form-create \
  --base-token <base_token> \
  --table-id <table_id> \
  --name "用户调研问卷" \
  --description "2024年度调研，[详情请查看](https://example.com)"

# 使用应用身份（bot）
lark-cli base +form-create \
  --base-token <base_token> \
  --table-id <table_id> \
  --name "用户调研问卷" \
  --as bot
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 多维表格 App token（base_token） |
| `--table-id <id>` | 是 | 数据表 ID |
| `--name <name>` | 是 | 表单名称 |
| `--description <string>` | 否 | 表单描述（纯文本或 Markdown 链接，如 `[文本](https://example.com)`） |
| `--format` | 否 | 输出格式：json（默认）\| pretty \| table \| ndjson \| csv |
| `--as` | 否 | 身份：user（默认）\| bot |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 输出格式

| 字段 | 说明 |
|------|------|
| `id` | 新创建的表单 ID |
| `name` | 表单名称 |
| `description` | 表单描述 |

```json
{
  "ok": true,
  "data": {
    "id": "vewX58te9D",
    "name": "用户调研问卷",
    "description": "2024年度用户满意度调研"
  }
}
```

## 工作流

> [!CAUTION]
> 这是**写入操作** — 执行前必须向用户确认。

1. 确认目标 `app_token` 和 `table_id`
2. 确认表单名称和描述
3. 执行命令
4. 报告返回的 `form_id`，后续可用于添加问题（`+form-questions-create`）

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
