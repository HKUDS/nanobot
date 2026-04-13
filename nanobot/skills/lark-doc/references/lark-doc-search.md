
# docs +search（云空间搜索：文档 / Wiki / 电子表格）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

基于 Search v2 接口 `POST /open-apis/search/v2/doc_wiki/search`，以**用户身份**统一搜索云空间对象。

虽然接口名是 `doc_wiki/search`，但命中结果不只限于文档 / Wiki，也会返回 `SHEET`、`BITABLE`、`FOLDER` 等云空间对象。因此它适合作为云空间对象的资源发现入口：先定位文档、知识库节点、电子表格、多维表格、文件夹，以及用户以“表格 / 报表”方式描述的相关对象，再切回对应业务 skill 做对象内部操作。

该 shortcut 会：

- 未指定范围字段时，自动补齐 `doc_filter` / `wiki_filter`
- 自动将 `--filter` 中的公共字段同步到搜索范围对应的 filter；`folder_tokens` 仅发到 `doc_filter`，`space_ids` 仅发到 `wiki_filter`
- 支持在 `filter.open_time` / `filter.create_time` 中使用 ISO 8601 时间，并自动转换为 Unix 秒
- 在返回结果中为 `*_time` 字段补充 `*_time_iso`（便于阅读）
- `title_highlighted` / `summary_highlighted` 可能包含高亮标签（如 `<h>` / `<hb>`）

## 命令

> **关键约束：搜索关键词必须通过 `--query` 传递。**
> 正确：`lark-cli docs +search --query "方案"`
> 错误：`lark-cli docs +search 方案`
> `+search` 不接受“搜索词位置参数”这种写法；如果把关键词直接跟在命令后面，不会进入 `query`，会变成空搜或返回不符合预期的结果。

