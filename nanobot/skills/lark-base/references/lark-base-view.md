# base view shortcuts

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

view 相关命令索引。

## 命令导航

| 文档 | 命令 | 说明 |
|------|------|------|
| [lark-base-view-list.md](lark-base-view-list.md) | `+view-list` | 分页列视图 |
| [lark-base-view-get.md](lark-base-view-get.md) | `+view-get` | 获取视图基本信息 |
| [lark-base-view-create.md](lark-base-view-create.md) | `+view-create` | 创建视图 |
| [lark-base-view-delete.md](lark-base-view-delete.md) | `+view-delete` | 删除视图 |
| [lark-base-view-rename.md](lark-base-view-rename.md) | `+view-rename` | 重命名视图 |
| [lark-base-view-get-filter.md](lark-base-view-get-filter.md) | `+view-get-filter` | 读取筛选配置 |
| [lark-base-view-set-filter.md](lark-base-view-set-filter.md) | `+view-set-filter` | 更新筛选配置 |
| [lark-base-view-get-visible-fields.md](lark-base-view-get-visible-fields.md) | `+view-get-visible-fields` | 读取可见字段列表 |
| [lark-base-view-set-visible-fields.md](lark-base-view-set-visible-fields.md) | `+view-set-visible-fields` | 更新可见字段列表 |
| [lark-base-view-get-group.md](lark-base-view-get-group.md) | `+view-get-group` | 读取分组配置 |
| [lark-base-view-set-group.md](lark-base-view-set-group.md) | `+view-set-group` | 更新分组配置 |
| [lark-base-view-get-sort.md](lark-base-view-get-sort.md) | `+view-get-sort` | 读取排序配置 |
| [lark-base-view-set-sort.md](lark-base-view-set-sort.md) | `+view-set-sort` | 更新排序配置 |
| [lark-base-view-get-timebar.md](lark-base-view-get-timebar.md) | `+view-get-timebar` | 读取时间轴配置 |
| [lark-base-view-set-timebar.md](lark-base-view-set-timebar.md) | `+view-set-timebar` | 更新时间轴配置 |
| [lark-base-view-get-card.md](lark-base-view-get-card.md) | `+view-get-card` | 读取卡片配置 |
| [lark-base-view-set-card.md](lark-base-view-set-card.md) | `+view-set-card` | 更新卡片配置 |

## AI 决策前置

先判断视图类型，再选接口能力；不支持的能力直接不要调用。

| 视图类型 | 可用能力 |
|------|------|
| `grid` | `group` `sort` `filter` |
| `kanban` | `group` `sort` `filter` `card` |
| `gallery` | `sort` `filter` `card` |
| `calendar` | `filter` `timebar` |
| `gantt` | `group` `sort` `filter` `timebar` |

## 说明

- 聚合页只保留目录职责；每个命令的详细说明请进入对应单命令文档。
- 所有 `+xxx-list` 调用都必须串行执行；若要批量跑多个 list 请求，只能串行执行。
