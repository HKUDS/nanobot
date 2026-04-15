
# drive +add-comment

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

给文档添加评论。底层统一走 `/open-apis/drive/v1/files/:file_token/new_comments`（`create_v2`）接口；未指定位置时省略 `anchor` 创建全文评论，指定 `--selection-with-ellipsis` 或 `--block-id` 时传入 `anchor.block_id` 创建局部评论。支持直接传 docx URL/token、旧版 doc URL（仅全文评论），也支持传最终可解析为 doc/docx 的 wiki URL。

## 命令

```bash
# 默认：未指定位置时添加全文评论
lark-cli drive +add-comment \
  --doc "https://example.larksuite.com/docx/<DOC_ID>" \
  --content '[{"type":"text","text":"请补充发布说明"}]'

# 也可以显式指定为全文评论；旧版 doc URL 仅支持全文评论
lark-cli drive +add-comment \
  --doc "https://example.larksuite.com/doc/<DOC_ID>" \
  --full-comment \
  --content '[{"type":"text","text":"请补充旧版文档的背景信息"}]'

# wiki 链接也可以，shortcut 会先解析到真实 doc/docx token
lark-cli drive +add-comment \
  --doc "https://example.larksuite.com/wiki/<WIKI_TOKEN>" \
  --content '[{"type":"text","text":"这里需要一段全文评论"}]'

# 给 docx 文档里匹配到的文字添加局部评论
lark-cli drive +add-comment \
  --doc "https://example.larksuite.com/docx/<DOC_ID>" \
  --selection-with-ellipsis "流程" \
  --content '[{"type":"text","text":"请补充流程说明"}]'

# wiki 链接也支持局部评论，但解析结果必须是 docx
lark-cli drive +add-comment \
  --doc "https://example.larksuite.com/wiki/<WIKI_TOKEN>" \
  --selection-with-ellipsis "流程" \
  --content '[{"type":"text","text":"请补充更细的开发步骤"}]'

# 组合文本、@用户、链接元素
lark-cli drive +add-comment \
  --doc "https://example.larksuite.com/docx/<DOC_ID>" \
  --selection-with-ellipsis "流程" \
  --content '[{"type":"text","text":"请 "},{"type":"mention_user","text":"ou_xxx"},{"type":"text","text":" 处理，参考 "},{"type":"link","text":"https://example.com"}]'

# 已知 block_id 时可跳过 MCP 直接创建局部评论
lark-cli drive +add-comment \
  --doc "<DOCX_TOKEN>" \
  --block-id "<BLOCK_ID>" \
  --content '[{"type":"text","text":"评论内容"}]'

# 如果需要更底层的原生 API，也可以直接调用 V2 协议
lark-cli schema drive.file.comments.create_v2

lark-cli drive file.comments create_v2 \
  --params '{"file_token":"<DOC_TOKEN>"}' \
  --data '{"file_type":"docx","reply_elements":[{"type":"text","text":"全文评论内容"}]}'

# 预览底层调用链
lark-cli drive +add-comment \
  --doc "https://example.larksuite.com/docx/<DOC_ID>" \
  --selection-with-ellipsis "流程" \
  --content '[{"type":"text","text":"请补充流程说明"}]' \
  --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--doc` | 是 | 文档 URL / token，或可解析到 `doc`/`docx` 的 wiki URL。原始 token 默认按 `docx` 处理；旧版 `doc` 请传 URL 或 wiki 链接 |
| `--content` | 是 | `reply_elements` JSON 数组字符串。示例：`'[{"type":"text","text":"文本"},{"type":"mention_user","text":"ou_xxx"},{"type":"link","text":"https://example.com"}]'` |
| `--full-comment` | 否 | 显式指定创建全文评论；未传 `--selection-with-ellipsis` / `--block-id` 时也会默认走全文评论 |
| `--selection-with-ellipsis` | 局部评论时二选一 | 目标文本定位表达式，支持纯文本或 `开头...结尾`；与 `--block-id` 互斥 |
| `--block-id` | 局部评论时二选一 | 已知目标块 ID 时直接使用；与 `--selection-with-ellipsis` 互斥 |

## 行为说明

- **无需预先获取文档内容**：使用 `--selection-with-ellipsis` 时，shortcut 内部会自动调用 `locate-doc` 定位目标文本，不需要先调用 `docs +fetch` 获取文档。
- 未传 `--selection-with-ellipsis` / `--block-id` 时，shortcut 默认创建**全文评论**；也可以显式传 `--full-comment`。
- 全文评论支持 `docx`、旧版 `doc` URL，以及最终可解析为 `doc`/`docx` 的 wiki URL。
- 传 `--selection-with-ellipsis` 或 `--block-id` 时，shortcut 创建**局部评论（划词评论）**；该模式仅支持 `docx`，以及最终可解析为 `docx` 的 wiki URL。
- `--content` 接收结构化评论元素数组；`type` 支持 `text`、`mention_user`、`link`。为便于书写，`mention_user` / `link` 元素可以直接把用户 ID 或链接地址放在 `text` 字段中，shortcut 会转换成 OpenAPI 所需字段。
- 局部评论走 `locate-doc` 时，内部固定使用 `limit=10`。
- 当 `locate-doc` 命中多处时，shortcut 会中止并提示用户继续收窄 `--selection-with-ellipsis`，不支持手动指定匹配序号。
- 写入评论前会自动生成符合 OpenAPI 定义的请求体：
- 统一接口：`POST /new_comments`
- 统一字段：`file_type` + `reply_elements`
- 全文评论：省略 `anchor`
- 局部评论：传入 `anchor.block_id`
- `--dry-run` 仅预览调用链和请求体，不会实际写入。
- 如果需要更底层的控制，仍可改用 `lark-cli schema drive.file.comments.create_v2` + `lark-cli drive file.comments create_v2`。

> [!CAUTION]
> 这是**写入操作** —— 执行前必须确认用户意图。

## 参考

- [lark-drive](../SKILL.md) -- 云空间全部命令
- [lark-shared](../../lark-shared/SKILL.md) -- 认证和全局参数
