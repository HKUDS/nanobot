# base +record-history-list

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

查询指定记录的变更历史。当前可执行命令为 `+record-history-list`，无 `+history-list` 别名。

## 推荐命令

```bash
# 查询最新一页历史
lark-cli base +record-history-list \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --record-id rec_xxx

# 指定分页大小，带游标翻页
lark-cli base +record-history-list \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --record-id rec_xxx \
  --page-size 30 \
  --max-version 123456
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID |
| `--record-id <id>` | 是 | 记录 ID |
| `--page-size <n>` | 否 | 每页条数，默认 `30`，最大 `50` |
| `--max-version <n>` | 否 | 翻页游标，取上一页返回的 `next_max_version` 值 |

## API 入参详情

**HTTP 方法和路径：**

```
GET /open-apis/base/v3/bases/:base_token/record_history
```

- Query 参数：`table_id`、`record_id`、`page_size`、`max_version`。

## 返回重点

- 返回记录历史条目列表（按版本号降序，最新在前），而不是记录当前值。
- 每条历史包含：版本号(`rev`)、操作人(`operator`)、操作时间(`create_time`，**秒级** Unix 时间戳)、操作类型(`activity_type`)、字段变更列表(`field_changes`)。
- 字段变更包含：字段 ID、字段名、字段类型、变更前值(`before`)、变更后值(`after`)。
- 适合定位谁改了这条记录、什么时候改的、改了哪些字段。

### activity_type 取值

| 值 | 含义 |
|------|------|
| `create` | 记录创建 |
| `update` | 记录编辑 |
| `delete` | 记录删除 |

### 不出现在历史中的字段类型

以下字段类型的变更**不会**出现在 `field_changes` 中：
- **计算字段**：公式(formula)、查找引用(lookup)
- **系统字段**：自动编号、创建时间、创建人、修改时间、修改人

## 翻页工作流

1. **首次请求**：不传 `--max-version`，获取最新一页。
2. **判断是否有下一页**：检查返回的 `has_more` 字段。
3. **翻页**：若 `has_more = true`，取返回的 `next_max_version` 值，传入下一次请求的 `--max-version`。
4. **终止**：当 `has_more = false` 时停止。

## 工作流

1. 先确认 `table-id` 和 `record-id` 都来自同一张表。
2. 先查最新一页，再按翻页工作流向前翻页。

## 坑点

- ⚠️ `+record-history-list` 属于 `+xxx-list`，禁止并发调用；批量执行时只能串行。
- ⚠️ 当前不支持整表历史扫描，只支持单条记录历史。

## 参考

- [lark-base-history.md](lark-base-history.md) — history 索引页
- [lark-base-record.md](lark-base-record.md) — record 索引页
