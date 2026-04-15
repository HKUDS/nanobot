# mail +send

> **前置条件：** 先阅读 [`../../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

发送新邮件，支持：
- 纯文本或 HTML 正文
- 抄送/密送
- 本地文件附件（`--attach`）
- 内嵌图片（`--inline`，CID 可用随机字符串）

本 skill 对应 shortcut：`lark-cli mail +send`。

## CRITICAL — 发送工作流（必须遵循）

此命令默认**只保存草稿**，不会发送邮件。需要发送时，**必须**按以下步骤操作：

**Step 1** — 创建草稿（不带 `--confirm-send`）：
```bash
lark-cli mail +send --to <收件人> --subject '<主题>' --body '<正文>'
```
→ 返回 `draft_id`

**Step 2** — 向用户展示邮件摘要（收件人、主题、正文预览），请求确认发送

**Step 3** — 用户明确同意后，发送该草稿：
```bash
lark-cli mail user_mailbox.drafts send --params '{"user_mailbox_id":"me","draft_id":"<Step 1 返回的 draft_id>"}'
```

**禁止跳过 Step 1 直接使用 `--confirm-send`。禁止在用户未明确同意的情况下执行 Step 3。**

## 命令

```bash
# 保存为草稿（默认行为，不发送）— HTML 格式推荐
lark-cli mail +send --to alice@example.com --subject '周报' \
  --body '<p>本周进展：</p><ul><li>完成 A 模块</li><li>修复 3 个 bug</li></ul>'

# 保存为草稿并抄送
lark-cli mail +send --to alice@example.com --cc bob@example.com --subject '状态更新' --body '<b>已完成</b>'

# 确认发送（仅在用户明确确认后使用）
lark-cli mail +send --to alice@example.com --subject '周报' \
  --body '<p>本周进展如下...</p>' --confirm-send

# 保存带附件的草稿
lark-cli mail +send --to alice@example.com --subject '请查收' --body '<p>见附件</p>' --attach ./report.pdf,./logs.zip

# 保存带内嵌图片的草稿（推荐：直接用相对路径，自动解析）
lark-cli mail +send --to alice@example.com --subject '预览图' --body '<img src="./logo.png" />'

# 纯文本邮件（仅在内容极简时使用）
lark-cli mail +send --to alice@example.com --subject '确认' --body '收到，谢谢'

# Dry Run（仅打印请求，不执行）
lark-cli mail +send --to alice@example.com --subject '测试' --body '<p>test</p>' --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--to <emails>` | 是 | 收件人邮箱，多个用逗号分隔 |
| `--subject <text>` | 是 | 邮件主题 |
| `--body <text>` | 是 | 邮件正文。推荐使用 HTML 获得富文本排版；也支持纯文本（自动检测）。使用 `--plain-text` 可强制纯文本模式。支持 `<img src="./local.png" />` 相对路径自动解析为内嵌图片（仅支持相对路径，不支持绝对路径） |
| `--from <email>` | 否 | 发件人邮箱地址（EML From 头）。使用别名（send_as）发信时，设为别名地址并配合 `--mailbox` 指定所属邮箱。默认读取邮箱主地址 |
| `--mailbox <email>` | 否 | 邮箱地址，指定草稿所属的邮箱（默认回退到 `--from`，再回退到 `me`）。当发件人（`--from`）与邮箱不同时使用。可通过 `accessible_mailboxes` 查询可用邮箱 |
| `--cc <emails>` | 否 | 抄送邮箱，多个用逗号分隔 |
| `--bcc <emails>` | 否 | 密送邮箱，多个用逗号分隔 |
| `--plain-text` | 否 | 强制纯文本模式，忽略 HTML 自动检测。不可与 `--inline` 同时使用 |
| `--attach <paths>` | 否 | 附件文件路径，多个用逗号分隔。相对路径 |
| `--inline <json>` | 否 | 高级用法：手动指定内嵌图片 CID 映射。推荐直接在 `--body` 中使用 `<img src="./path" />`（自动解析）。仅在需要精确控制 CID 命名时使用此参数。格式：`'[{"cid":"mycid","file_path":"./logo.png"}]'`，在 body 中用 `<img src="cid:mycid">` 引用。不可与 `--plain-text` 同时使用 |
| `--confirm-send` | 否 | 确认发送邮件（默认只保存草稿）。仅在用户明确确认收件人和内容后使用 |
| `--dry-run` | 否 | 仅打印请求，不执行 |

## 返回值

**草稿模式（默认）：**

```json
{
  "ok": true,
  "data": {
    "draft_id": "草稿ID",
    "tip": "draft saved. To send: lark-cli mail user_mailbox.drafts send --params '{...}'"
  }
}
```

**发送模式（`--confirm-send`）：**

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

### 场景 1：用户说"帮我写一封邮件给 Alice"（只创建草稿）
```bash
lark-cli mail +send --to alice@example.com --subject '周报' --body '<p>本周进展如下...</p>'
```
→ 返回 `draft_id`，告诉用户草稿已创建，可在飞书邮件 UI 中预览和编辑。

### 场景 2：用户说"发邮件给 Alice 说收到了"（需要发送）
```bash
# Step 1: 创建草稿
lark-cli mail +send --to alice@example.com --subject '收到' --body '<p>已收到，谢谢！</p>'
# → 返回 draft_id

# Step 2: 向用户确认 "邮件草稿已创建：收件人 alice@example.com，主题「收到」。确认发送吗？"

# Step 3: 用户确认后发送
lark-cli mail user_mailbox.drafts send --params '{"user_mailbox_id":"me","draft_id":"<draft_id>"}'
```

## 发送后跟进

邮件发送成功后（收到 `message_id`），**必须**调用 `send_status` 查询投递状态：

```bash
lark-cli mail user_mailbox.messages send_status --params '{"user_mailbox_id":"me","message_id":"<发送返回的 message_id>"}'
```

状态码：1=正在投递, 2=投递失败重试, 3=退信, 4=投递成功, 5=待审批, 6=审批拒绝。向用户简要报告各收件人投递结果，异常状态需重点提示。

## 实现说明

- 使用 EML 构建器生成完整 MIME 邮件并 base64url 编码后发送。
- `--attach` 作为普通附件添加。相对路径。
- `--inline` 接受 JSON 数组，每项需提供 `cid`（唯一标识符，可用随机十六进制字符串）和 `file_path`（相对路径），作为 inline part 嵌入邮件。

## 相关命令

- `lark-cli mail +reply` — 回复邮件
- `lark-cli mail +reply-all` — 回复全部
- `lark-cli mail +forward` — 转发邮件
- `lark-cli mail user_mailbox.messages list` — 列出邮件
