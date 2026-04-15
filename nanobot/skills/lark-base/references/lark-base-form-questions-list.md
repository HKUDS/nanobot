# base +form-questions-list

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

列出多维表格表单/问卷中的所有问题。只读操作，不修改任何数据。

## 命令

```bash
# 列出表单所有问题
lark-cli base +form-questions-list \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id>

# 以表格形式展示
lark-cli base +form-questions-list \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id> \
  --format table

# 使用应用身份（bot）
lark-cli base +form-questions-list \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id> \
  --as bot
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 多维表格 App token（base_token） |
| `--table-id <id>` | 是 | 数据表 ID |
| `--form-id <id>` | 是 | 表单 ID |
| `--format` | 否 | 输出格式：json（默认）\| pretty \| table \| ndjson \| csv |
| `--as` | 否 | 身份：user（默认）\| bot |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 输出格式

每条问题包含以下字段：

| 字段 | 说明 |
|------|------|
| `id` | 问题 ID（即数据表的 field_id） |
| `title` | 问题标题 |
| `description` | 问题描述 |
| `required` | 是否必填 |

```json
{
  "ok": true,
  "data": {
    "questions": [
      {
        "id": "q_001",
        "title": "您的姓名是？",
        "description": "请填写真实姓名",
        "required": true
      },
      {
        "id": "q_002",
        "title": "您的联系方式是？",
        "description": "手机号或邮箱",
        "required": false
      }
    ],
    "total": 2
  }
}
```

## 提示

- 问题 `id` 与数据表的 `field_id` 相同
- 返回的问题列表已按顺序排列

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
