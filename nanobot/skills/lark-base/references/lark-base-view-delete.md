# base +view-delete

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

删除一个视图。

## 推荐命令

```bash
lark-cli base +view-delete \
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
DELETE /open-apis/base/v3/bases/:base_token/tables/:table_id/views/:view_id
```

## 返回重点

- 返回删除成功状态和目标视图标识。

## 工作流


1. 建议先用 `+view-get` 确认目标视图。
2. 删除前必须让用户确认。

## 坑点

- ⚠️ 高风险写操作，删除后不可恢复。

## 参考

- [lark-base-view.md](lark-base-view.md) — view 索引页
