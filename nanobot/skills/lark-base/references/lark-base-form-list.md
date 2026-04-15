# base +form-list

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

列出多维表格数据表中的所有表单。自动翻页，一次性返回全量结果。只读操作，不修改任何数据。

## 命令

```bash
# 列出指定数据表的所有表单
lark-cli base +form-list \
  --base-token <base_token> \
  --table-id <table_id>

# 以表格形式展示
lark-cli base +form-list \
  --base-token <base_token> \
  --table-id <table_id> \
  --format table

# 使用应用身份（bot）
lark-cli base +form-list \
  --base-token <base_token> \
  --table-id <table_id> \
  --as bot
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 多维表格 App token（base_token） |
| `--table-id <id>` | 是 | 数据表 ID |
| `--page-size <n>` | 否 | 每次请求的分页大小，默认 100，最大 100 |
| `--format` | 否 | 输出格式：json（默认）\| pretty \| table \| ndjson \| csv |
| `--as` | 否 | 身份：user（默认）\| bot |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 输出格式

每条表单包含以下字段：

| 字段 | 说明 |
|------|------|
| `id` | 表单 ID（如 `vewX58te9D`） |
| `name` | 表单名称 |
| `description` | 表单描述 |

JSON 输出示例（`--format json`，默认）：

```json
{
  "ok": true,
  "data": {
    "forms": [
      {"id": "vewX58te9D", "name": "用户调研问卷", "description": "..."},
      {"id": "form_yyyy",  "name": "产品反馈表",   "description": "..."}
    ],
    "total": 2
  }
}
```

## 提示

- `base_token` 在多维表格 URL 中可找到（形如 `bascnXXXX`）
- `table_id` 可通过 `lark-cli base app.tables list --app-token <token> --params '{"app_token":"<token>"}'` 获取
- 如无表单，输出 `forms: []`

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
