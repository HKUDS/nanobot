
# drive +export

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

把 `doc` / `docx` / `sheet` / `bitable` 导出到本地文件。这个 shortcut 内置有限轮询：

- 如果导出任务在轮询窗口内完成，会直接下载到本地目录
- 如果轮询结束仍未完成，会返回 `ticket`、`ready=false`、`timed_out=true` 和 `next_command`
- 后续继续查结果时，改用 `drive +task_result --scenario export`
- 拿到 `file_token` 后，改用 `drive +export-download`

## 命令

```bash
# 导出新版文档为 pdf，默认保存到当前目录
lark-cli drive +export \
  --token "<DOCX_TOKEN>" \
  --doc-type docx \
  --file-extension pdf

# 导出旧版文档为 docx
lark-cli drive +export \
  --token "<DOC_TOKEN>" \
  --doc-type doc \
  --file-extension docx

# 导出 docx 为 markdown
# 注意：markdown 只支持 docx，底层走 /open-apis/docs/v1/content
lark-cli drive +export \
  --token "<DOCX_TOKEN>" \
  --doc-type docx \
  --file-extension markdown

# 导出电子表格为 xlsx
lark-cli drive +export \
  --token "<SHEET_TOKEN>" \
  --doc-type sheet \
  --file-extension xlsx \
  --output-dir ./exports

# 导出电子表格或多维表格为 csv 时，必须传 sub_id
lark-cli drive +export \
  --token "<SHEET_OR_BITABLE_TOKEN>" \
  --doc-type "<sheet|bitable>" \
  --file-extension csv \
  --sub-id "<SUB_ID>" \
  --output-dir ./exports

# 允许覆盖已存在文件
lark-cli drive +export \
  --token "<DOCX_TOKEN>" \
  --doc-type docx \
  --file-extension pdf \
  --overwrite
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--token` | 是 | 源文档 token |
| `--doc-type` | 是 | 源文档类型：`doc` / `docx` / `sheet` / `bitable` |
| `--file-extension` | 是 | 导出格式：`docx` / `pdf` / `xlsx` / `csv` / `markdown` |
| `--sub-id` | 条件必填 | 当 `sheet` / `bitable` 导出为 `csv` 时必填 |
| `--output-dir` | 否 | 本地输出目录，默认当前目录 |
| `--overwrite` | 否 | 覆盖已存在文件 |

## 关键约束

- `markdown` 只支持 `docx`
- `sheet` / `bitable` 导出为 `csv` 时必须带 `--sub-id`
- shortcut 内部固定有限轮询：最多 10 次，每次间隔 5 秒
- 轮询超时不是失败；会返回 `ticket`、`timed_out=true` 和 `next_command`，供后续继续查询

## 推荐续跑方式

```bash
# 第一步：先尝试直接导出
lark-cli drive +export \
  --token "<DOCX_TOKEN>" \
  --doc-type docx \
  --file-extension pdf

# 如果返回 ready=false / timed_out=true，再继续查
lark-cli drive +task_result \
  --scenario export \
  --ticket "<TICKET>" \
  --file-token "<DOCX_TOKEN>"

# 查到 file_token 后下载
lark-cli drive +export-download \
  --file-token "<EXPORTED_FILE_TOKEN>" \
  --output-dir ./exports
```

## 参考

- [lark-drive](../SKILL.md) -- 云空间全部命令
- [lark-shared](../../lark-shared/SKILL.md) -- 认证和全局参数
