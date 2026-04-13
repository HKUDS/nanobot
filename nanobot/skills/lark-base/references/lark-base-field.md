# base field shortcuts

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

field 相关命令索引。

## 命令导航

| 文档 | 命令 | 说明 |
|------|------|------|
| [lark-base-field-list.md](lark-base-field-list.md) | `+field-list` | 分页列字段 |
| [lark-base-field-get.md](lark-base-field-get.md) | `+field-get` | 获取单字段配置 |
| [lark-base-field-create.md](lark-base-field-create.md) | `+field-create` | 创建字段 |
| [lark-base-field-update.md](lark-base-field-update.md) | `+field-update` | 更新字段 |
| [lark-base-field-search-options.md](lark-base-field-search-options.md) | `+field-search-options` | 搜索选项字段候选值 |
| [lark-base-field-delete.md](lark-base-field-delete.md) | `+field-delete` | 删除字段 |

## 说明

- 聚合页只保留目录职责；每个命令的详细说明请进入对应单命令文档。
- 所有 `+xxx-list` 调用都必须串行执行；若要批量跑多个 list 请求，只能串行执行。
- 写字段 JSON 前优先阅读 [lark-base-shortcut-field-properties.md](lark-base-shortcut-field-properties.md)。
