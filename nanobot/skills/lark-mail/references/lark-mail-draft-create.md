# mail +draft-create

> **前置条件：** 先阅读 [`../../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

从零创建一封全新的邮件草稿。适用于已知收件人、主题和正文的场景。

不要用此命令处理回复或转发场景。回复和转发应使用对应的专用 shortcut（它们默认也是创建草稿而不发送）。

如需修改已有草稿，不要使用此命令，请使用 `lark-cli mail +draft-edit`。

## 安全约束

此命令创建草稿——**不会**发送邮件。用户可以在飞书邮件 UI 中预览、编辑或删除草稿后再发送。因此：

- **不要把邮件内容以文本形式输出再请求确认。** 当用户要求"起草"/"草拟"邮件时，直接调用 `+draft-create` 在飞书邮箱中创建草稿。
- **收件人未指定时省略 `--to`** — 草稿将不带收件人创建，用户之后可自行添加。
- **仅在用户请求确实有歧义时才需确认**（例如内容有多种可能的理解方式）。
- **发送**草稿是单独的操作，需要用户明确确认。

## 命令

```bash
# 创建 HTML 草稿（推荐）
lark-cli mail +draft-create --to alice@example.com --subject '周报' \
  --body '<p>本周进展：</p><ul><li>完成 A 模块</li></ul>'

# 不带收件人的 HTML 草稿（用户之后可自行添加）
lark-cli mail +draft-create --subject '周报' --body '<p>草稿内容</p>'

# 带附件和内嵌图片的 HTML 草稿（推荐：直接用相对路径，自动解析）
lark-cli mail +draft-create --to alice@example.com --subject '预览图' --body '<p>见附件和图：<img src="./logo.png" /></p>' --attach ./report.pdf

# 纯文本草稿（仅在内容极简时使用）
lark-cli mail +draft-create --to alice@example.com --subject '简短通知' --body '收到，谢谢'

# Dry Run（仅打印请求，不执行）
lark-cli mail +draft-create --to alice@example.com --subject '测试' --body 'test' --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--to <emails>` | 否 | 完整收件人列表，多个用逗号分隔。支持 `Alice <alice@example.com>` 格式。省略时草稿不带收件人（之后可通过 `+draft-edit` 添加） |
| `--subject <text>` | 是 | 草稿主题 |
| `--body <text>` | 是 | 邮件正文。推荐使用 HTML 获得富文本排版；也支持纯文本（自动检测）。使用 `--plain-text` 可强制纯文本模式。支持 `<img src="./local.png" />` 相对路径自动解析为内嵌图片（仅支持相对路径，不支持绝对路径） |
| `--from <email>` | 否 | 发件人邮箱地址（EML From 头）。使用别名（send_as）发信时，设为别名地址并配合 `--mailbox` 指定所属邮箱。省略时使用邮箱主地址 |
| `--mailbox <email>` | 否 | 邮箱地址，指定草稿所属的邮箱（默认回退到 `--from`，再回退到 `me`）。当发件人（`--from`）与邮箱不同时使用，如通过别名或 send_as 地址发信。可通过 `accessible_mailboxes` 查询可用邮箱 |
| `--cc <emails>` | 否 | 完整抄送列表，多个用逗号分隔 |
| `--bcc <emails>` | 否 | 完整密送列表，多个用逗号分隔 |
| `--plain-text` | 否 | 强制纯文本模式，忽略 HTML 自动检测。不可与 `--inline` 同时使用 |
| `--attach <paths>` | 否 | 普通附件文件路径，多个用逗号分隔。相对路径 |
| `--inline <json>` | 否 | 高级用法：手动指定内嵌图片 CID 映射。推荐直接在 `--body` 中使用 `<img src="./path" />`（自动解析）。仅在需要精确控制 CID 命名时使用此参数。格式：`'[{"cid":"mycid","file_path":"./logo.png"}]'`，在 body 中用 `<img src="cid:mycid">` 引用。不可与 `--plain-text` 同时使用 |
| `--format <mode>` | 否 | 输出格式：`json`（默认）/ `pretty` / `table` / `ndjson` / `csv` |
| `--dry-run` | 否 | 仅打印请求，不执行 |

## 返回值

成功时：

```json
{
  "ok": true,
  "data": {
    "draft_id": "草稿ID"
  }
}
```

## 典型场景

### 撰写新邮件 → 创建草稿 → 预览 → 发送

```bash
# 1. 创建草稿
lark-cli mail +draft-create --to alice@example.com --subject 'Q1 报告' --body '请查收附件中的报告。' --attach ./q1-report.pdf --format json

# 2. 在飞书邮件 UI 中预览草稿，或通过 API 获取：
lark-cli mail user_mailbox.drafts get --params '{"user_mailbox_id":"me","draft_id":"<draft_id>"}'

# 3. 发送草稿
lark-cli mail user_mailbox.drafts send --params '{"user_mailbox_id":"me","draft_id":"<draft_id>"}'
```

### 创建带内嵌图片的 HTML 草稿

> **推荐方式：** 直接在 `--body` HTML 中使用 `<img src="./logo.png" />`（相对路径），系统会自动创建内嵌 MIME 部分并替换为 `cid:` 引用。仅支持相对路径（如 `./logo.png`），不支持绝对路径（如 `/tmp/logo.png`）。

```bash
# 推荐：直接使用相对路径，自动解析为内嵌图片
lark-cli mail +draft-create \
  --to alice@example.com \
  --subject '通讯稿' \
  --body '<h1>你好</h1><img src="./banner.png" />'

# 高级用法：手动指定 CID（CID 为唯一标识符，可用随机十六进制字符串）
lark-cli mail +draft-create \
  --to alice@example.com \
  --subject '通讯稿' \
  --body '<h1>你好</h1><img src="cid:c7d8e9f0a1b2c3d4e5f6">' \
  --inline '[{"cid":"c7d8e9f0a1b2c3d4e5f6","file_path":"./banner.png"}]'
```

## 相关命令

- `lark-cli mail +draft-edit` — 编辑已有草稿
- `lark-cli mail user_mailbox.drafts send` — 发送已有草稿
- `lark-cli mail user_mailbox.drafts get` — 获取草稿内容
- `lark-cli mail +reply` / `+reply-all` / `+forward` — 创建回复/转发草稿（默认），或加 `--confirm-send` 发送
