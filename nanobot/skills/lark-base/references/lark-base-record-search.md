# base +record-search

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

按关键词检索记录；CLI 侧通过 `--json` 透传请求体。

## 适用场景

- 需要关键词检索记录。
- 用户已提供明确搜索关键词（`keyword`）。
- 需要附带 `view_id / select_fields` 控制检索范围与返回字段。
- 不用于聚合统计。涉及 SUM/AVG/COUNT/MAX/MIN 时改用 `+data-query`。

## 推荐命令

```bash
lark-cli base +record-search \
  --base-token XXXXXX \
  --table-id tblXXX \
  --json '{"keyword":"Created","search_fields":["Title","fld_owner"],"offset":0,"limit":100}'

lark-cli base +record-search \
  --base-token XXXXXX \
  --table-id tblXXX \
  --json '{"view_id":"vewXXX","keyword":"Alice","search_fields":["Title","Owner"],"select_fields":["Title","Owner","Status"],"offset":0,"limit":50}'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--json <object>` | 是 | 搜索请求体 JSON（结构要求见下方“JSON 要求”） |

## 返回关键字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `query_context.record_scope` | string | 记录范围：`all_records`（全表）/ `view_filtered_records`（按 `view_id` 限定到视图记录） |
| `query_context.field_scope` | string | 字段范围：`selected_fields`（显式传 `select_fields`）/ `view_visible_fields`（未传 `select_fields` 且按视图可见字段）/ `all_fields`（未传 `select_fields` 且无视图限制） |
| `query_context.search_scope` | string | 实际参与搜索的字段集合，格式类似 `fieldTitle(Title), fieldOwner(Owner)` |

## API 入参详情

**HTTP 方法和路径：**

```http
POST /open-apis/base/v3/bases/:base_token/tables/:table_id/records/search
```

### JSON 格式要求

| 字段 | 必填 | 类型 | 约束 |
|------|------|------|------|
| `view_id` | 否 | string | 传入后仅在该视图范围内搜索，并默认按该视图可见字段返回结果 |
| `keyword` | 是 | string | 非空，最小长度 `1` |
| `search_fields` | 是 | string[] | 数组长度 `1-20`；每项是字段 `field_id` 或字段名，代表在这些字段中做关键词搜索 |
| `select_fields` | 否 | string[] | 数组长度 `<=50`；每项是字段 `field_id` 或字段名 |
| `offset` | 否 | int | `>=0`，默认 `0` |
| `limit` | 否 | int | `1-200`，默认 `10` |

## 坑点

- ⚠️ `+record-search` 用于检索，不用于聚合分析；聚合场景使用 `+data-query`。
- ⚠️ 部分字段不支持搜索（例如 `attachment`、`link`）；传入后通常不会报错，但可能导致无法命中对应记录。

## 参考

- [lark-base-record.md](lark-base-record.md) — record 索引页
- [lark-base-record-list.md](lark-base-record-list.md) — 分页列表读取
- [lark-base-data-query.md](lark-base-data-query.md) — 聚合分析