```bash
# 关键词搜索
lark-cli docs +search --query "季度总结"

# 搜标题里带“评测结果”的电子表格 / 文档
lark-cli docs +search --query "评测结果"

# 标题包含关键词（默认按关键词检索，不做精确标题匹配）
lark-cli docs +search --query "方案"

# 使用服务端标题限定语法
lark-cli docs +search --query 'intitle:方案'

# 精确短语匹配
lark-cli docs +search --query '"季度 总结"'

# 逻辑或 / 排除
lark-cli docs +search --query '方案 OR 草稿'
lark-cli docs +search --query '方案 -草稿'

# 标题精确短语匹配
lark-cli docs +search --query 'intitle:"季度总结"'

# 按最近打开时间过滤
lark-cli docs +search \
  --query "方案" \
  --filter '{"open_time":{"start":"2025-09-24T00:00:00+08:00","end":"2025-12-24T23:59:59+08:00"}}'

# 按文档所有者过滤（creator_ids 传文档所有者 open_id，不是邮箱 / user_id）
lark-cli docs +search \
  --query "季度总结" \
  --filter '{"creator_ids":["ou_7890123456abcdef"]}'

# 只搜索指定类型
lark-cli docs +search \
  --query "评测结果" \
  --filter '{"doc_types":["SHEET","DOCX"]}'

# 只在指定文件夹下搜索文档（folder_token 通常来自 /drive/folder/<token>）
lark-cli docs +search \
  --query "方案" \
  --filter '{"folder_tokens":["fld_123456"]}'

# 只搜标题，不搜正文 / 摘要
lark-cli docs +search \
  --query "周报" \
  --filter '{"only_title":true}'

# 只搜评论，不搜标题 / 正文
lark-cli docs +search \
  --query "延期原因" \
  --filter '{"only_comment":true}'

# 只搜索指定群会话里分享过的文档（chat_id 最多 20 个）
lark-cli docs +search \
  --query "方案" \
  --filter '{"chat_ids":["oc_1234567890abcdef"]}'

# 只搜索指定分享者分享过的文档（sharer_ids 传分享者 open_id，最多 20 个）
lark-cli docs +search \
  --query "复盘" \
  --filter '{"sharer_ids":["ou_7890123456abcdef"]}'

# 按创建时间过滤并指定排序方式
lark-cli docs +search \
  --query "方案" \
  --filter '{"create_time":{"start":"2026-01-01","end":"2026-03-31"},"sort_type":"CREATE_TIME"}'

# 组合多个筛选条件
lark-cli docs +search \
  --query "项目复盘" \
  --filter '{"creator_ids":["ou_7890123456abcdef"],"doc_types":["DOCX","SHEET"],"only_title":true,"sort_type":"OPEN_TIME","open_time":{"start":"2026-01-01T00:00:00+08:00"}}'

# 只在指定知识空间下搜 Wiki
lark-cli docs +search \
  --query "研发规范" \
  --filter '{"space_ids":["space_1234567890fedcba"]}'

# 空搜（不传 query 或传空字符串）：按最近浏览等默认规则返回
lark-cli docs +search

# 人类可读格式输出
lark-cli docs +search --query "OKR" --format pretty

# 返回原始 JSON，并用 page_token 翻页
lark-cli docs +search --query "方案" --format json
lark-cli docs +search --query "方案" --format json --page-token '<PAGE_TOKEN>'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--query <text>` | 否 | 搜索关键词。**支持高级 Boolean 语法**以提升搜索精度：<br>1. 使用空格表示 AND（如 `方案 设计`）。<br>2. 使用 `OR` 表示逻辑或（如 `方案 OR 草稿`）。<br>3. 使用 `-` 表示排除（如 `方案 -草稿`）。<br>4. 使用双引号 `""` 表示精确匹配短语。<br>5. 使用 `intitle:` 限定关键词出现在标题中（如 `intitle:总结` 或 `intitle:"季度 总结"`）。不传/空字符串表示空搜。**凡是有关键词，都要显式通过 `--query` 传递，不要写成位置参数。** |
| `--filter <json>` | 否 | JSON 对象。公共字段默认同时应用到 `doc_filter` / `wiki_filter`；若传 `folder_tokens`，则只发 `doc_filter`；若传 `space_ids`，则只发 `wiki_filter`；两者不能同时传 |
| `--page-size <n>` | 否 | 每页数量（默认 15，最大 20） |
| `--page-token <token>` | 否 | 翻页标记（配合 `has_more` 使用） |
| `--format` | 否 | 输出格式：json（默认） \| pretty |

## `--query` 高级语法

以下语法由服务端搜索能力处理，适合把过滤逻辑尽量下推到搜索侧：

- 空格表示 AND：`方案 设计`
- `OR` 表示逻辑或：`方案 OR 草稿`
- `-` 表示排除：`方案 -草稿`
- 双引号表示精确短语：`"季度 总结"`
- `intitle:` 表示标题限定：`intitle:总结`
- 标题精确短语：`intitle:"季度总结"`

## `--filter` 字段速查

`--filter` 是一个 JSON 对象。大多数字段默认会同时作用于 `doc_filter` 和 `wiki_filter`；其中 `folder_tokens` 只用于文档侧，`space_ids` 只用于 Wiki 侧。

### 字段归属

- `doc_filter` / `wiki_filter` 公共字段：`creator_ids`、`doc_types`、`chat_ids`、`sharer_ids`、`only_title`、`only_comment`、`open_time`、`sort_type`、`create_time`
- `doc_filter` 独有字段：`folder_tokens`
- `wiki_filter` 独有字段：`space_ids`
- 如果传 `folder_tokens`，shortcut 只发送 `doc_filter`
- 如果传 `space_ids`，shortcut 只发送 `wiki_filter`
- 如果同时传 `folder_tokens` 和 `space_ids`，shortcut 直接报错，不支持同时查询文档文件夹范围和知识空间范围

