
# sheets +read（读取单元格）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

本 skill 对应 shortcut：`lark-cli sheets +read`。

内置能力：

- 支持 `--url` / `--spreadsheet-token` 二选一（URL 支持 wiki；支持粘贴时带空格/引号/反引号）
- 若已传 `--sheet-id`，`--range` 可写 `A1:D10` 或 `C2`
- 将单元格富文本 segment 数组拍平成纯文本，减少输出冗余
- 默认最多返回 200 行（超出会 `truncated=true`）

## 命令

```bash
# 读取指定范围（推荐）
lark-cli sheets +read --url "https://example.larksuite.com/sheets/shtxxxxxxxx" \
  --range "<sheetId>!A1:H20"

# 配合 --sheet-id，可直接写相对范围或单个单元格
lark-cli sheets +read --spreadsheet-token "shtxxxxxxxx" \
  --sheet-id "<sheetId>" --range "C2"

# 仅指定工作表（不含 A1:D10），读取整个工作表（仍会做 200 行截断）
lark-cli sheets +read --spreadsheet-token "shtxxxxxxxx" --range "<sheetId>"

# 不指定 range：读取 --sheet-id 对应工作表；再不指定则读取第一个工作表
lark-cli sheets +read --spreadsheet-token "shtxxxxxxxx" --sheet-id "<sheetId>"

# 控制值渲染方式
lark-cli sheets +read --url "https://..." --range "<sheetId>!A1:D10" --value-render-option Formula

# 仅预览参数（不发请求）
lark-cli sheets +read --url "https://..." --range "<sheetId>!A1:D10" --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--url <url>` | 否 | 电子表格 URL（与 `--spreadsheet-token` 二选一；支持 wiki URL） |
| `--spreadsheet-token <token>` | 否 | 表格 token（与 `--url` 二选一） |
| `--range <range>` | 否 | 读取范围：`<sheetId>!A1:D10`、`A1:D10` / `C2`（需配合 `--sheet-id`），或 `<sheetId>` |
| `--sheet-id <id>` | 否 | 工作表 ID（不提供 `--range` 时生效） |
| `--value-render-option <opt>` | 否 | `ToString`（默认）/ `FormattedValue` / `Formula` / `UnformattedValue` |
| `--dry-run` | 否 | 仅打印参数，不执行请求 |

## 输出

JSON，包含：

- `range`：服务端实际读取的范围
- `values`：二维数组（已做富文本拍平）
- `truncated/total_rows`：当行数超过 200 时出现

## 参考

- [lark-sheets-info](lark-sheets-info.md) — 先获取 `sheet_id`
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
