# base +table-get

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

获取一张表的聚合信息：表基础信息、全部字段、全部视图。

## 推荐命令

```bash
lark-cli base +table-get \
  --base-token app_xxx \
  --table-id tbl_xxx
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID（`id` 必须以 `tbl` 开头）或表名 |

## API 入参详情

**HTTP 方法和路径：**

```
GET /open-apis/base/v3/bases/:base_token/tables/:table_id
```

- CLI 内部还会继续查询 `/fields` 和 `/views`，并聚合输出。

## 返回重点

- 返回 `table`、`fields`、`views` 三段数据。
- 适合先摸清表结构，再继续字段或视图操作。

## 坑点

- ⚠️ 如果 `--table-id` 传的是 `id`，必须是 `tbl` 开头；不是的话先询问用户具体是哪张表，或先用 `+table-list` 查表列表再确认。
- ⚠️ `--table-id` 支持传表名，但重名场景下建议优先传 `tbl_xxx`。

## 参考

- [lark-base-table.md](lark-base-table.md) — table 索引页
- [lark-base-field-list.md](lark-base-field-list.md) — 列字段
- [lark-base-view-list.md](lark-base-view-list.md) — 列视图