| 字段 | 作用范围 | 类型 | 说明 |
|------|----------|------|------|
| `creator_ids` | 文档 + Wiki | `string[]` | 所有者列表，**必须传 open_id**，不是 `user_id` / `union_id` / 邮箱。比如 `["ou_xxx"]`。如果只有姓名，先用 `lark-contact` 查 open_id |
| `doc_types` | 文档 + Wiki | `string[]` | 资源类型过滤。常用值：`DOC`、`DOCX`、`SHEET`、`BITABLE`、`FILE`、`WIKI`、`SLIDES`、`FOLDER`、`CATALOG`、`SHORTCUT` |
| `chat_ids` | 文档 + Wiki | `string[]` | 群会话 ID 列表，只搜索这些会话里分享过的文档，最多 20 个。通常传群 `chat_id`（如 `oc_xxx`）；如果用户只给群名，先用 `lark-im` 定位群 |
| `sharer_ids` | 文档 + Wiki | `string[]` | 分享者列表，**必须传分享者 open_id**，最多 20 个。适合“某人分享过的文档”；如果只有姓名，先用 `lark-contact` 查 open_id |
| `folder_tokens` | 仅文档 | `string[]` | 只搜索指定云空间文件夹下的文档；值通常来自文件夹 URL `/drive/folder/<folder_token>` |
| `space_ids` | 仅 Wiki | `string[]` | 只搜索指定知识空间下的 Wiki 节点 |
| `only_title` | 文档 + Wiki | `boolean` | 只搜标题。注意这不是“标题精确等于”，只是把搜索范围限制在标题 |
| `only_comment` | 文档 + Wiki | `boolean` | 只搜评论。用法类似 `only_title`，只是把搜索范围限制在评论区；默认 `false` |
| `open_time` | 文档 + Wiki | `object` | 最近打开时间范围，支持 `{ "start": "...", "end": "..." }`。shortcut 支持 ISO 8601 / `YYYY-MM-DD` / Unix 秒，并自动转成秒级时间戳 |
| `sort_type` | 文档 + Wiki | `string` | 排序方式。常用值：`DEFAULT_TYPE`、`OPEN_TIME`、`EDIT_TIME`、`EDIT_TIME_ASC`、`CREATE_TIME` |
| `create_time` | 文档 + Wiki | `object` | 文档 / Wiki 创建时间范围，结构与 `open_time` 相同 |

### 字段使用建议

- `creator_ids`：适合“找某个人创建的文档 / 表格 / Wiki”。如果用户只给姓名，不要猜 ID，先查这个人的 `open_id`。
- `doc_types`：只在用户**明确指定资源类型**时使用，适合先把资源类型缩小。显式类型词可按以下方式映射：`表格 / 电子表格 / spreadsheet -> ["SHEET"]`、`多维表格 / base / bitable -> ["BITABLE"]`、`知识库 / wiki -> ["WIKI"]`、`文件夹 -> ["FOLDER"]`、`普通文档` 或明确要求“只看文档类型、不要表格 / Wiki” -> `["DOC","DOCX"]`。不要因为用户口头说“文档”就默认补 `DOC` / `DOCX`，因为“文档”在很多场景里只是对云空间对象的泛称。
- `chat_ids`：适合“搜某个群里分享过的文档”“看某个群会话里的方案”。如果用户只给群名，先切到 `lark-im` 用群搜索能力拿到 `chat_id`，再回到 `docs +search`。
- `sharer_ids`：适合“找某人分享过的文档”“看某个同事转给我的资料”。如果用户只给姓名，不要猜 ID，先用 `lark-contact` 查分享者 `open_id`。
- `folder_tokens`：适合“在某个云空间文件夹里搜文档”。它不是知识空间 `space_id`，两者不要混用。
- `only_title`：适合“标题里包含某个词”的场景；如果用户明确表达标题限定，也可以直接在 `--query` 里使用 `intitle:`。如果用户要“标题精确等于”，优先使用 `intitle:"完整标题"`，必要时再做客户端精确确认。
- `only_comment`：适合“评论里提到某个词”“只找评论区讨论过某件事”。它和 `only_title` 一样，都是把搜索范围缩小到特定区域，但这里限制到评论区。
- `open_time`：适合“最近打开过 / 最近看过”的描述；如果用户说相对时间，先换算成明确绝对时间再传。
- `sort_type`：`CREATE_TIME_ASC` 在协议里标注“暂不支持”，`ENTITY_CREATE_TIME_ASC` / `ENTITY_CREATE_TIME_DESC` 已废弃，默认不要主动使用。
- `create_time`：适合“今年新建的”“上个月创建的”这类条件；不写 `start` / `end` 时，协议默认窗口是“请求时间往前 1 年”到“请求时间”。

