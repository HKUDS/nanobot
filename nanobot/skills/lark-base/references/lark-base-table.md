# base table shortcuts

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

table 相关命令索引。

## 命令导航

| 文档 | 命令 | 说明 |
|------|------|------|
| [lark-base-table-list.md](lark-base-table-list.md) | `+table-list` | 分页列出数据表 |
| [lark-base-table-get.md](lark-base-table-get.md) | `+table-get` | 获取单表概要、字段和视图 |
| [lark-base-table-create.md](lark-base-table-create.md) | `+table-create` | 创建数据表，可附带字段 / 视图 |
| [lark-base-table-update.md](lark-base-table-update.md) | `+table-update` | 重命名数据表 |
| [lark-base-table-delete.md](lark-base-table-delete.md) | `+table-delete` | 删除数据表 |

## 说明

- 聚合页只保留目录职责；调用任一 table 命令前，务必先阅读对应单命令文档（本页不提供调用细节）。
- 所有 `+xxx-list` 调用都必须串行执行；若要批量跑多个 list 请求，只能串行执行。
