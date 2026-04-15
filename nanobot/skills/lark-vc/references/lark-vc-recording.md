
# vc +recording

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

通过 meeting_id 或 calendar_event_id 查询对应的 minute_token。这是 VC 域和 Minutes 域之间的桥梁命令。只读操作。

本 skill 对应 shortcut：`lark-cli vc +recording`。

## 命令

```bash
# 通过会议 ID 查询（逗号分隔支持批量，最多 50 个）
lark-cli vc +recording --meeting-ids 69xxxxxxxxxxxxx28
lark-cli vc +recording --meeting-ids 69xxxxxxxxxxxxx28,69xxxxxxxxxxxxx29

# 通过日程事件 ID 查询
lark-cli vc +recording --calendar-event-ids xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx_0

# 输出格式
lark-cli vc +recording --meeting-ids 69xxxxxxxxxxxxx28 --format json

# 预览 API 调用
lark-cli vc +recording --meeting-ids 69xxxxxxxxxxxxx28 --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--meeting-ids <ids>` | 二选一 | 会议 ID，逗号分隔支持批量 |
| `--calendar-event-ids <ids>` | 二选一 | 日程事件 ID，逗号分隔支持批量 |
| `--format <fmt>` | 否 | 输出格式：json (默认) / pretty / table / ndjson / csv |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 核心约束

### 1. 两种参数互斥

每次只能指定一种输入方式。同时传入会报错。

### 2. 仅支持 user 身份

该命令仅支持 `user` 身份。如当前用户授权缺失或过期，由 agent 在后台发起 `lark-cli auth login` 并把授权链接发给用户点击；不要让最终用户执行该命令。user token 只能查自己有权限的录制。

### 3. 批量上限

每次最多传入 50 个 ID。

### 4. 录制必须已完成

录制必须完成生成后才能查询。时长 < 5 秒的录制可能不会生成文件。

## 输出结果

返回 `recordings` 数组，每条记录包含：

| 字段 | 说明 |
|------|------|
| `meeting_id` | 会议 ID |
| `calendar_event_id` | 日历事件 ID（仅 `--calendar-event-ids` 路径） |
| `minute_token` | 从录制 URL 中解析的妙记 Token |
| `recording_url` | 录制 URL |
| `duration` | 录制时长（毫秒） |
| `error` | 错误信息（仅查询失败时存在） |

## 如何获取输入参数

| 输入参数 | 获取方式 |
|---------|---------|
| `meeting_id` | `vc +search` 搜索历史会议 → 结果中的 `id` 字段 |
| `calendar_event_id` | `calendar +agenda` 查看日程 → 结果中的 `event_id` 字段 |

## Agent 组合场景

### 场景 1：知道 meeting_id，想下载录制

```bash
vc +recording --meeting-ids xxx → minute_token
minutes +download --minute-token <minute_token>
```

### 场景 2：知道 meeting_id，想获取完整纪要（含 AI 产物）

```bash
vc +recording --meeting-ids xxx → minute_token
vc +notes --minute-tokens <minute_token>
```

### 场景 3：搜索会议 → 获取录制 → 下载

```bash
vc +search --query "周会" --start yesterday → meeting_ids
vc +recording --meeting-ids <ids> → minute_tokens
minutes +download --minute-token <token>
```

### 场景 4：从日历事件获取录制

```bash
vc +recording --calendar-event-ids <event_id> → minute_token
minutes +download --minute-token <minute_token>
```

## 常见错误与排查

| 错误现象 | 根本原因 | 解决方案 |
|---------|---------|---------|
| `exactly one of ... is required` | 未传入参数或同时传了多种 | 只指定一种输入方式 |
| `no recording available` | 该会议无录制或录制未完成 | 确认会议已结束且开启了录制 |
| `121005 no permission` | 无权查看该会议录制 | 确认是会议参与者或有录制权限 |
| `124002 recording generating` | 录制文件仍在生成中 | 等待录制完成后重试 |
| `missing required scope(s)` | 权限不足 | 由 agent 在后台发起 `auth login --scope` 并返回授权链接；不要让最终用户执行该命令 |

## 提示

- 默认使用 `--format json` 输出，Agent 更擅长解析 JSON 数据。
- 排查参数与请求结构时优先使用 `--dry-run`。
- `minute_token` 从录制 URL 尾段解析（`https://meetings.feishu.cn/minutes/{minute_token}`）。
- 拿到 `minute_token` 后可直接传给 `minutes +download` 或 `vc +notes --minute-tokens`。

## 参考

- [lark-vc](../SKILL.md) — 视频会议全部命令
- [lark-vc-search](lark-vc-search.md) — 搜索历史会议（获取 meeting_id）
- [lark-vc-notes](lark-vc-notes.md) — 获取会议纪要
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
