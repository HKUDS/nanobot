
# mail +triage

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

查看收件箱邮件摘要（date / from / subject / message_id），用于快速浏览和决定读哪封邮件。

## 用法

```bash
# 默认：收件箱邮件（默认 20 条，默认table 格式）
lark-cli mail +triage

# 查看收件箱未读
lark-cli mail +triage --filter '{"folder":"inbox","is_unread":true}'

# 全文搜索
lark-cli mail +triage --query "合同审批"

# 按发件人 / 主题搜索
lark-cli mail +triage --filter '{"from":["boss@example.com"],"subject":"季度报告"}'

# 按时间范围搜索（如"上周的邮件"）
lark-cli mail +triage --query "项目评审" --filter '{"time_range":{"start_time":"2026-03-16T00:00:00+08:00","end_time":"2026-03-22T23:59:59+08:00"}}'

# 指定文件夹
lark-cli mail +triage --filter '{"folder":"sent"}'

# 系统标签（可通过 folder 或 label 传入，搜索时自动转为 folder）
lark-cli mail +triage --filter '{"folder":"flagged"}'
lark-cli mail +triage --filter '{"label":"important"}'
lark-cli mail +triage --filter '{"label":"重要邮件"}'

# json/data 格式可配合 jq 处理
lark-cli mail +triage --format json | jq '.messages[].subject'

# 分页：先取 10 条，再用 page_token 翻页
lark-cli mail +triage --max 10 --format json
# 输出中包含 page_token，传入下一次请求
lark-cli mail +triage --page-token 'list:FfccvoqPd...' --max 10 --format json

# --page-size 是 --max 的别名
lark-cli mail +triage --page-size 10
```

## 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--filter <json>` | — | 筛选条件（见下方字段说明） |
| `--query <text>` | — | 全文搜索关键词 |
| `--format <mode>` | `table` | `table` / `json` / `data`（`json` 和 `data` 均输出含分页信息的对象） |
| `--max <n>` | `20` | 最大返回条数（1-400），内部自动分页拉取 |
| `--page-size <n>` | — | `--max` 的别名，两者含义相同；同时指定时 `--page-size` 优先 |
| `--page-token <token>` | — | 上一次响应返回的分页令牌，传入后从该位置继续拉取。令牌带 `search:` 或 `list:` 前缀，标识来源路径，不可混用 |
| `--labels` | — | table 格式时额外显示 labels 列 |
| `--mailbox <id>` | `me` | 邮箱地址 |

### `--filter` 支持的字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `folder` | string | 文件夹名称筛选。系统文件夹固定值：`inbox`/`sent`/`draft`/`trash`/`spam`/`archive`/`priority`/`flagged`/`other`/`scheduled`，也支持自定义文件夹名称。子文件夹需用 `parent_name/child_name` 格式，可通过 folder list 接口查看 |
| `folder_id` | string | 文件夹 ID，优先级高于 `folder`。系统值：`INBOX`/`SENT`/`DRAFT`/`TRASH`/`SPAM`/`ARCHIVED`，自定义文件夹为数字 ID |
| `label` | string | 自定义标签名称筛选。子标签需用 `parent_name/child_name` 格式，可通过 label list 接口查看 |
| `label_id` | string | 标签 ID，优先级高于 `label`。自定义标签为数字 ID |
| `is_unread` | boolean | 是否未读 |
| `from` | string[] | 发件人 |
| `to` | string[] | 收件人 |
| `subject` | string | 主题关键词 |
| `has_attachment` | boolean | 是否有附件 |
| `time_range` | object | 时间范围 `{"start_time":"2026-01-01T00:00:00+08:00","end_time":"..."}` |

> **系统标签说明**：`IMPORTANT`/`FLAGGED`/`OTHER` 可通过 `folder` 或 `label` 传入（也支持中文别名 `重要邮件`/`已加旗标`/`其他邮件`、搜索名 `priority`/`flagged`/`other`）。搜索时自动转为 folder 字段，列表时自动转为 label_id。label list 接口不返回这三个系统标签。
>
> **⚠️ 注意**：查询未读请用 `"is_unread":true`。
可运行 `mail +triage --print-filter-schema` 查看完整字段说明。

## 输出

### `--format json` / `--format data`

两者输出格式相同，均为含分页信息的对象：

```json
{
  "messages": [
    {
      "message_id": "SEU2...",
      "date": "Fri, 21 Mar 2026 11:40:00 +0800",
      "from": "Alice <alice@example.com>",
      "subject": "Weekly update",
      "labels": "INBOX,UNREAD"
    }
  ],
  "count": 20,
  "has_more": true,
  "page_token": "list:FfccvoqPd_loLhtcRx8cx..."
}
```

- `has_more`：是否还有下一页
- `page_token`：传入 `--page-token` 可获取下一页；为空字符串表示已到末尾
- token 前缀 `search:` / `list:` 标识来源 API 路径，不可混用

### `table` 格式

`page_token` 信息输出在 stderr，自动携带 `--query`/`--filter` 参数方便续页：
```text
15 message(s)
next page: mail +triage --query '合同审批' --page-token 'search:abc123...'
tip: use mail +message --message-id <id> to read full content
```

### 搜索分页注意事项

搜索路径（使用 `--query` 或 `from`/`to`/`subject` 等 filter）的分页结果在**同一翻页链内**保持一致（无重复、无丢失）。但不同 `--max` 值发起的独立搜索可能返回不同排序，这是搜索 API 的固有行为。列表路径（仅 `folder`/`label` 筛选）无此限制。

## 参考

- [lark-mail](../SKILL.md) — 邮箱域总览
- [lark-mail-watch](lark-mail-watch.md) — 实时监听新邮件