### 常见 `--filter` JSON 片段

```json
{"creator_ids":["ou_7890123456abcdef"]}
{"doc_types":["SHEET","DOCX"]}
{"chat_ids":["oc_1234567890abcdef"]}
{"sharer_ids":["ou_7890123456abcdef"]}
{"folder_tokens":["fld_123456"]}
{"only_title":true}
{"only_comment":true}
{"open_time":{"start":"2026-01-01T00:00:00+08:00","end":"2026-03-31T23:59:59+08:00"},"sort_type":"OPEN_TIME"}
{"create_time":{"start":"2026-01-01","end":"2026-03-31"},"sort_type":"CREATE_TIME"}
{"space_ids":["space_1234567890fedcba"]}
```

## 结果判别

- `result_meta.doc_types == SHEET`：电子表格，后续切到 `lark-sheets`
- 其他类型：继续按对应 skill 或 API 处理

## 决策规则

- 参数传递：只要用户给了搜索关键词，就必须显式使用 `--query "<关键词>"`。不要生成 `lark-cli docs +search 方案`、`lark-cli docs +search xxx（搜索关键词）` 这种位置参数写法。
- 查询语义：必须优先利用 --query 的高级语法（如 intitle:、""、-）将过滤逻辑下推给服务端。当用户要求“标题精确等于 X”时，直接使用 --query "intitle:\"X\""，严禁先进行模糊搜索再做客户端二次筛选。只有在遇到服务端语法无法覆盖的复杂本地比对场景时，才允许在客户端过滤，且比对前必须先去掉 title_highlighted 里的高亮标签。
- 实体补全：如果用户要按“某个群里分享的文档”搜索，先用 `lark-im` 拿 `chat_id` 再填 `chat_ids`；如果用户要按“某人分享的文档”搜索，先用 `lark-contact` 拿 `open_id` 再填 `sharer_ids`。
- 零结果回退：如果因为用户的显式类型约束加了 `doc_types` 且结果为 0，可以提示“按指定类型没搜到”；只有在不违背用户明确约束的前提下，才建议放宽类型重试。
- 入口选择：用户说“找表格标题”“找名为 `X` 的电子表格”“搜某个报表”时，也默认走 `docs +search`。不要误用 `sheets +find` 做跨文件搜索。
- 分页策略：默认只返回**第一页**，并说明 `has_more` / `page_token`。只有当用户明确要求“全部结果”“继续翻页”“全量扫描”“所有结果”“完整列表”时，才继续翻页。
- 翻页上限：即使用户要求全量，单轮也最多先拉 **5 页**（按默认 `page-size=20` 约等于最多 100 条结果）。达到上限后，先回报当前进度和是否还有更多页，再让用户决定是否继续下一批。
- 总数口径：`total` 是 OpenAPI 的搜索结果总数，不一定等于客户端二次筛选后的精确数量。凡是依赖本地过滤、去重、精确标题匹配的场景，都不要默认承诺“精确总数”。
- 原始返回：如果用户要求“直接返回接口数据 / 原始返回”，优先使用 `--format json`，不要额外做精确标题过滤或摘要重写。
- 时间表达：用户如果说“3 到 6 个月前”“最近半年内”等相对时间，先转换成明确的绝对时间，再写入 `filter.open_time` / `filter.create_time`。
- 跨 skill handoff：如果搜索的目标是某个 spreadsheet，返回命中的标题、URL、token 等定位信息后，应切换到 `lark-sheets` 继续后续操作，不要把 `docs +search` 当成对象内部查询。

## 权限

| 操作 | 所需 scope |
|------|-----------|
| 搜索云空间对象（含文档 / Wiki / 表格资源发现） | `search:docs:read` |
