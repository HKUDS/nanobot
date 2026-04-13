# base +form-questions-delete

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

从多维表格表单中批量删除问题。**不可逆操作**，执行前务必确认。

## 命令

```bash
# 删除一个问题
lark-cli base +form-questions-delete \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id> \
  --question-ids '["q_001"]'

# 批量删除多个问题
lark-cli base +form-questions-delete \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id> \
  --question-ids '["q_001","q_002","q_003"]'

# 预览（不实际执行）
lark-cli base +form-questions-delete \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id> \
  --question-ids '["q_001"]' \
  --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 多维表格 App token（base_token） |
| `--table-id <id>` | 是 | 数据表 ID |
| `--form-id <id>` | 是 | 表单 ID |
| `--question-ids <json>` | 是 | 要删除的问题 ID JSON 数组，最多 10 个，如 `'["q_001","q_002"]'` |
| `--as` | 否 | 身份：user（默认）\| bot |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 输出格式

```json
{
  "ok": true,
  "data": {
    "deleted": true,
    "question_ids": ["q_001", "q_002"]
  }
}
```

## 工作流

> [!CAUTION]
> 这是**高风险写入操作（删除）** — 执行前必须明确向用户确认，告知此操作不可逆。

1. 先用 `+form-questions-list` 查看问题列表，确认要删除的 `id`
2. 向用户展示将要删除的问题标题和 ID，等待明确确认
3. 执行删除并报告结果

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
