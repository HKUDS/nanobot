
# sheets +info（查看表格/工作表信息）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

本 skill 对应 shortcut：`lark-cli sheets +info`。

用于：

- 从表格 URL / token 获取 `spreadsheet_token`
- 列出工作表（`sheet_id`、标题、行列数等），便于后续 `+read/+write/+find/+export` 使用

## 命令

```bash
# 传 URL（支持用户粘贴时带空格/引号/反引号；支持 wiki URL）
lark-cli sheets +info --url "https://example.larksuite.com/sheets/shtxxxxxxxx"

# 传 spreadsheet_token
lark-cli sheets +info --spreadsheet-token "shtxxxxxxxx"

# 仅预览请求参数（不发请求）
lark-cli sheets +info --url "https://..." --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--url <url>` | 否 | 电子表格 URL（与 `--spreadsheet-token` 二选一；支持 wiki URL） |
| `--spreadsheet-token <token>` | 否 | 表格 token（与 `--url` 二选一） |
| `--dry-run` | 否 | 仅打印参数，不执行请求 |

## 输出

JSON，包含：

- `spreadsheet_token`：后续命令复用
- `sheets[]`：每个工作表的 `sheet_id`、`title`、`row_count`、`column_count` 等

## 参考

- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数