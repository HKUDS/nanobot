# base +view-get-group

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

获取分组配置。

## 推荐命令

```bash
lark-cli base +view-get-group \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --view-id viw_xxx
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--view-id <id_or_name>` | 是 | 视图 ID 或视图名 |

## API 入参详情

**HTTP 方法和路径：**

```
GET /open-apis/base/v3/bases/:base_token/tables/:table_id/views/:view_id/group
```

## 返回重点

- 返回原始分组配置。

## 参考

- [lark-base-view.md](lark-base-view.md) — view 索引页
