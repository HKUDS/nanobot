# base +form-delete

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

删除多维表格数据表中的指定表单。**不可逆操作**，执行前务必确认。

## 命令

```bash
# 删除表单
lark-cli base +form-delete \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id>

# 预览（不实际执行）
lark-cli base +form-delete \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id> \
  --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 多维表格 App token（base_token） |
| `--table-id <id>` | 是 | 数据表 ID |
| `--form-id <id>` | 是 | 要删除的表单 ID |
| `--as` | 否 | 身份：user（默认）\| bot |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 输出格式

```json
{
  "ok": true,
  "data": {
    "deleted": true,
    "form_id": "vewX58te9D"
  }
}
```

## 工作流

> [!CAUTION]
> 这是**高风险写入操作（删除）** — 执行前必须明确向用户确认，告知此操作不可逆。

1. 先用 `+form-list` 或 `+form-get` 确认目标表单存在
2. 向用户展示将要删除的表单名称和 ID，等待明确确认
3. 执行删除
4. 报告删除结果

## 提示

- 删除前建议先用 `+form-questions-list` 了解表单内容，避免误删
- `form_id` 可通过 `+form-list` 查询

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
