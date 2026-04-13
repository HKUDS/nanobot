
# docs +media-insert（文档末尾插入图片/文件）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

把“创建空 block → 上传文件 → 设置 token”三步合并成一个命令，在**文档末尾**插入本地图片或文件。

## 命令

```bash
# 插入图片（默认）
lark-cli docs +media-insert --doc doxcnXXX --file ./image.png

# doc 支持直接传 docx URL（自动提取 document_id）
lark-cli docs +media-insert --doc "https://xxx.feishu.cn/docx/doxcnXXX" --file ./image.png

# 如果上一步是 create-doc，优先传返回值里的 doc_id
# 不要把 /wiki/... 形式的 doc_url 直接传给 docs +media-insert
lark-cli docs +media-insert --doc doxcnReturnedByCreateDoc --file ./image.png

# 插入文件（非图片）
lark-cli docs +media-insert --doc doxcnXXX --file ./spec.pdf --type file

# 图片对齐与描述（caption）
lark-cli docs +media-insert --doc doxcnXXX --file ./arch.png --align center --caption "架构图"
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--doc <id>` | 是 | 文档 ID 或 docx URL（仅支持 `/docx/<document_id>` 形式自动提取；**不支持 `/wiki/...` URL 自动提取**） |
| `--file <path>` | 是 | 本地文件路径（文件大于 20MB 时自动切换分片上传） |
| `--type <type>` | 否 | `image`（默认）或 `file` |
| `--align <align>` | 否 | 仅图片：`left` / `center`（默认）/ `right` |
| `--caption <text>` | 否 | 仅图片：图片描述 |

> [!IMPORTANT]
> 如果上一步是 [`lark-doc-create`](lark-doc-create.md)，并且它在知识库/知识空间场景下返回的是 `/wiki/...` 形式的 `doc_url`，后续调用 `docs +media-insert` 时应优先传 `doc_id`，不要直接传这个 `doc_url`。

## 输出

命令成功后会输出 JSON，包含：`document_id`、`block_id`、`file_token`、`file_name`、`type`。

> [!CAUTION]
> 这是**写入操作**（会修改文档内容）—— 执行前必须确认用户意图。

## 参考

- [lark-doc-fetch](lark-doc-fetch.md) — 获取文档内容（可用于确认插入后的结果、以及提取媒体 token）
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数