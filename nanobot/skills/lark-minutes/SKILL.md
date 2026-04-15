---
name: lark-minutes
version: 1.0.0
description: "飞书妙记：获取妙记基础信息（标题、封面、时长）和相关的 AI 产物（总结、待办、章节），下载妙记音视频文件。飞书妙记的 URL 格式为: http(s)://<host>/minutes/<minute-token>"
metadata:
  requires:
    bins: ["lark-cli"]
  cliHelp: "lark-cli minutes --help"
---

# minutes (v1)

**CRITICAL — 开始前 MUST 先用 Read 工具读取 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)，其中包含认证、权限处理**

## 核心概念

- **妙记 Token（minute_token）**：妙记的唯一标识符。通常可从妙记的 URL 链接中提取（例如 `https://*.feishu.cn/minutes/obcnq3b9jl72l83w4f14xxxx` 中的最后一段字符串 `obcnq3b9jl72l83w4f14xxxx`）。

## 使用说明

1. **提取 Token**：
   - 只有 `minute_token` 参数是必填的。
   - 如果 URL 中包含额外参数（如 `?xxx`），请截取路径部分的最后一段作为 token。
   - 示例：从 `https://domain.feishu.cn/minutes/obc123456?project=xxx` 中提取出 `obc123456`。

2. **获取妙记信息**：
   - 使用 `lark-cli schema minutes.minutes.get` 可以查看具体的返回值结构。
   - 返回的核心字段通常包含：
     - `title`：会议标题
     - `cover`：视频/音频封面 URL
     - `duration`：会议时长（毫秒）
     - `owner_id`：所有者 ID
     - `url`：妙记链接

## 典型场景

### 妙记内容查询

```bash
# 首先查询妙记元信息（标题、时长、封面） → 用本 skill
lark-cli minutes minutes get --params '{"minute_token": "obcn***************"}'

# 查妙记关联的纪要产物：逐字稿、总结、待办、章节等 → 用 lark-cli vc +notes
lark-cli vc +notes --minute-tokens obcnhijv43vq6bcsl5xasfb2
```
本 skill 仅提供妙记**基础元信息**查询（标题、封面、时长）。如需获取纪要**内容**（逐字稿、AI 总结、待办、章节），请使用 [lark-cli vc +notes](../lark-vc/references/lark-vc-notes.md)：

- 用户未指定需要查询妙记的哪些内容时，默认查询基础元信息和相关联的纪要产物信息。
- 用户未明确指定查看纪要产物（逐字稿、总结、待办、章节）时，向用户展示对应产物的链接即可，不需要直接读取产物内容。

## Shortcuts（推荐优先使用）

Shortcut 是对常用操作的高级封装（`lark-cli minutes +<verb> [flags]`）。有 Shortcut 的操作优先使用。

| Shortcut | 说明 |
|----------|------|
| [`+download`](references/lark-minutes-download.md) | Download audio/video media file of a minute |

### 妙记音视频下载

下载妙记音视频文件到本地，或获取有效期 1 天的下载链接。详见 [minutes +download](references/lark-minutes-download.md)。

```bash
# 下载音视频文件到本地
lark-cli minutes +download --minute-tokens obcnq3b9jl72l83w4f149w9c --output ./meeting.mp4

# 仅获取下载链接
lark-cli minutes +download --minute-tokens obcnq3b9jl72l83w4f149w9c --url-only

# 批量下载
lark-cli minutes +download --minute-tokens obcnq3b9jl72l83w4f149w9c,obcnexa7814k4t41c446fzwj
```

<!-- AUTO-GENERATED-START — gen-skills.py 管理，勿手动编辑 -->
## API Resources

```bash
lark-cli schema minutes.<resource>.<method>   # 调用 API 前必须先查看参数结构
lark-cli minutes <resource> <method> [flags] # 调用 API
```

> **重要**：使用原生 API 时，必须先运行 `schema` 查看 `--data` / `--params` 参数结构，不要猜测字段格式。

### minutes

  - `get` — 获取妙记信息

## 权限表

| 方法 | 所需 scope |
|------|-----------|
| `minutes.get` | `minutes:minutes:readonly` |
| `+download` | `minutes:minutes.media:export` |


<!-- AUTO-GENERATED-END -->
