
# mail +watch

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

实时监听新邮件事件（`mail.user_mailbox.event.message_received_v1`）。

**权限要求：** 应用需要 `mail:event`、`mail:user_mailbox.message:readonly` 权限，以及字段权限 `mail:user_mailbox.message.address:read`、`mail:user_mailbox.message.subject:read`、`mail:user_mailbox.message.body:read`，且机器人需订阅事件 `mail.user_mailbox.event.message_received_v1`。按需权限（缺失时会提示申请）：使用 `--folders` / `--folder-ids` 筛选自定义文件夹时需要 `mail:user_mailbox.folder:read`；使用 `--labels` / `--label-ids` 筛选自定义标签时需要 `mail:user_mailbox.message:modify`。

## 命令

```bash
# 默认：表格输出 message 元数据
lark-cli mail +watch

# 仅输出 message 数据（jq 友好）
lark-cli mail +watch --msg-format metadata --format data

# 输出精简元数据（message_id / thread_id / folder_id / label_ids / internal_date / message_state）
lark-cli mail +watch --msg-format minimal --format data

# 输出纯文本全文
lark-cli mail +watch --msg-format plain_text_full --format data

# 输出完整 message（含正文相关字段）
lark-cli mail +watch --msg-format full --format data

# 输出原始事件体
lark-cli mail +watch --msg-format event --format data

# 监听指定邮箱
lark-cli mail +watch --mailbox alice@company.com

# 按文件夹/标签过滤（客户端过滤，支持名称或 ID）
lark-cli mail +watch --folders '["收件箱项目"]' --label-ids '["FLAGGED"]'

# 写入文件
lark-cli mail +watch --msg-format metadata --output-dir ./mail-events

# 查看各 --msg-format 的输出字段说明（解析前先运行）
lark-cli mail +watch --print-output-schema
```

## 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--mailbox <id>` | `me` | 订阅目标邮箱 |
| `--msg-format <mode>` | `metadata` | 输出模式：`metadata` / `minimal` / `plain_text_full` / `full` / `event` |
| `--format <mode>` | `table` | 输出样式：`table` / `json` / `data` |
| `--folder-ids <json-array>` | — | 文件夹 ID 过滤，如 `["INBOX","SENT"]` |
| `--folders <json-array>` | — | 文件夹名称过滤（与 `--folder-ids` 取并集） |
| `--label-ids <json-array>` | — | 标签 ID 过滤，如 `["FLAGGED","IMPORTANT"]` |
| `--labels <json-array>` | — | 标签名称过滤（与 `--label-ids` 取并集） |

> **过滤逻辑：** `--folder-ids`/`--folders` 与 `--label-ids`/`--labels` 之间是 **AND** 关系，即邮件必须**同时**匹配指定的文件夹和标签才会输出。同类参数内部是 **OR** 关系（匹配其中任一即可）。新收到的邮件通常只有系统标签（如 `UNREAD`、`IMPORTANT`），不会自动带有自定义标签。
| `--output-dir <dir>` | — | 每条事件写入单独 JSON 文件 |
| `--print-output-schema` | — | 打印各 `--msg-format` 的输出字段说明（解析输出前先运行此命令） |
| `--dry-run` | — | 仅预览订阅请求，不实际连接 |

## --msg-format 输出结构（--format json）

每条事件输出为一行 NDJSON。

**`metadata`**（默认，适合分拣/通知）
```json
{"ok":true,"data":{"message":{"message_id":"...","thread_id":"...","subject":"...","head_from":{"name":"Alice","mail_address":"alice@example.com"},"to":[{"name":"Bob","mail_address":"bob@example.com"}],"folder_id":"INBOX","label_ids":["IMPORTANT"],"internal_date":"1742800000000","message_state":1,"body_preview":"Please find attached..."}}}
```

**`minimal`**（仅 ID 和状态，适合追踪已读/文件夹变更）
```json
{"ok":true,"data":{"message":{"message_id":"...","thread_id":"...","folder_id":"INBOX","label_ids":["IMPORTANT"],"internal_date":"1742800000000","message_state":1}}}
```

**`plain_text_full`**（metadata 全部字段 + 完整纯文本正文）
```json
{"ok":true,"data":{"message":{"message_id":"...","subject":"...","head_from":{...},"folder_id":"INBOX","label_ids":[...],"body_preview":"...","body_plain_text":"<base64url>"}}}
```

**`event`**（原始 WebSocket 事件，不发起 API 请求，适合调试）
```json
{"ok":true,"data":{"header":{"event_id":"abc123","event_type":"mail.user_mailbox.event.message_received_v1","create_time":"1742800000000"},"event":{"message_id":"...","mail_address":"user@example.com"}}}
```

**`full`**（全部字段，含 HTML 正文和附件）
```json
{"ok":true,"data":{"message":{"message_id":"...","subject":"...","head_from":{...},"body_preview":"...","body_plain_text":"<base64url>","body_html":"<base64url>","attachments":[{"name":"report.pdf","size":102400}]}}}
```

## 参考

- [lark-mail](../SKILL.md) — 邮箱域总览
- [lark-mail-triage](lark-mail-triage.md) — 邮件摘要列表
- [lark-event-subscribe](../../lark-event/references/lark-event-subscribe.md) — 通用事件订阅
