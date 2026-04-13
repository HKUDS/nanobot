# mail +reply-all

> **前置条件：** 先阅读 [`../../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

回复全部会自动处理：
- 自动聚合原邮件发件人、原 To、原 Cc
- 自动排除当前用户地址，避免回给自己
- 自动维护会话头（`In-Reply-To` / `References`）

> **默认草稿**：`+reply-all` 默认保存为草稿，不会立即发送。如需立即发送，添加 `--confirm-send` 参数（仅在用户明确确认后使用）。

本 skill 对应 shortcut：`lark-cli mail +reply-all`。

## CRITICAL — 发送工作流（必须遵循）

此命令默认**只保存草稿**，不会发送邮件。回复全部会发送给**所有**原始收件人，需要发送时**必须**按以下步骤操作：

**Step 1** — 创建回复全部草稿（不带 `--confirm-send`）：
```bash
lark-cli mail +reply-all --message-id <邮件ID> --body '<回复正文>'
```
→ 返回 `draft_id`

**Step 2** — 向用户展示回复摘要（目标邮件、回复内容、完整收件人列表 To/Cc），请求确认发送

**Step 3** — 用户明确同意后，发送该草稿：
```bash
lark-cli mail user_mailbox.drafts send --params '{"user_mailbox_id":"me","draft_id":"<Step 1 返回的 draft_id>"}'
```

**禁止跳过 Step 1 直接使用 `--confirm-send`。禁止在用户未明确同意的情况下执行 Step 3。**

## 命令

```bash
# 回复全部（默认保存为草稿）— HTML 推荐
lark-cli mail +reply-all --message-id <邮件ID> --body '<p><b>已完成</b>，详见下方说明。</p>'

# 回复全部并追加收件人/抄送（草稿）
lark-cli mail +reply-all --message-id <邮件ID> --body '<p>同步更新</p>' --to lead@example.com --cc pm@example.com

# 从回复名单中排除某些地址（草稿）
lark-cli mail +reply-all --message-id <邮件ID> --body '<p>见上</p>' --remove bot@example.com,noreply@example.com

# 回复全部时插入内嵌图片（推荐：直接用相对路径，自动解析）
lark-cli mail +reply-all --message-id <邮件ID> --body '<p>详见图示：<img src="./logo.png" /></p>'

# 纯文本回复全部（仅在内容极简时使用）
lark-cli mail +reply-all --message-id <邮件ID> --body '收到，已处理。'

# 确认发送（用户明确确认后才可使用）
lark-cli mail +reply-all --message-id <邮件ID> --body '<p>收到，已处理。</p>' --confirm-send

# Dry Run（仅打印请求，不发送）
lark-cli mail +reply-all --message-id <邮件ID> --body '测试' --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--message-id <id>` | 是 | 被回复的邮件 ID |
| `--body <text>` | 是 | 回复正文。推荐使用 HTML 获得富文本排版；也支持纯文本。根据回复正文和原邮件正文自动检测 HTML。使用 `--plain-text` 可强制纯文本模式。支持 `<img src="./local.png" />` 相对路径自动解析为内嵌图片（仅支持相对路径，不支持绝对路径） |
| `--from <email>` | 否 | 发件人邮箱地址（EML From 头）。使用别名（send_as）发信时，设为别名地址并配合 `--mailbox` 指定所属邮箱。默认读取邮箱主地址 |
| `--mailbox <email>` | 否 | 邮箱地址，指定草稿所属的邮箱（默认回退到 `--from`，再回退到 `me`）。当发件人（`--from`）与邮箱不同时使用。可通过 `accessible_mailboxes` 查询可用邮箱 |
| `--to <emails>` | 否 | 额外收件人，多个用逗号分隔（追加到自动聚合结果） |
| `--cc <emails>` | 否 | 额外抄送，多个用逗号分隔 |
| `--bcc <emails>` | 否 | 密送邮箱，多个用逗号分隔 |
| `--remove <emails>` | 否 | 从自动聚合结果中排除的邮箱，多个用逗号分隔 |
| `--plain-text` | 否 | 强制纯文本模式，忽略所有 HTML 自动检测。不可与 `--inline` 同时使用 |
| `--attach <paths>` | 否 | 附件文件路径，多个用逗号分隔。相对路径 |
| `--inline <json>` | 否 | 高级用法：手动指定内嵌图片 CID 映射。推荐直接在 `--body` 中使用 `<img src="./path" />`（自动解析）。仅在需要精确控制 CID 命名时使用此参数。格式：`'[{"cid":"mycid","file_path":"./logo.png"}]'`，在 body 中用 `<img src="cid:mycid">` 引用。不可与 `--plain-text` 同时使用 |
| `--confirm-send` | 否 | 确认发送回复（默认只保存草稿）。仅在用户明确确认后使用 |
| `--dry-run` | 否 | 仅打印请求，不执行 |

## 返回值

默认（草稿模式）：
```json
{
  "ok": true,
  "data": {
    "draft_id": "草稿ID",
    "tip": "draft saved. To send: lark-cli mail user_mailbox.drafts send --params '{...}'"
  }
}
```

`--confirm-send` 模式：
```json
{
  "ok": true,
  "data": {
    "message_id": "邮件ID",
    "thread_id":  "会话ID"
  }
}
```

## 典型场景

### 场景 1：用户说"帮我回复全部说同意"（只创建草稿）
```bash
lark-cli mail +reply-all --message-id <邮件ID> --body '<p>同意，没有问题。</p>'
```
→ 返回 `draft_id`，告诉用户回复全部草稿已创建。

### 场景 2：用户说"回复全部说已确认"（需要发送）
```bash
# Step 1: 创建回复全部草稿
lark-cli mail +reply-all --message-id <邮件ID> --body '<p>已确认。</p>'
# → 返回 draft_id

# Step 2: 向用户确认 "回复全部草稿已创建：收件人 alice@, bob@, carol@，内容「已确认。」确认发送吗？"

# Step 3: 用户确认后发送
lark-cli mail user_mailbox.drafts send --params '{"user_mailbox_id":"me","draft_id":"<draft_id>"}'
```

## 实现说明

- 自动收件人规则：原发件人优先进入 To，原 To/Cc 进入 Cc。
- 地址会去重（大小写不敏感）。
- 自动排除当前用户地址（enterprise email），并叠加 `--remove` 规则。
- 通过 raw EML 维护会话头并尽量复用原 `thread_id`。

## 发送后跟进

回复发送成功后：

**1. 确认投递状态**（必须）— 用返回的 `message_id` 查询投递状态：

```bash
lark-cli mail user_mailbox.messages send_status --params '{"user_mailbox_id":"me","message_id":"<发送返回的 message_id>"}'
```

状态码：1=正在投递, 2=投递失败重试, 3=退信, 4=投递成功, 5=待审批, 6=审批拒绝。向用户简要报告投递结果，异常状态需重点提示。

**2. 标记已读**（可选）— 询问用户是否需要将原邮件标记为已读。如果用户同意：

```bash
lark-cli mail user_mailbox.messages batch_modify_message --params '{"user_mailbox_id":"me"}' --data '{"message_ids":["<原邮件ID>"],"remove_label_ids":["UNREAD"]}'
```

## 相关命令

- `lark-cli mail +reply` — 仅回复发件人
- `lark-cli mail +forward` — 转发邮件
- `lark-cli mail user_mailbox.messages get` — 查看邮件详情
