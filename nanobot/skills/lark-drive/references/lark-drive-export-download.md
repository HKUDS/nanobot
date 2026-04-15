
# drive +export-download

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

根据导出任务产物的 `file_token` 下载本地文件。通常与 `drive +task_result --scenario export` 配合使用。

## 命令

```bash
# 使用服务端返回的文件名下载到当前目录
lark-cli drive +export-download \
  --file-token "<EXPORTED_FILE_TOKEN>"

# 下载到指定目录
lark-cli drive +export-download \
  --file-token "<EXPORTED_FILE_TOKEN>" \
  --output-dir ./exports

# 指定本地文件名
lark-cli drive +export-download \
  --file-token "<EXPORTED_FILE_TOKEN>" \
  --file-name "weekly-report.pdf" \
  --output-dir ./exports

# 允许覆盖
lark-cli drive +export-download \
  --file-token "<EXPORTED_FILE_TOKEN>" \
  --overwrite
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--file-token` | 是 | 导出完成后的产物 token |
| `--file-name` | 否 | 覆盖默认文件名 |
| `--output-dir` | 否 | 本地输出目录，默认当前目录 |
| `--overwrite` | 否 | 覆盖已存在文件 |

## 使用顺序

1. 用 `drive +export` 发起导出
2. 如果返回 `ticket` / `next_command`，用 `drive +task_result --scenario export --ticket <ticket> --file-token <source_token>` 继续查
3. 查到 `file_token` 后，用 `drive +export-download` 下载

## 参考

- [lark-drive](../SKILL.md) -- 云空间全部命令
- [lark-shared](../../lark-shared/SKILL.md) -- 认证和全局参数
