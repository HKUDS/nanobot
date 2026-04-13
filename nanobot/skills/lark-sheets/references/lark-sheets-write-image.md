
# sheets +write-image（写入图片到单元格）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

本 skill 对应 shortcut：`lark-cli sheets +write-image`。

特性：

- 将本地图片文件写入到电子表格的指定单元格
- 支持格式：PNG、JPEG、JPG、GIF、BMP、JFIF、EXIF、TIFF、BPG、HEIC
- `--range` 的起始和结束单元格必须相同（单个单元格），如 `A1` 或 `<sheetId>!B2:B2`
- `--name` 默认取 `--image` 的文件名

> [!CAUTION]
> 这是**写入操作** —— 执行前必须确认用户意图。可以先用 `--dry-run` 预览。

## 命令

```bash
# 写入图片到指定单元格
lark-cli sheets +write-image --spreadsheet-token "shtxxxxxxxx" \
  --range "<sheetId>!B2:B2" \
  --image "./logo.png"

# 使用 URL + sheet-id，指定单个单元格
lark-cli sheets +write-image --url "https://example.larksuite.com/sheets/shtxxxxxxxx" \
  --sheet-id "<sheetId>" --range "C3" \
  --image "./chart.jpg"

# 自定义图片名称
lark-cli sheets +write-image --spreadsheet-token "shtxxxxxxxx" \
  --range "<sheetId>!A1:A1" \
  --image "./output.png" --name "revenue_chart.png"

# 仅预览参数（不发请求）
lark-cli sheets +write-image --spreadsheet-token "shtxxxxxxxx" \
  --range "<sheetId>!B2:B2" --image "./logo.png" --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|----|------|
| `--url <url>` | 否  | 电子表格 URL（与 `--spreadsheet-token` 二选一） |
| `--spreadsheet-token <token>` | 否  | 表格 token（与 `--url` 二选一） |
| `--range <range>` | 是  | 目标单元格：`<sheetId>!A1:A1`、`A1`（需配合 `--sheet-id`） |
| `--sheet-id <id>` | 否  | 工作表 ID |
| `--image <path>` | 是  | 本地图片文件的**相对路径**（必须在当前目录下，如 `./logo.png`；不支持绝对路径）|
| `--name <filename>` | 否  | 图片文件名（含扩展名，默认取 `--image` 的文件名） |
| `--dry-run` | 否  | 仅打印参数，不执行请求 |

## 输出

JSON，包含：

- `spreadsheetToken` — 表格 token
- `updateRange` — 图片写入的单元格范围
- `revision` — 工作表版本号

## 参考

- [lark-sheets-write](lark-sheets-write.md) — 写入普通单元格数据
- [lark-sheets-read](lark-sheets-read.md) — 写入前可先 read 验证范围
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
