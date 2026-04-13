
# sheets +append（追加行）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

本 skill 对应 shortcut：`lark-cli sheets +append`。

- `--values` 必须是二维数组 JSON
- 内置尺寸校验：最多 5000 行、每行最多 100 列
- `--range` 可以是 `<sheetId>` 或 `<sheetId>!A1:D10`
- 若已传 `--sheet-id`，`--range` 也可写 `A1:D10` 或 `C2`

> [!CAUTION]
> 这是**写入操作** —— 执行前必须确认用户意图。可以先用 `--dry-run` 预览。

## 命令

```bash
# 追加一行（6 列示例）
lark-cli sheets +append --spreadsheet-token "shtxxxxxxxx" \
  --range "<sheetId>!A1" \
  --values '[["华东一仓","2026-03",125000,98000,168000,"41.7%"]]'

# 配合 --sheet-id，可直接写相对范围
lark-cli sheets +append --spreadsheet-token "shtxxxxxxxx" \
  --sheet-id "<sheetId>" --range "A1" \
  --values '[["A","B"]]'

# 仅预览参数（不发请求）
lark-cli sheets +append --spreadsheet-token "shtxxxxxxxx" --range "<sheetId>!A1" \
  --values '[["A","B"]]' --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--url <url>` | 否 | 电子表格 URL（与 `--spreadsheet-token` 二选一；支持 wiki URL） |
| `--spreadsheet-token <token>` | 否 | 表格 token（与 `--url` 二选一） |
| `--range <range>` | 否 | 追加范围：`<sheetId>!A1:D10`、`A1:D10` / `C2`（需配合 `--sheet-id`），或 `<sheetId>` |
| `--sheet-id <id>` | 否 | 工作表 ID（不提供 `--range` 时生效） |
| `--values <json>` | 是 | 二维数组 JSON（追加的行数据） |
| `--dry-run` | 否 | 仅打印参数，不执行请求 |

## 输出

JSON，包含：

- `table_range`
- `updated_range/updated_rows/updated_columns/updated_cells`
- `revision`

## 参考

- [lark-sheets-read](lark-sheets-read.md) — 追加后可 read 验证
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
