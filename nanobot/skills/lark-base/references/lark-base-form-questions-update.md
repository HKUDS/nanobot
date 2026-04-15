# base +form-questions-update

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

批量更新多维表格表单/问卷中的问题（标题、描述、是否必填）。

## 命令

```bash
# 更新一个问题的标题
lark-cli base +form-questions-update \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id> \
  --questions '[{"id":"q_001","title":"您的真实姓名是？"}]'

# 同时更新多个问题
lark-cli base +form-questions-update \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id> \
  --questions '[
    {"id":"q_001","title":"姓名（必填）","required":true},
    {"id":"q_002","title":"联系方式","required":false}
  ]'
  
# 更新问题描述（纯文本）
lark-cli base +form-questions-update \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id> \
  --questions '[{"id":"q_001","description":"请填写您的真实姓名"}]'
# 更新问题描述（含链接）
lark-cli base +form-questions-update \
  --base-token <base_token> \
  --table-id <table_id> \
  --form-id <form_id> \
  --questions '[{"id":"q_001","description":"更多说明请参考[帮助文档](https://example.com/help)"}]'  
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 多维表格 App token（base_token） |
| `--table-id <id>` | 是 | 数据表 ID |
| `--form-id <id>` | 是 | 表单 ID |
| `--questions <json>` | 是 | 问题更新 JSON 数组，最多 10 个（见下方格式） |
| `--format` | 否 | 输出格式：json（默认）\| pretty \| table \| ndjson \| csv |
| `--as` | 否 | 身份：user（默认）\| bot |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## `--questions` 格式

每个问题对象必须包含 `id`，其余字段按需传入：

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | **是** | 问题 ID（field_id），不可修改 |
| `title` | 否 | 新的问题标题 |
| `description` | 否 | 新的问题描述（纯文本或 Markdown 链接，如 `[文本](https://example.com)`） |
| `required` | 否 | 是否必填 |
| `option_display_mode` | 否 | 选项展示方式（仅 `select` 有效）：`0`=下拉，`1`=纵向（默认），`2`=横向 |

## 输出格式

返回更新后的问题列表：

```json
{
  "ok": true,
  "data": {
    "items": [
      {"id": "q_001", "title": "姓名（必填）", "required": true}
    ]
  }
}
```

## 工作流

> [!CAUTION]
> 这是**写入操作** — 执行前必须向用户确认。

1. 先用 `+form-questions-list` 获取现有问题及其 `id`
2. 构造包含 `id` 的更新数组
3. 执行命令并报告更新结果

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
