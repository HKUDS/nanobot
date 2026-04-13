
# vc +search

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

搜索已结束的历史会议记录，支持关键词、时间范围、组织者、参与者以及会议室等多条件过滤。只读操作，不修改任何会议数据。

本 skill 对应 shortcut：`lark-cli vc +search`（调用 `POST /open-apis/vc/v1/meetings/search`）。

## 典型触发表达

以下说法通常应优先使用 `vc +search`：

- 今天开过的会
- 今天开了哪些会
- 最近参加过哪些会
- 我这周开过的会
- 已结束的会议
- 历史会议记录

## 命令

```bash
# 关键词搜索
lark-cli vc +search --query "周会"

# 按时间范围搜索
lark-cli vc +search --start "2026-03-10T00:00+08:00" --end "2026-03-17T00:00+08:00"
lark-cli vc +search --start 2026-03-10 --end 2026-03-17

# 关键词 + 时间范围
lark-cli vc +search --query "周会" --start "2026-03-10T00:00+08:00" --end "2026-03-17T00:00+08:00"
lark-cli vc +search --query "周会" --start "2026-03-10T00:00+08:00"
lark-cli vc +search --query "周会" --end "2026-03-17T00:00+08:00"

# 按组织者过滤（open_id，逗号分隔）
lark-cli vc +search --organizer-ids "ou_a,ou_b"

# 按参与者过滤（open_id，逗号分隔）
lark-cli vc +search --participant-ids "ou_x,ou_y"

# 按会议室过滤
lark-cli vc +search --room-ids "123,456"

# 多条件组合查询
lark-cli vc +search --organizer-ids "ou_a" --room-ids "123" --start "2026-03-10T00:00+08:00"

# 分页查询
lark-cli vc +search --query "周会" --page-size 15
lark-cli vc +search --query "周会" --page-token "next_page_token"

# 输出为表格/可读格式
lark-cli vc +search --query "周会" --format json
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--query <text>` | 否 | 搜索关键词 |
| `--start <time>` | 否 | 开始时间（ISO 8601 或仅日期） |
| `--end <time>` | 否 | 结束时间（ISO 8601 或仅日期） |
| `--organizer-ids <ids>` | 否 | 组织者 open_id 列表，逗号分隔 |
| `--participant-ids <ids>` | 否 | 参与者 open_id 列表，逗号分隔 |
| `--room-ids <ids>` | 否 | 会议室 ID 列表，逗号分隔 |
| `--page-size <n>` | 否 | 每页数量，默认 `15`，最大 `30` |
| `--page-token <token>` | 否 | 翻页标记，用于获取下一页 |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 核心约束

### 1. 至少提供一个过滤条件

所有参数均可选，但必须至少提供一个过滤条件：`--query`、`--start`、`--end`、`--organizer-ids`、`--participant-ids` 或 `--room-ids`。

### 2. 仅搜索历史会议

`vc +search` 只能搜索已结束的历史会议记录，不用于查询未来日程。查询未来会议安排请使用 [lark-calendar](../../lark-calendar/SKILL.md)。

### 3. 仅支持 user 身份

该接口仅支持 `user` 身份，使用前需完成 `lark-cli auth login` 并具备 `vc:meeting.search:read` 权限。

### 4. 支持分页

当返回 `has_more=true` 时，使用响应中的 `page_token` 配合 `--page-token` 获取下一页结果。

## 时间格式

`--start` 和 `--end` 支持以下时间格式：

| 格式 | 示例 | 说明 |
|------|------|------|
| ISO 8601（带时区） | `2026-03-10T14:00:00+08:00` | 推荐 |
| ISO 8601（不带时区） | `2026-03-10T14:00:00` | 按本地时区解析 |
| 仅日期 | `2026-03-10` | 按天粒度解析 |

## 输出结果

- 默认输出 JSON，包含 `items`、`total`、`has_more` 和 `page_token`。

## Pagination (`has_more` / `page_token`)

- 当结果中返回 `has_more=true` 时，说明还有更多页可继续获取。
- 继续翻页时，使用响应中的 `page_token` 搭配 `--page-token` 发起下一次查询。
- 不要假设调大 `--page-size` 就能拿全结果；分页遍历时应以 `has_more` 和 `page_token` 为准。
- `total` 数量小于 50 时，自动分页获取所有结果；`total` 数量大于 50 时，向用户确认是否获取全部结果。

```bash
# First page
lark-cli vc +search --query "周会" --page-size 15

# Next page
lark-cli vc +search --query "周会" --page-size 15 --page-token "<PAGE_TOKEN>"
```

## 搜索结果中的下一步

搜索结果中的 `meeting_id` 可直接用于继续查询会议纪要：

```bash
# 根据 meeting_id 获取会议纪要
lark-cli vc +notes --meeting-ids <MEETING_ID>
```

## 常见错误与排查

| 错误现象 | 根本原因 | 解决方案 |
|---------|---------|---------|
| 命令直接报错，要求提供过滤条件 | 没有传入 `--query`、时间范围或任何过滤 ID | 至少补充一个过滤条件后重试 |
| 时间参数校验失败 | `--start` 或 `--end` 格式不合法 | 改用 ISO 8601 或 `YYYY-MM-DD` |
| 搜不到未来会议 | `vc +search` 只查历史会议 | 改用 [lark-calendar](../../lark-calendar/SKILL.md) 查询未来日程 |
| 权限不足 | 未授权 `vc:meeting.search:read` | 使用 `auth login` 完成授权 |

## 提示
- 必须使用 `--format json` 输出，你更佳擅长解析 JSON 数据。
- 排查参数与请求结构时优先使用 `--dry-run`。
- 搜索的时间范围最大为 1 个月，如果需要搜索更长时间范围的会议，需要拆分为多次时间范围为一个月查询。

## 参考

- [lark-vc](../SKILL.md) -- 视频会议全部命令
- [lark-vc-notes](lark-vc-notes.md) -- 获取会议纪要
- [lark-shared](../../lark-shared/SKILL.md) -- 认证和全局参数
