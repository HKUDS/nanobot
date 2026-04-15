
# minutes +download

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

下载妙记的音视频媒体文件到本地，或获取有效期 1 天的下载链接。只读操作。

本 skill 对应 shortcut：`lark-cli minutes +download`。

## 命令

```bash
# 下载单个妙记的音视频文件
lark-cli minutes +download --minute-tokens obcnq3b9jl72l83w4f149w9c

# 指定输出路径
lark-cli minutes +download --minute-tokens obcnq3b9jl72l83w4f149w9c --output ./meeting.mp4

# 仅获取下载链接（有效期 1 天），不下载文件
lark-cli minutes +download --minute-tokens obcnq3b9jl72l83w4f149w9c --url-only

# 批量下载多个妙记
lark-cli minutes +download --minute-tokens obcnq3b9jl72l83w4f149w9c,obcnexa7814k4t41c446fzwj

# 批量下载到指定目录
lark-cli minutes +download --minute-tokens obcnq3b9jl72l83w4f149w9c,obcnexa7814k4t41c446fzwj --output ./downloads

# 预览 API 调用
lark-cli minutes +download --minute-tokens obcnq3b9jl72l83w4f149w9c --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--minute-tokens <tokens>` | 是 | 妙记 Token，逗号分隔支持批量（最多 50 个） |
| `--output <path>` | 否 | 输出路径：单个 token 时为文件路径，批量时为目录（默认当前目录） |
| `--overwrite` | 否 | 覆盖已存在的输出文件 |
| `--url-only` | 否 | 仅返回下载链接，不下载文件 |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 核心约束

### 1. 妙记必须已完成转写

音视频文件仅在妙记转写完成后可下载。如果妙记尚未准备好，API 会返回 `2091003` 错误。

### 2. 下载链接有效期 1 天

`--url-only` 返回的链接有效期为 1 天，过期后需重新获取。

### 3. 频率限制

API 限流 5 次/秒，批量下载时需注意控制频率。

### 4. 所需权限

| 身份 | 所需权限 |
|------|---------|
| user / bot | `minutes:minutes.media:export` |

## 输出结果

### 下载模式（默认）

```json
{
  "saved_path": "访谈一则 & 澳成.mp4",
  "size_bytes": 52428800
}
```

| 字段 | 说明 |
|------|------|
| `saved_path` | 文件保存的本地路径 |
| `size_bytes` | 文件大小（字节） |

### URL 模式（--url-only）

```json
{
  "download_url": "https://..."
}
```

| 字段 | 说明 |
|------|------|
| `download_url` | 媒体文件下载链接（有效期 1 天） |

## 如何获取 minute_token

| 来源 | 获取方式 |
|------|---------|
| 妙记 URL | 从 URL 末尾提取，如 `https://sample.feishu.cn/minutes/obcnq3b9jl72l83w4f149w9c` → `obcnq3b9jl72l83w4f149w9c` |
| 妙记元信息查询 | `lark-cli minutes minutes get --params '{"minute_token": "obcn..."}'` |
| 会议纪要查询 | `lark-cli vc +notes --meeting-ids <id>` 返回结果中关联的妙记 token |

## 常见错误与排查

| 错误现象 | 错误码 | 根本原因 | 解决方案 |
|---------|--------|---------|---------|
| 参数无效 | 2091001 | minute_token 格式不正确 | 检查 token 是否完整（24 位） |
| 资源不存在 | 2091002 | token 不存在 | 确认 minute_token 正确 |
| 妙记尚未准备好 | 2091003 | 转写未完成 | 等待转写完成后重试 |
| 资源已删除 | 2091004 | 妙记已被删除 | 确认妙记文件仍然存在 |
| 权限不足 | 2091005 | 无阅读权限 | 检查是否有该妙记的访问权限 |
| `missing required scope(s)` | — | 应用缺少权限 | 由 agent 在后台发起 `auth login --scope "minutes:minutes.media:export"` 并返回授权链接；不要让最终用户执行该命令 |

## 提示

- 音视频文件可能较大，下载无固定超时限制（由用户 Ctrl+C 控制取消）。
- 未指定 `--output` 时，默认使用妙记原始标题作为文件名（如 `Office Oncall流程2.0宣讲.mp4`）。
- 如需获取妙记的纪要内容（逐字稿、AI 总结等），请使用 [vc +notes](../../lark-vc/references/lark-vc-notes.md)。

## 参考

- [lark-minutes](../SKILL.md) — 妙记全部命令
- [lark-vc-notes](../../lark-vc/references/lark-vc-notes.md) — 会议纪要查询
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
