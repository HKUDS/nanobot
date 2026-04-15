
# sheets +write（写入单元格 / 覆盖写入）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

本 skill 对应 shortcut：`lark-cli sheets +write`。

- `--values` 必须是二维数组 JSON
- 内置尺寸校验：最多 5000 行、每行最多 100 列
- 若已传 `--sheet-id`，`--range` 可写 `A1:D10` 或 `C2`
- 若 `--range` 只给了 `<sheetId>` 或单个起始单元格，工具会按 `--values` 的尺寸自动展开为矩形范围

> [!CAUTION]
> 这是**写入操作** —— 执行前必须确认用户意图。可以先用 `--dry-run` 预览。

## 命令

```bash
# 覆盖写入一个矩形区域
lark-cli sheets +write --spreadsheet-token "shtxxxxxxxx" \
  --range "<sheetId>!A1:B2" \
  --values '[["name","age"],["alice",18]]'

# 已有 --sheet-id 时，可直接写相对范围
lark-cli sheets +write --url "https://example.larksuite.com/sheets/shtxxxxxxxx" \
  --sheet-id "<sheetId>" --range "C2" \
  --values '[["hello"]]'

# 只给 sheetId：会从 A1 开始，按 values 尺寸自动展开
lark-cli sheets +write --url "https://example.larksuite.com/sheets/shtxxxxxxxx" \
  --range "<sheetId>" \
  --values '[["hello","world"]]'

# 仅预览参数（不发请求）
lark-cli sheets +write --spreadsheet-token "shtxxxxxxxx" --range "<sheetId>!A1:B2" \
  --values '[["name","age"],["alice",18]]' --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--url <url>` | 否 | 电子表格 URL（与 `--spreadsheet-token` 二选一；支持 wiki URL） |
| `--spreadsheet-token <token>` | 否 | 表格 token（与 `--url` 二选一） |
| `--range <range>` | 否 | 写入范围：`<sheetId>!A1:D10`、`A1:D10` / `C2`（需配合 `--sheet-id`），或 `<sheetId>` |
| `--sheet-id <id>` | 否 | 工作表 ID（不提供 `--range` 时生效） |
| `--values <json>` | 是 | 二维数组 JSON（写入值） |
| `--dry-run` | 否 | 仅打印参数，不执行请求 |

## 输出

JSON，包含：

- `updated_range/updated_rows/updated_columns/updated_cells`
- `revision`

## 参考

- [lark-sheets-read](lark-sheets-read.md) — 写入前可先 read 验证范围
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
