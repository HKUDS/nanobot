# base +table-update

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

重命名一张表。

## 推荐命令

```bash
lark-cli base +table-update \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --name "重点客户名单"
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--name <name>` | 是 | 新表名 |

## API 入参详情

**HTTP 方法和路径：**

```
PATCH /open-apis/base/v3/bases/:base_token/tables/:table_id
```

## 返回重点

- 返回 `table` 和 `updated: true`。
- 当前只支持更新名称。

## 工作流


1. 建议先用 `+table-get` 确认目标表。

## 坑点

- ⚠️ 这是写入操作，执行前必须确认。

## 参考

- [lark-base-table.md](lark-base-table.md) — table 索引页
- [lark-base-table-get.md](lark-base-table-get.md) — 查表详情
