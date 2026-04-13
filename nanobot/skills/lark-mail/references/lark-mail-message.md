# mail +message

> **前置条件：** 先阅读 [`../../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

读取指定邮件的完整内容，包括邮件头、正文（纯文本 + 可选 HTML）以及统一的 `attachments` 列表（涵盖普通附件和内嵌图片）。

CLI 分两阶段构建最终 JSON：
- 安全的邮件元数据字段直接透传
- 正文、附件和辅助字段由 shortcut 派生

本 skill 对应 shortcut `lark-cli mail +message`，内部步骤：
1. `GET /open-apis/mail/v1/user_mailboxes/{mailbox}/messages/{message_id}` — 获取完整邮件内容

## 命令

```bash
# 读取一封邮件（默认包含 HTML 正文）
lark-cli mail +message --message-id <message-id>

# 仅纯文本正文（更小的负载，适合 AI 处理）
lark-cli mail +message --message-id <message-id> --html=false

# 指定邮箱
lark-cli mail +message --mailbox user@example.com --message-id <message-id>

# JSON 输出（脚本友好）
lark-cli mail +message --message-id <message-id> --format json

# Dry Run
lark-cli mail +message --message-id <message-id> --dry-run
```

## 参数

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--message-id <id>` | 是 | — | 邮件 ID |
| `--mailbox <email>` | 否 | 当前用户 | 邮箱地址（`user_mailbox_id`） |
| `--html` | 否 | true | 是否返回 HTML 正文（`false` 仅返回纯文本，减少带宽） |
| `--format <mode>` | 否 | json | 输出格式：`json`（默认）/ `pretty` / `table` / `ndjson` / `csv` |
| `--dry-run` | 否 | — | 仅打印请求，不执行 |

## 返回值

成功时返回 `{"ok": true, "data": ...}` 结构，`data` 字段包含：

```json
{
  "message_id":               "邮件 ID",
  "thread_id":                "会话 ID",
  "smtp_message_id":          "RFC 2822 Message-ID",
  "subject":                  "邮件主题",
  "head_from":                {"mail_address": "alice@example.com", "name": "Alice"},
  "to":                       [{"mail_address": "bob@example.com", "name": "Bob"}],
  "cc":                       [{"mail_address": "carol@example.com", "name": "Carol"}],
  "bcc":                      [],
  "date":                     "Thu, 19 Mar 2026 16:33:02 +0800",
  "in_reply_to":              "<original@domain>",
  "reply_to":                 "reply-to@domain",
  "reply_to_smtp_message_id": "reply-to@domain",
  "references":               ["<a@domain>", "<b@domain>"],
  "internal_date":            "1748000000000",
  "date_formatted":           "2026-03-19 16:33",
  "message_state":            1,
  "message_state_text":       "received",
  "folder_id":                "INBOX",
  "label_ids":                ["UNREAD"],
  "priority_type":            "1",
  "priority_type_text":       "high",
  "security_level": {
    "is_risk": true,
    "risk_banner_level": "DANGER",
    "risk_banner_reason": "UNAUTH_EXTERNAL",
    "is_header_from_external": true,
    "via_domain": "example.com",
    "spam_banner_type": "USER_RULE",
    "spam_user_rule_id": "76180000000025388",
    "spam_banner_info": "blocked.example.com"
  },
  "body_plain_text":          "Hi Bob, ...",
  "body_preview":             "Hi Bob, ...",
  "body_html":                "<html>...</html>",
  "attachments": [
    {
      "id":              "att_xxx",
      "filename":        "report.pdf",
      "attachment_type": 1,
      "is_inline":       false
    },
    {
      "id":           "att_yyy",
      "filename":     "logo.png",
      "content_type": "image/png",
      "is_inline":    true,
      "cid":          "logo@cid"
    }
  ]
}
```

### 字段说明

> 注意：使用 `--format json` 获取结构化输出。所有 JSON 输出统一包裹在 `{"ok": true, "data": ...}` 结构中。

| 字段 | 说明 |
|------|------|
| `message_id` | 邮件 ID |
| `thread_id` | 会话 ID |
| `subject` | 邮件主题 |
| `head_from` | 发件人对象：`{mail_address, name}` |
| `to` | 收件人列表：`[{mail_address, name}]` |
| `cc` | 抄送列表：`[{mail_address, name}]` |
| `bcc` | 密送列表：`[{mail_address, name}]` |
| `date` | EML 中的时间（毫秒） |
| `date_formatted` | 可读的发送时间，如 `"2026-03-19 16:33"` |
| `smtp_message_id` | 符合 RFC 2822 的 SMTP Message-ID |
| `in_reply_to` | In-Reply-To 邮件头 |
| `references` | References 邮件头，祖先 SMTP message ID 列表 |
| `internal_date` | 创建/接收/发送时间（毫秒） |
| `message_state` | 邮件状态：`1` = 已接收，`2` = 已发送，`3` = 草稿 |
| `message_state_text` | `"unknown"` / `"received"` / `"sent"` / `"draft"` |
| `folder_id` | 文件夹 ID。值：`INBOX`、`SENT`、`SPAM`、`ARCHIVED`、`STRANGER`，或自定义文件夹 ID |
| `label_ids` | 标签 ID 列表 |
| `priority_type` | 优先级值：`0` = 无优先级，`1` = 高，`3` = 普通，`5` = 低 |
| `priority_type_text` | `"unknown"` / `"high"` / `"normal"` / `"low"` |
| `draft_id` | 草稿 ID，可通过列出草稿 API 获取 |
| `reply_to` | Reply-To 邮件头 |
| `reply_to_smtp_message_id` | Reply-To SMTP Message-ID |
| `body_plain_text` | **LLM 阅读推荐的正文字段**；已 base64url 解码并清理 ANSI 转义 |
| `body_preview` | 纯文本正文前 100 字符，用于快速预览 |
| `body_html` | 原始 HTML 正文；`--html=false` 时省略 |
| `attachments` | 普通附件和内嵌图片的统一列表 |
| `attachments[].id` | 附件 ID（用于下载 URL API） |
| `attachments[].filename` | 附件文件名 |
| `attachments[].content_type` | 附件 MIME 类型 |
| `attachments[].attachment_type` | 附件类型：`1` = 普通附件，`2` = 超大附件 |
| `attachments[].is_inline` | `true` = 内嵌图片，`false` = 普通附件 |
| `attachments[].cid` | 内嵌图片的 Content-ID（对应 HTML 正文中 `<img src="cid:...">` 的引用） |

### security_level

当服务端有该邮件的风险元数据时返回。

| 字段 | 说明 |
|------|------|
| `is_risk` | 布尔值。`true` 表示邮件被标记为有风险 |
| `risk_banner_level` | 风险等级。值：`WARNING`、`DANGER`、`INFO` |
| `risk_banner_reason` | 风险原因。值：`NO_REASON`、`IMPERSONATE_DOMAIN`（相似域名仿冒）、`IMPERSONATE_KP_NAME`（关键人物姓名仿冒）、`UNAUTH_EXTERNAL`（未认证的外部域名）、`MALICIOUS_URL`、`MALICIOUS_ATTACHMENT`、`PHISHING`、`IMPERSONATE_PARTNER`（合作伙伴仿冒）、`EXTERNAL_ENCRYPTION_ATTACHMENT`（外部加密附件） |
| `is_header_from_external` | 布尔值。`true` 表示发件人来自外部域名 |
| `via_domain` | 当邮件代发或伪造时显示的 SPF/DKIM 域名，如 `"larksuite.com"` |
| `spam_banner_type` | 垃圾邮件原因。值：`USER_REPORT`（用户举报）、`USER_BLOCK`（被用户屏蔽）、`ANTI_SPAM`（系统判定为垃圾邮件）、`USER_RULE`（匹配收件箱规则）、`BLOCK_DOMIN`（域名被用户屏蔽）、`BLOCK_ADDRESS`（地址被用户屏蔽） |
| `spam_user_rule_id` | 匹配的收件箱规则 ID |
| `spam_banner_info` | 匹配用户黑名单的地址或域名，如 `"larksuite.com"` |

## 注意事项

- **JSON 输出可直接使用** — 默认输出合法 UTF-8 JSON，可直接读取，无需额外编码转换。
- JSON 输出中 `body_html` 里的 `<` / `>` 可能显示为 `\u003c` / `\u003e`（JSON 安全转义，内容不变，`jq -r` 可还原）。
- `mail +message` 默认不再获取附件/图片下载 URL。这样可以保持邮件详情读取更轻量，调用方可按需单独请求 URL。
- 查看原始 HTML：

```bash
# jq -r 自动处理 JSON 转义，输出原始 HTML
lark-cli mail +message --message-id <id> --format json | jq -r '.data.body_html'
```

## 典型场景

### 读取邮件 → 摘要 → 回复

```bash
# 1. 读取邮件（仅纯文本，更小负载）
lark-cli mail +message --message-id <id> --html=false --format json

# 2. 让 LLM 分析 body_plain_text 并起草回复

# 3. 发送回复
lark-cli mail +reply --message-id <id> --body "..."
```

### 按需获取附件或内嵌图片下载 URL

```bash
# 1. 读取邮件，从 .data.attachments[] 中获取附件 ID
lark-cli mail +message --message-id <id> --format json

# 2. 仅为需要的 ID 获取下载 URL
lark-cli schema mail.user_mailbox.message.attachments.download_url
lark-cli mail user_mailbox.message.attachments download_url \
  --params '{"user_mailbox_id":"me","message_id":"<id>","attachment_ids":["att_xxx","att_yyy"]}'
```

普通附件和内嵌图片使用同一个 `user_mailbox.message.attachments download_url` 原生 API（无 shortcut 封装），传入 `attachments[].id` 即可。

## 相关命令

- `lark-cli mail +thread` — 读取会话中所有邮件
- `lark-cli mail +reply` — 回复邮件
- `lark-cli mail +forward` — 转发邮件
- `lark-cli mail user_mailbox.message.attachments download_url` — 按需获取邮件附件/图片下载 URL
- `lark-cli mail user_mailbox.messages list` — 列出收件箱邮件（获取 `message_id`）
