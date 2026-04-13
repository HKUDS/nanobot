# mail +draft-edit

> **前置条件：** 先阅读 [`../../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

编辑已有的邮件草稿。命令会读取当前原始 EML，应用最小化补丁，然后将更新后的草稿写回。

简单元数据编辑使用直接参数：
- `--set-subject`
- `--set-to`
- `--set-cc`
- `--set-bcc`

**正文编辑和其他高级操作必须通过 `--patch-file`**。没有 `--set-body` flag。

### 正文编辑：两个 op 的选择

正文编辑通过 `--patch-file` 传入，有两个 op 可选：

| 情况 | op | 行为 |
|------|-----|------|
| 普通草稿（无引用区） | `set_body` | 替换整个正文 |
| 回复/转发草稿，编辑用户撰写部分 | `set_reply_body` | **仅替换引用区前面的用户撰写部分**，自动重新拼接引用区。传入的 value 只包含新的用户撰写内容，**不要包含引用区** |
| 回复/转发草稿，编辑引用区内容 | `set_body` | 全量替换整个正文（含引用区），需自行传入完整的 HTML |
| 用户明确要去掉引用区 | `set_body` | 全量替换，不包含引用区即可 |

**判断方法：** 运行 `--inspect`，若返回 `has_quoted_content: true`，说明草稿包含引用区（由 `+reply` 或 `+forward` 生成）。

**关键区别：**
- `set_reply_body` 的 value = **纯用户撰写内容**（不含引用区），引用区会自动重新拼接
- `set_body` 的 value = **完整正文**（含或不含引用区均可），是全量替换

### 正文编辑：plain+HTML 耦合草稿

当草稿同时包含 `text/plain` 和 `text/html` 部分时，它们构成耦合对。`set_body` 和 `set_reply_body` 均更新 HTML 正文并自动重新生成纯文本摘要。此时务必传入 HTML 作为输入，因为原始主正文为 `text/html`。

## 安全约束

此命令会更新真实草稿。调用前须与用户确认：
1. 草稿 ID
2. 最终收件人范围（To/Cc/Bcc）
3. 最终主题和正文
4. 是否需要附件、内嵌图片或其他高级编辑

## 命令

```bash
# 编辑草稿元数据（主题、收件人）
lark-cli mail +draft-edit --draft-id <draft-id> --set-subject '更新后的主题' --set-to alice@example.com,bob@example.com

# 编辑草稿正文（必须通过 patch-file）
lark-cli mail +draft-edit --draft-id <draft-id> --patch-file ./patch.json

# 查看草稿（只读）— 返回包含 has_quoted_content、attachments_summary 和 inline_summary 的投影
lark-cli mail +draft-edit --draft-id <draft-id> --inspect

# 打印补丁模板
lark-cli mail +draft-edit --print-patch-template

# Dry Run（仅打印请求，不执行）
lark-cli mail +draft-edit --draft-id <draft-id> --set-subject '测试' --dry-run
```

## 通用参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--mailbox <email>` | 否 | 邮箱地址，指定草稿所属的邮箱（默认回退到 `--from`，再回退到 `me`）。优先于 `--from`。可通过 `accessible_mailboxes` 查询可用邮箱 |
| `--draft-id <id>` | 是 | 目标草稿 ID。仅当单独使用 `--print-patch-template` 时可省略 |
| `--set-subject <text>` | 否 | 用此值替换主题 |
| `--set-to <emails>` | 否 | 用此处提供的地址替换整个 To 收件人列表 |
| `--set-cc <emails>` | 否 | 用此处提供的地址替换整个 Cc 抄送列表 |
| `--set-bcc <emails>` | 否 | 用此处提供的地址替换整个 Bcc 密送列表 |
| `--patch-file <path>` | 否 | 所有正文编辑、增量收件人编辑、邮件头编辑、附件变更和内嵌图片变更的入口。相对路径。先运行 `--print-patch-template` 查看 JSON 结构 |
| `--print-patch-template` | 否 | 打印 `--patch-file` 的 JSON 模板和支持的操作。建议在生成补丁文件前先运行此命令。不会读取或写入草稿 |
| `--inspect` | 否 | 查看草稿但不修改。返回包含 `has_quoted_content`（是否有引用区）、`attachments_summary`（含每个附件的 `part_id`、`cid`、`filename`）和 `inline_summary` 的草稿投影 |
| `--format <mode>` | 否 | 输出格式：`json`（默认）/ `pretty` / `table` / `ndjson` / `csv` |
| `--dry-run` | 否 | 仅打印请求，不执行 |

## `--patch-file` 格式

推荐工作流：

1. 运行 `--inspect` 查看草稿当前状态（是否有引用区、附件等）
2. 运行 `--print-patch-template` 查看 JSON 结构
3. 生成符合该结构的补丁文件
4. 运行 `--patch-file`

`--patch-file` 接受项目专用的类型化补丁 JSON 格式，不是 RFC 6902 JSON Patch。

顶层结构：

```json
{
  "ops": [
    { "op": "set_subject", "value": "更新后的主题" }
  ],
  "options": {
    "rewrite_entire_draft": false,
    "allow_protected_header_edits": false
  }
}
```

`options` 字段：

- `rewrite_entire_draft`：默认 `false`。仅当编辑需要合成或重组正文部分（例如添加缺失的主正文部分）时设为 `true`。普通的主题、收件人、正文、附件和内嵌图片编辑保持 `false`。
- `allow_protected_header_edits`：默认 `false`。仅当用户明确要编辑受保护的邮件头并了解可能的会话归档或投递风险时设为 `true`。正常使用保持 `false`。

### 主题与正文

`set_subject`

```json
{ "op": "set_subject", "value": "更新后的主题" }
```

`set_body` — 全量替换整个正文

```json
{ "op": "set_body", "value": "<p>全新的正文内容</p>" }
```

> **注意：** `set_body` 替换整个正文，**包括引用区**。对于回复/转发草稿，如果只需修改用户撰写部分而保留引用区，请使用 `set_reply_body`。

`set_reply_body` — 仅替换用户撰写部分，自动保留引用区

```json
{ "op": "set_reply_body", "value": "<p>新的回复内容</p>" }
```

> **value 只传用户撰写的内容，不要包含引用区。** 引用区会自动从原草稿中提取并重新拼接到 value 后面。
>
> 如果用户要修改引用区里的内容（如修正引用中的错误），必须用 `set_body` 全量传入完整 HTML（含修改后的引用区）。
>
> 如果草稿无引用区，`set_reply_body` 行为与 `set_body` 相同。

### 收件人

`set_recipients`

```json
{ "op": "set_recipients", "field": "to", "addresses": [{ "address": "alice@example.com", "name": "Alice" }] }
```

`add_recipient`

```json
{ "op": "add_recipient", "field": "cc", "address": "alice@example.com", "name": "Alice" }
```

`remove_recipient`

```json
{ "op": "remove_recipient", "field": "cc", "address": "alice@example.com" }
```

### 邮件头

`set_header`

```json
{ "op": "set_header", "name": "X-Custom", "value": "abc" }
```

`remove_header`

```json
{ "op": "remove_header", "name": "X-Custom" }
```

### 附件与内嵌图片

**如何获取 `part_id` / `cid`：** `remove_attachment`、`remove_inline` 和 `replace_inline` 需要 `part_id` 或 `cid` 来定位目标部分。这些值来自草稿的 MIME 结构，与公开 API 的附件 ID **不同**。要获取这些值，先运行 `--inspect`：

```bash
lark-cli mail +draft-edit --draft-id <draft_id> --inspect
```

返回的 `projection.attachments_summary` 和 `projection.inline_summary` 列出了每个部分的 `part_id`、`cid`、`filename` 和 `content_type`。在 `remove_attachment` / `remove_inline` / `replace_inline` 操作中使用这些值。

`add_attachment`

```json
{ "op": "add_attachment", "path": "./report.pdf" }
```

`remove_attachment`

```json
{ "op": "remove_attachment", "target": { "part_id": "1.3" } }
{ "op": "remove_attachment", "target": { "cid": "logo" } }
```

`target` 接受 `part_id` 或 `cid`。优先级：`part_id` > `cid`。

`add_inline`

```json
{ "op": "add_inline", "path": "./logo.png", "cid": "logo" }
```

> **推荐方式：** 直接在 `set_body`/`set_reply_body` 的 HTML 中使用 `<img src="./logo.png" />`（相对路径），系统会自动创建 MIME 内嵌部分、生成 CID 并替换为 `cid:` 引用。仅支持相对路径（如 `./logo.png`），不支持绝对路径。删除或替换 `<img>` 标签时，对应的 MIME 部分会自动清理。详见[在正文中插入内嵌图片](#在正文中插入内嵌图片)。
>
> `add_inline` 仅在需要精确控制 CID 命名时使用。使用时仍需在 HTML 正文中加入 `<img src="cid:...">` 引用。

`replace_inline`

```json
{ "op": "replace_inline", "target": { "part_id": "1.2" }, "path": "./new-logo.png", "filename": "new-logo.png", "content_type": "image/png" }
{ "op": "replace_inline", "target": { "cid": "logo" }, "path": "./new-logo.png" }
```

`replace_inline` 中 `filename` 和 `content_type` 为可选。省略时保留原内嵌部分的文件名和内容类型。`target` 接受 `part_id` 或 `cid`。

`remove_inline`

```json
{ "op": "remove_inline", "target": { "part_id": "1.2" } }
{ "op": "remove_inline", "target": { "cid": "logo" } }
```

注意事项：

- `ops` 按顺序执行
- `target` 接受 `part_id` 或 `cid`；优先级：`part_id` > `cid`
- **所有文件路径（`--patch-file` 及 ops 中的 `path`）必须为相对路径**
- **正文编辑没有 flag，必须通过 `--patch-file`**
- **`set_body` 是完整替换** — 它替换整个正文内容（包括引用区）
- **`set_reply_body` 仅替换引用区前面的用户撰写部分** — 引用区自动重新拼接；value 只传用户撰写内容，不要包含引用区；如果用户要修改引用区内容，用 `set_body` 全量覆盖
- 通过 `--inspect` 返回的 `has_quoted_content` 字段可判断草稿是否包含引用区

## 返回值

成功时：

```json
{
  "ok": true,
  "data": {
    "draft_id": "草稿ID",
    "warning": "This edit flow has no optimistic locking. If the same draft is changed concurrently, the last writer wins."
  }
}
```

## 典型场景

### 获取草稿 → 编辑 → 发送

```bash
# 1. 查看草稿当前状态
lark-cli mail +draft-edit --draft-id <draft_id> --inspect

# 2. 编辑草稿（元数据用 flag，正文用 patch-file）
cat > ./patch.json << 'EOF'
{ "ops": [{ "op": "set_body", "value": "<p>更新后的内容</p>" }] }
EOF
lark-cli mail +draft-edit --draft-id <draft_id> --set-subject '最终版本' --patch-file ./patch.json

# 3. 发送草稿
lark-cli mail user_mailbox.drafts send --params '{"user_mailbox_id":"me","draft_id":"<draft_id>"}'
```

### 编辑回复/转发草稿的正文

回复或转发草稿的正文包含引用区（原邮件引用块）。编辑时需使用 `set_reply_body` 保留引用区。

```bash
# 1. 查看草稿，确认是否有引用区
lark-cli mail +draft-edit --draft-id <draft_id> --inspect
# 返回包含：
#   has_quoted_content: true  ← 说明有引用区，应使用 set_reply_body
#   body_html_summary: "<div>原有回复内容</div>..."

# 2. 使用 set_reply_body 编辑正文（value 只传用户撰写内容，不含引用区）
cat > ./patch.json << 'EOF'
{ "ops": [{ "op": "set_reply_body", "value": "<p>修改后的回复内容</p>" }] }
EOF
lark-cli mail +draft-edit --draft-id <draft_id> --patch-file ./patch.json
```

**注意：** 如果误用 `set_body`，引用区将被覆盖丢失。如果用户明确要去掉引用区或修改引用区内容，则应使用 `set_body`。

### 从草稿中移除附件

```bash
# 1. 查看草稿以获取附件的 part_id / cid
lark-cli mail +draft-edit --draft-id <draft_id> --inspect
# 返回包含 projection.attachments_summary，如：
#   [{"part_id":"1.3","filename":"report.pdf","content_type":"application/pdf"}]

# 2. 编写补丁文件，使用步骤 1 中获取的 part_id
cat > ./patch.json << 'EOF'
{
  "ops": [
    { "op": "remove_attachment", "target": { "part_id": "1.3" } }
  ],
  "options": {}
}
EOF

# 3. 应用补丁
lark-cli mail +draft-edit --draft-id <draft_id> --patch-file ./patch.json
```

### 在正文中插入内嵌图片

直接在 `set_body`/`set_reply_body` 的 HTML 中使用相对路径即可（如 `./logo.png`，不支持绝对路径）。系统会自动创建 MIME 内嵌部分并替换为 `cid:` 引用。

```bash
# 1. 查看草稿以获取当前 HTML 正文
lark-cli mail +draft-edit --draft-id <draft_id> --inspect

# 2. 编写补丁 — 直接使用相对路径（注意：回复草稿用 set_reply_body，普通草稿用 set_body）
cat > ./patch.json << 'EOF'
{
  "ops": [
    { "op": "set_body", "value": "<div>内容<img src=\"./logo.png\" /><img src=\"./photo.jpg\" /></div>" }
  ]
}
EOF

# 3. 应用补丁
lark-cli mail +draft-edit --draft-id <draft_id> --patch-file ./patch.json
```

内嵌图片的增删改通过 HTML 正文自动联动：
- **添加**：在 HTML 中写 `<img src="./image.png" />`，自动创建 MIME 部分
- **删除**：从 HTML 中移除 `<img>` 标签，对应 MIME 部分自动清理
- **替换**：将 `src` 改为新的相对路径，旧 MIME 部分自动移除、新部分自动创建

> **高级用法：** 需要精确控制 CID 命名时，仍可使用 `add_inline` 手动添加 MIME 部分，并在 HTML 中用 `<img src="cid:your-cid">` 引用。

### 使用 patch-file 进行高级编辑

```bash
# 1. 查看补丁模板
lark-cli mail +draft-edit --print-patch-template

# 2. 编写补丁文件（例如添加一个抄送并移除一个附件）
cat > ./patch.json << 'EOF'
{
  "ops": [
    { "op": "add_recipient", "field": "cc", "address": "carol@example.com", "name": "Carol" },
    { "op": "remove_attachment", "target": { "part_id": "1.3" } }
  ],
  "options": {}
}
EOF

# 3. 应用补丁
lark-cli mail +draft-edit --draft-id <draft_id> --patch-file ./patch.json
```

## 相关命令

- `lark-cli mail +draft-create` — 创建新草稿
- `lark-cli mail user_mailbox.drafts get` — 获取草稿原始内容
- `lark-cli mail user_mailbox.drafts send` — 发送已有草稿
