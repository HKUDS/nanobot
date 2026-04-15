
# sheets +find（查找单元格）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。
> **边界说明：** `sheets +find` 不是云空间搜索，只在一个已知 spreadsheet 内查找单元格内容。如果还不知道目标 spreadsheet 是哪一个，先用 [`lark-doc`](../../lark-doc/SKILL.md) 的 `docs +search` 定位文件；`docs +search` 的结果里会直接返回 `SHEET` 类型，再回到 `sheets +info` / `sheets +find`。

本 skill 对应 shortcut：`lark-cli sheets +find`。

特性：

- `--sheet-id` 必填（建议先用 `sheets +info` 获取）
- `--range` 可写完整范围（如 `<sheetId>!A1:D200`）
- 若已传 `--sheet-id`，`--range` 也可直接写 `A1:D200` 或 `C2`
- 默认**区分大小写**；加 `--ignore-case` 可不区分大小写
- 可选 `--search-by-regex` 按正则匹配

## 命令

```bash
# 在指定范围查找（默认区分大小写）
lark-cli sheets +find --url "https://example.larksuite.com/sheets/shtxxxxxxxx" \
  --sheet-id "<sheetId>" --find "张三" --range "A1:H200"

# 不区分大小写
lark-cli sheets +find --spreadsheet-token "shtxxxxxxxx" \
  --sheet-id "<sheetId>" --find "仓库管理营收报表" --range "H1:H500" --ignore-case

# 正则查找
lark-cli sheets +find --spreadsheet-token "shtxxxxxxxx" \
  --sheet-id "<sheetId>" --find "仓库管理营收报表" --range "H1:H500" --search-by-regex

# 仅预览参数（不发请求）
lark-cli sheets +find --url "https://..." --sheet-id "<sheetId>" --find "xxx" --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--url <url>` | 否 | 电子表格 URL（与 `--spreadsheet-token` 二选一；支持 wiki URL） |
| `--spreadsheet-token <token>` | 否 | 表格 token（与 `--url` 二选一） |
| `--sheet-id <id>` | 是 | 工作表 ID（可通过 `+info` 获取） |
| `--find <text>` | 是 | 查找内容（字符串或正则） |
| `--range <range>` | 否 | 范围（如 `<sheetId>!A1:D200`，或 `A1:D200` / `C2` 配合 `--sheet-id`）；不填则搜索整个工作表 |
| `--ignore-case` | 否 | 不区分大小写（默认区分） |
| `--match-entire-cell` | 否 | 完全匹配单元格 |
| `--search-by-regex` | 否 | 使用正则 |
| `--include-formulas` | 否 | 搜索公式 |
| `--dry-run` | 否 | 仅打印参数，不执行请求 |

## 输出

JSON，包含：

- `matched_cells`
- `matched_formula_cells`
- `rows_count`

## 参考

- [lark-sheets-info](lark-sheets-info.md)
- [lark-shared](../../lark-shared/SKILL.md)
