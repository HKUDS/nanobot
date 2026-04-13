# base +record-list

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

分页列出一张表里的记录；可按视图过滤，也可按字段裁剪返回列。

> 默认优先使用 `+record-list`；仅当用户提供明确搜索关键词时，才使用 [lark-base-record-search.md](lark-base-record-search.md)。

## 返回关键字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `has_more` | boolean | 是否还有下一页数据；`true` 表示可继续翻页，`false` 表示已到末页 |
| `query_context.record_scope` | string | 记录范围：`all_records`（全表）或 `view_filtered_records`（按视图过滤） |
| `query_context.field_scope` | string | 字段范围：`selected_fields`（显式传 `--field-id`）/ `view_visible_fields`（未传 `--field-id` 且按视图可见字段）/ `all_fields`（未传 `--field-id` 且无视图限制） |

## 字段返回优先级

- `query_context.field_scope` 的优先级为：`selected_fields`（explicit `--field-id`） > `view_visible_fields`（view visible fields） > `all_fields`（table all fields）。

## 按需翻页规则

1. 先执行一次 `+record-list` 获取首批结果。
2. 检查返回的 `has_more`。
3. 仅当同时满足以下条件时才继续翻页：
   - `has_more = true`
   - 用户问题需要更多数据（例如“全部导出”“统计全量明细”“继续加载下一页”）
4. 若用户只要部分结果（例如“先看前 20 条”“先给示例数据”），即使 `has_more = true` 也不继续翻页。
5. 继续翻页时，`offset` 按已读取数量递增，直到满足用户需求或 `has_more = false`。

## 推荐命令

```bash
lark-cli base +record-list \
  --base-token XXXXXX \
  --table-id tblXXX \
  --offset 0 \
  --limit 100

lark-cli base +record-list \
  --base-token XXXXXX \
  --table-id tblXXX \
  --view-id vewXXX \
  --field-id fldStatus \
  --field-id 项目名称 \
  --offset 0 \
  --limit 50
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--view-id <id>` | 否 | 视图 ID；传入后只读该视图结果 |
| `--field-id <id_or_name>` | 否 | 字段 ID 或字段名；可重复传入多个 `--field-id` 裁剪返回列 |
| `--offset <n>` | 否 | 分页偏移，默认 `0` |
| `--limit <n>` | 否 | 分页大小，默认 `100`，范围 `1-200`（最大 `200`，超过会报错） |

## API 入参详情

**HTTP 方法和路径：**

```
GET /open-apis/base/v3/bases/:base_token/tables/:table_id/records
```

- 查询参数会附带 `view_id / field_id(repeatable) / offset / limit`。


## 坑点

- ⚠️ `+record-list` 禁止并发调用；批量拉多个视图或多张表时必须串行。
- ⚠️ `--limit` 最大 `200`，不要传超过 `200` 的值。
- ⚠️ 分页时优先根据返回的 `has_more` 判断是否继续请求，不要盲目预拉全量数据。
- ⚠️ `--field-id` 接受字段 ID 或字段名。
- ⚠️ 复杂筛选优先落到视图里，再用 `--view-id` 读取。

## 参考

- [lark-base-record.md](lark-base-record.md) — record 索引页
- [lark-base-view-set-filter.md](lark-base-view-set-filter.md) — 配筛选
