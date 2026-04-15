
# sheets +export（导出表格）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

本 skill 对应 shortcut：`lark-cli sheets +export`。

特性：

- 创建导出任务并轮询完成（默认最多约 30 秒）
- 支持导出 `xlsx` 或 `csv`
- 若提供 `--output-path`，会直接下载并保存到本地；否则输出 `file_token` 供后续处理

## 命令

```bash
# 导出为 xlsx 并保存到本地
lark-cli sheets +export --url "https://example.larksuite.com/sheets/shtxxxxxxxx" \
  --file-extension xlsx --output-path "./report.xlsx"

# 导出为 csv（必须指定 sheet-id）
lark-cli sheets +export --spreadsheet-token "shtxxxxxxxx" \
  --file-extension csv --sheet-id "<sheetId>" --output-path "./report.csv"

# 不下载：只获取 file_token
lark-cli sheets +export --spreadsheet-token "shtxxxxxxxx" --file-extension xlsx

# 仅预览参数（不发请求）
lark-cli sheets +export --url "https://..." --file-extension xlsx --output-path "./report.xlsx" --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--url <url>` | 否 | 电子表格 URL（与 `--spreadsheet-token` 二选一；支持 wiki URL） |
| `--spreadsheet-token <token>` | 否 | 表格 token（与 `--url` 二选一） |
| `--file-extension <ext>` | 是 | `xlsx` 或 `csv` |
| `--sheet-id <id>` | 否 | 工作表 ID（导出 `csv` 时必填；`xlsx` 可不填） |
| `--output-path <path>` | 否 | 本地保存路径；提供则自动下载保存 |
| `--dry-run` | 否 | 仅打印参数，不执行请求 |

## 输出

- 若提供 `--output-path`：输出 `file_path/file_name/file_size`
- 否则：输出 `file_token/file_name/file_size`

## 参考

- [lark-sheets-info](lark-sheets-info.md) — 先获取 `sheet_id`
- [lark-shared](../../lark-shared/SKILL.md)