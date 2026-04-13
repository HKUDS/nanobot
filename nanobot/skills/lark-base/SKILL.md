---
name: lark-base
version: 1.2.0
description: "当需要用 lark-cli 操作飞书多维表格（Base）时调用：适用于建表、字段管理、记录读写、视图配置、历史查询，以及角色/表单/仪表盘管理/工作流；也适用于把旧的 +table / +field / +record 写法改成当前命令写法。涉及字段设计、公式字段、查找引用、跨表计算、行级派生指标、数据分析需求时也必须使用本 skill。"
metadata:
  requires:
    bins: ["lark-cli"]
  cliHelp: "lark-cli base --help"
---

# base

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)。
> **执行前必做：** 执行任何 `base` 命令前，必须先阅读对应命令的 reference 文档，再调用命令。
> **命名约定：** Base 业务命令仅使用 `lark-cli base +...` 形式；如需先解析 Wiki 链接，可先调用 `lark-cli wiki ...`。
> **分流规则：** 如果用户要“把本地文件导入成 Base / 多维表格 / bitable”，第一步不是 `base`，而是 `lark-cli drive +import --type bitable`；导入完成后再回到 `lark-cli base +...` 做表内操作。

## 1. 何时使用本 Skill

### 1.1 触发条件

以下场景应使用本 skill：

- 用户明确要操作飞书多维表格 / Base。
- 用户要建表、改表、查表、删表，或管理字段、记录、视图。
- 用户要做公式字段、lookup 字段、派生指标、跨表计算。
- 用户要做临时统计、聚合分析、比较排序、求最值。
- 用户要管理 workflow、dashboard、表单、角色权限。
- 用户给出 `/base/{token}` 链接。
- 用户给出 `/wiki/{token}` 链接，且最终解析为 `bitable`。
- 用户要把旧的 Base 聚合式写法改成当前原子命令写法，例如把旧 `+table / +field / +record / +view / +history / +workspace` 改写成当前命令。

以下场景不应使用本 skill：

- 用户只是做认证、初始化配置、切换 `--as user/bot`、处理 scope。此时先读 `../lark-shared/SKILL.md`。
- 用户只是泛化地讨论“数据分析 / 字段设计”，但并不在 Base 场景中。不要因为提到“统计 / 公式 / lookup”就误触发。

### 1.2 前置约束

1. 先阅读 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)。
2. Base 业务命令仅使用 `lark-cli base +...` 形式的 shortcut 命令；如果输入是 Wiki 链接，可先调用 `lark-cli wiki spaces get_node` 解析真实 token。
3. 定位到命令后，先读该命令对应的 reference，再执行命令。
4. 如果用户要把本地 Excel / CSV 导入成 Base / 多维表格 / bitable，第一步不是 `base`，而是 `lark-cli drive +import --type bitable`；导入完成后再回到 `lark-cli base +...` 做表内操作。
5. 不要在 Base 场景改走 `lark-cli api /open-apis/bitable/v1/...`。

## 2. 模块与命令导航

本章按“先选模块，再选命令”的方式组织。先判断用户目标属于哪个大模块，再进入对应子模块，按要求阅读 reference 后执行命令。

### 2.1 模块地图

| 大模块 | 处理什么问题 | 包含的小模块 / 能力 |
|------|-------------|-------------------|
| Base 模块 | 管理 Base 本体，或从链接进入 Base 场景 | `base-create / base-get / base-copy`，Base / Wiki 链接解析 |
| 表与数据模块 | 管理 Base 内部结构与日常数据操作 | `table / field / record / view` |
| 公式 / Lookup 模块 | 处理派生字段、条件判断、跨表计算、固定查找引用 | `formula / lookup` 字段创建与更新 |
| 数据分析模块 | 做一次性筛选、分组、聚合分析 | `data-query` |
| Workflow 模块 | 管理自动化流程 | `workflow-list / get / create / update / enable / disable` |
| Dashboard 模块 | 管理仪表盘和图表组件 | `dashboard-* / dashboard-block-*` |
| 表单模块 | 管理表单和表单题目 | `form-* / form-questions-*` |
| 权限与角色模块 | 管理高级权限和自定义角色 | `advperm-* / role-*` |

### 2.2 Base 模块

用于管理 Base 本体，或从用户给出的链接进入后续 Base 操作。  
模块索引：[`references/lark-base-workspace.md`](references/lark-base-workspace.md)

| 命令 | 用途 / 何时使用 | 必读 reference | 路由提醒 |
|------|------------------|----------------|----------|
| `+base-create` | 创建新的 Base | [`lark-base-base-create.md`](references/lark-base-base-create.md)、[`lark-base-workspace.md`](references/lark-base-workspace.md) | 写入操作；执行前先读 reference；`--folder-token`、`--time-zone` 都是可选项 |
| `+base-get` | 获取 Base 信息 | [`lark-base-base-get.md`](references/lark-base-base-get.md)、[`lark-base-workspace.md`](references/lark-base-workspace.md) | 适合确认 Base 本体信息，不替代表/字段结构读取 |
| `+base-copy` | 复制已有 Base | [`lark-base-base-copy.md`](references/lark-base-base-copy.md)、[`lark-base-workspace.md`](references/lark-base-workspace.md) | 写入操作；执行前先读 reference；复制成功后应主动返回新 Base 标识信息 |

### 2.3 表与数据模块

这是最常用的大模块，包含 `table / field / record / view` 四类子模块。  
补充示例：[`references/examples.md`](references/examples.md)，适合需要串联 table / record / view 完整操作链路时再读。

#### 2.3.1 Table 子模块

子模块索引：[`references/lark-base-table.md`](references/lark-base-table.md)

| 命令 | 用途 / 何时使用 | 必读 reference | 路由提醒 |
|------|------------------|----------------|----------|
| `+table-list / +table-get` | 列出数据表，或获取单个表详情 | [`lark-base-table-list.md`](references/lark-base-table-list.md)、[`lark-base-table-get.md`](references/lark-base-table-get.md) | `+table-list` 只能串行执行；`+table-get` 适合删除/修改前确认目标 |
| `+table-create / +table-update / +table-delete` | 创建、更新或删除数据表 | [`lark-base-table-create.md`](references/lark-base-table-create.md)、[`lark-base-table-update.md`](references/lark-base-table-update.md)、[`lark-base-table-delete.md`](references/lark-base-table-delete.md) | 创建适合一次性建表；更新前先确认目标表；删除时用户已明确目标可直接执行并带 `--yes` |

#### 2.3.2 Field 子模块

普通字段管理走这里；如果字段类型是 `formula` 或 `lookup`，转到下方“公式 / Lookup 模块”。  
子模块索引：[`references/lark-base-field.md`](references/lark-base-field.md)

| 命令 | 用途 / 何时使用 | 必读 reference | 路由提醒 |
|------|------------------|----------------|----------|
| `+field-list / +field-get` | 列出字段结构，或获取单个字段详情 | [`lark-base-field-list.md`](references/lark-base-field-list.md)、[`lark-base-field-get.md`](references/lark-base-field-get.md) | 写记录、写字段、做分析前常先读 `+field-list`；`+field-list` 只能串行执行；`+field-get` 适合删除/更新前确认目标 |
| `+field-create / +field-update / +field-delete` | 创建、更新或删除普通字段 | [`lark-base-field-create.md`](references/lark-base-field-create.md)、[`lark-base-field-update.md`](references/lark-base-field-update.md)、[`lark-base-field-delete.md`](references/lark-base-field-delete.md)、[`lark-base-shortcut-field-properties.md`](references/lark-base-shortcut-field-properties.md) | 写字段前先看字段属性规范；如果类型是 `formula / lookup`，先转去读对应 guide；删除时用户已明确目标可直接执行并带 `--yes` |
| `+field-search-options` | 查询字段可选项 | [`lark-base-field-search-options.md`](references/lark-base-field-search-options.md) | 适合单选/多选等选项型字段 |

#### 2.3.3 Record 子模块

子模块索引：[`references/lark-base-record.md`](references/lark-base-record.md)、[`references/lark-base-history.md`](references/lark-base-history.md)

| 命令 | 用途 / 何时使用 | 必读 reference | 路由提醒 |
|------|------------------|----------------|----------|
| `+record-search / +record-list / +record-get` | 按关键词检索记录、读取记录明细 / 分页导出，或获取单条记录详情 | [`lark-base-record-search.md`](references/lark-base-record-search.md)、[`lark-base-record-list.md`](references/lark-base-record-list.md)、[`lark-base-record-get.md`](references/lark-base-record-get.md) | 默认优先 `+record-list`；仅当用户提供明确搜索关键词时使用 `+record-search`；取数不用来做聚合分析；`--limit` 最大 `200`；仅在用户明确需要时继续翻页；`+record-list` 只能串行执行 |
| `+record-upsert / +record-batch-create / +record-batch-update` | 创建、更新或批量写入记录 | [`lark-base-record-upsert.md`](references/lark-base-record-upsert.md)、[`lark-base-record-batch-create.md`](references/lark-base-record-batch-create.md)、[`lark-base-record-batch-update.md`](references/lark-base-record-batch-update.md)、[`lark-base-shortcut-record-value.md`](references/lark-base-shortcut-record-value.md) | 写前先 `+field-list`；只写存储字段；批量单次建议不超过 `500` 条；附件不要走这里 |
| `+record-upload-attachment` | 给已有记录上传附件 | [`lark-base-record-upload-attachment.md`](references/lark-base-record-upload-attachment.md) | 附件上传专用链路，不要用 `+record-upsert` / `+record-batch-*` 伪造附件值 |
| `lark-cli docs +media-download` | 下载 Base 附件文件到本地 | [`../lark-doc/references/lark-doc-media-download.md`](../lark-doc/references/lark-doc-media-download.md) | Base 附件的 `file_token` 从 `+record-get` 返回的附件字段数组里取；**不要用 `lark-cli drive +download`**（对 Base 附件返回 403） |
| `+record-delete / +record-history-list` | 删除记录，或查询某条记录的变更历史 | [`lark-base-record-delete.md`](references/lark-base-record-delete.md)、[`lark-base-record-history-list.md`](references/lark-base-record-history-list.md) | 删除时用户已明确目标可直接执行并带 `--yes`；历史查询按 `table-id + record-id`，不支持整表扫描；`+record-history-list` 只能串行执行 |

#### 2.3.4 View 子模块

子模块索引：[`references/lark-base-view.md`](references/lark-base-view.md)

| 命令 | 用途 / 何时使用 | 必读 reference | 路由提醒 |
|------|------------------|----------------|----------|
| `+view-list / +view-get` | 列出视图，或获取视图详情 | [`lark-base-view-list.md`](references/lark-base-view-list.md)、[`lark-base-view-get.md`](references/lark-base-view-get.md) | `+view-list` 只能串行执行；`+view-get` 适合查看已有视图配置 |
| `+view-create / +view-delete / +view-rename` | 创建、删除或重命名视图 | [`lark-base-view-create.md`](references/lark-base-view-create.md)、[`lark-base-view-delete.md`](references/lark-base-view-delete.md)、[`lark-base-view-rename.md`](references/lark-base-view-rename.md) | 创建前先确认表和视图类型；删除前先确认目标；用户已明确新名字时可直接重命名 |
| `+view-get-filter / +view-set-filter` | 读取或配置筛选条件 | [`lark-base-view-get-filter.md`](references/lark-base-view-get-filter.md)、[`lark-base-view-set-filter.md`](references/lark-base-view-set-filter.md)、[`lark-base-record-list.md`](references/lark-base-record-list.md) | 常与 `+record-list` 组合，用于按视图筛选读取 |
| `+view-get-sort / +view-set-sort` | 读取或配置排序 | [`lark-base-view-get-sort.md`](references/lark-base-view-get-sort.md)、[`lark-base-view-set-sort.md`](references/lark-base-view-set-sort.md) | 字段名必须来自真实结构 |
| `+view-get-group / +view-set-group` | 读取或配置分组 | [`lark-base-view-get-group.md`](references/lark-base-view-get-group.md)、[`lark-base-view-set-group.md`](references/lark-base-view-set-group.md) | 字段名必须来自真实结构 |
| `+view-get-visible-fields / +view-set-visible-fields` | 读取或配置视图可见字段 | [`lark-base-view-get-visible-fields.md`](references/lark-base-view-get-visible-fields.md)、[`lark-base-view-set-visible-fields.md`](references/lark-base-view-set-visible-fields.md) | 用于控制视图中的字段顺序与可见性；字段名必须来自真实结构 |
| `+view-get-card / +view-set-card` | 读取或配置卡片视图 | [`lark-base-view-get-card.md`](references/lark-base-view-get-card.md)、[`lark-base-view-set-card.md`](references/lark-base-view-set-card.md) | 适合卡片展示场景 |
| `+view-get-timebar / +view-set-timebar` | 读取或配置时间轴视图 | [`lark-base-view-get-timebar.md`](references/lark-base-view-get-timebar.md)、[`lark-base-view-set-timebar.md`](references/lark-base-view-set-timebar.md) | 适合时间线展示场景 |

### 2.4 公式 / Lookup 模块

只要用户诉求涉及派生指标、条件判断、文本处理、日期差、跨表计算、跨表筛选后取值，都要先判断是否进入本模块。

默认优先考虑 `formula`：适合常规计算、条件判断、文本处理、日期差、跨表聚合，以及需要长期显示在表里的派生结果。  
只有当用户明确要求 `lookup`，或场景天然符合 `from / select / where / aggregate` 这种固定查找建模时，再使用 `lookup`。

| 命令 | 用途 / 何时使用 | 必读 reference | 路由提醒 |
|------|------------------|----------------|----------|
| `+field-create`（`type=formula`） | 创建公式字段 | [`formula-field-guide.md`](references/formula-field-guide.md)、[`lark-base-field-create.md`](references/lark-base-field-create.md)、[`lark-base-shortcut-field-properties.md`](references/lark-base-shortcut-field-properties.md) | 没读 guide 前不要直接创建 |
| `+field-update`（`type=formula`） | 更新公式字段 | [`formula-field-guide.md`](references/formula-field-guide.md)、[`lark-base-field-update.md`](references/lark-base-field-update.md)、[`lark-base-shortcut-field-properties.md`](references/lark-base-shortcut-field-properties.md) | 先拿当前表结构 |
| `+field-create`（`type=lookup`） | 创建 lookup 字段 | [`lookup-field-guide.md`](references/lookup-field-guide.md)、[`lark-base-field-create.md`](references/lark-base-field-create.md)、[`lark-base-shortcut-field-properties.md`](references/lark-base-shortcut-field-properties.md) | 没读 guide 前不要直接创建 |
| `+field-update`（`type=lookup`） | 更新 lookup 字段 | [`lookup-field-guide.md`](references/lookup-field-guide.md)、[`lark-base-field-update.md`](references/lark-base-field-update.md)、[`lark-base-shortcut-field-properties.md`](references/lark-base-shortcut-field-properties.md) | 跨表时还要拿目标表结构 |

### 2.5 数据分析模块

用于一次性分析和临时聚合查询。用户要的是“这次算出来的结果”，而不是把结果沉淀成字段时，优先进入本模块。

进入本模块前先确认几件事：

- `+data-query` 只做聚合查询（分组、过滤、排序、聚合计算），不用于列出原始记录或逐条明细。
- 调用者必须是目标多维表格的管理员，拥有目标多维表格的 FA（Full Access / 完全访问权限），否则会返回权限错误。
- `+data-query` 只支持白名单字段类型；`formula`、`lookup`、附件、系统字段、关联等字段不能用于 `dimensions / measures / filters / sort`。

| 命令 | 用途 / 何时使用 | 必读 reference | 路由提醒 |
|------|------------------|----------------|----------|
| `+data-query` | 做分组统计、SUM / AVG / COUNT / MAX / MIN、条件筛选后的聚合分析 | [`lark-base-data-query.md`](references/lark-base-data-query.md) | 字段名必须精确匹配真实字段名；不要用 `+record-list` / `+record-search` 拉全量再手算；`+data-query` 不返回原始记录；使用前先确认权限和字段类型是否受支持 |

### 2.6 Workflow 模块

这是高约束模块。执行任何 workflow 命令前，都必须先读对应命令文档和 schema。  
模块索引：[`references/lark-base-workflow.md`](references/lark-base-workflow.md)

| 命令 | 用途 / 何时使用 | 必读 reference | 路由提醒 |
|------|------------------|----------------|----------|
| `+workflow-list / +workflow-get` | 列出 workflow，或获取完整 workflow 结构 | [`lark-base-workflow-list.md`](references/lark-base-workflow-list.md)、[`lark-base-workflow-get.md`](references/lark-base-workflow-get.md)、[`lark-base-workflow-schema.md`](references/lark-base-workflow-schema.md) | `+workflow-list` 只返回摘要且只能串行执行；需要完整结构时用 `+workflow-get` |
| `+workflow-create / +workflow-update` | 创建或更新 workflow | [`lark-base-workflow-create.md`](references/lark-base-workflow-create.md)、[`lark-base-workflow-update.md`](references/lark-base-workflow-update.md)、[`lark-base-workflow-schema.md`](references/lark-base-workflow-schema.md) | 先读 schema；禁止凭自然语言猜 `type`；先确认真实表名和字段名 |
| `+workflow-enable / +workflow-disable` | 启用或停用 workflow | [`lark-base-workflow-enable.md`](references/lark-base-workflow-enable.md)、[`lark-base-workflow-disable.md`](references/lark-base-workflow-disable.md)、[`lark-base-workflow-schema.md`](references/lark-base-workflow-schema.md) | 启用或停用前先确认目标 workflow；`workflow_id` 与 `table_id` 需按前缀区分 |

### 2.7 Dashboard 模块

当用户提到“仪表盘、dashboard、数据看板、图表、可视化、block、组件、添加组件、创建图表”等关键词时，进入本模块，并先阅读 [`lark-base-dashboard.md`](references/lark-base-dashboard.md)。

| 命令 | 用途 / 何时使用 | 必读 reference | 路由提醒 |
|------|------------------|----------------|----------|
| `+dashboard-list / +dashboard-get` | 列出仪表盘，或获取仪表盘详情 | [`lark-base-dashboard-list.md`](references/lark-base-dashboard-list.md)、[`lark-base-dashboard-get.md`](references/lark-base-dashboard-get.md)、[`lark-base-dashboard.md`](references/lark-base-dashboard.md) | 进入仪表盘语义后先读 guide；`+dashboard-list` 只能串行执行 |
| `+dashboard-create / +dashboard-update / +dashboard-delete` | 创建、更新或删除仪表盘 | [`lark-base-dashboard-create.md`](references/lark-base-dashboard-create.md)、[`lark-base-dashboard-update.md`](references/lark-base-dashboard-update.md)、[`lark-base-dashboard-delete.md`](references/lark-base-dashboard-delete.md)、[`lark-base-dashboard.md`](references/lark-base-dashboard.md) | 创建前先明确看板目标和展示场景；更新前先读取当前配置；删除前先确认目标 |
| `+dashboard-block-list / +dashboard-block-get` | 列出图表组件，或获取单个 block 详情 | [`lark-base-dashboard-block-list.md`](references/lark-base-dashboard-block-list.md)、[`lark-base-dashboard-block-get.md`](references/lark-base-dashboard-block-get.md)、[`lark-base-dashboard.md`](references/lark-base-dashboard.md)、[`dashboard-block-data-config.md`](references/dashboard-block-data-config.md) | `+dashboard-block-list` 只能串行执行；查看配置细节时读 block config 文档 |
| `+dashboard-block-create / +dashboard-block-update / +dashboard-block-delete` | 创建、更新或删除图表组件 | [`lark-base-dashboard-block-create.md`](references/lark-base-dashboard-block-create.md)、[`lark-base-dashboard-block-update.md`](references/lark-base-dashboard-block-update.md)、[`lark-base-dashboard-block-delete.md`](references/lark-base-dashboard-block-delete.md)、[`lark-base-dashboard.md`](references/lark-base-dashboard.md)、[`dashboard-block-data-config.md`](references/dashboard-block-data-config.md) | 涉及 `data_config`、图表类型、filter 时要读 block config 文档；删除前先确认目标 |

### 2.8 表单模块

用于管理表单本体和表单题目。  
模块索引：[`references/lark-base-form.md`](references/lark-base-form.md)、[`references/lark-base-form-questions.md`](references/lark-base-form-questions.md)  
表单问题相关操作依赖 `form-id`；具体获取方式见 `form-list` 和 `form-create` 的 reference。

| 命令 | 用途 / 何时使用 | 必读 reference | 路由提醒 |
|------|------------------|----------------|----------|
| `+form-list / +form-get` | 列出表单，或获取单个表单 | [`lark-base-form-list.md`](references/lark-base-form-list.md)、[`lark-base-form-get.md`](references/lark-base-form-get.md) | `+form-list` 可用来获取 `form-id`；`+form-get` 适合查看已有表单配置 |
| `+form-create / +form-update / +form-delete` | 创建、更新或删除表单 | [`lark-base-form-create.md`](references/lark-base-form-create.md)、[`lark-base-form-update.md`](references/lark-base-form-update.md)、[`lark-base-form-delete.md`](references/lark-base-form-delete.md) | 创建后可继续进入表单问题相关操作；更新或删除前先确认目标表单 |
| `+form-questions-list` | 列出表单题目 | [`lark-base-form-questions-list.md`](references/lark-base-form-questions-list.md) | 适合查看已有题目结构 |
| `+form-questions-create / +form-questions-update / +form-questions-delete` | 创建、更新或删除题目 | [`lark-base-form-questions-create.md`](references/lark-base-form-questions-create.md)、[`lark-base-form-questions-update.md`](references/lark-base-form-questions-update.md)、[`lark-base-form-questions-delete.md`](references/lark-base-form-questions-delete.md) | 先确认 `form-id`；更新或删除前先确认题目目标 |

### 2.9 权限与角色模块

用于启用高级权限，以及管理 Base 自定义角色。  
涉及 `+advperm-enable / +advperm-disable / +role-*` 时，操作用户必须为 Base 管理员，否则会返回权限错误。

| 命令 | 用途 / 何时使用 | 必读 reference | 路由提醒 |
|------|------------------|----------------|----------|
| `+advperm-enable / +advperm-disable` | 启用或停用高级权限 | [`lark-base-advperm-enable.md`](references/lark-base-advperm-enable.md)、[`lark-base-advperm-disable.md`](references/lark-base-advperm-disable.md) | 管理角色前必须先启用；停用是高风险操作，会使已有自定义角色失效 |
| `+role-list / +role-get` | 列出角色，或获取角色详情 | [`lark-base-role-list.md`](references/lark-base-role-list.md)、[`lark-base-role-get.md`](references/lark-base-role-get.md)、[`role-config.md`](references/role-config.md) | `+role-list` 只能串行执行；`+role-get` 适合查看完整权限配置 |
| `+role-create / +role-update / +role-delete` | 创建、更新或删除角色 | [`lark-base-role-create.md`](references/lark-base-role-create.md)、[`lark-base-role-update.md`](references/lark-base-role-update.md)、[`lark-base-role-delete.md`](references/lark-base-role-delete.md)、[`role-config.md`](references/role-config.md) | `+role-create` 仅支持 `custom_role`；`+role-update` 采用 Delta Merge，`role_name` 和 `role_type` 即使不改也必须传当前值；`+role-delete` 不可逆 |

## 3. 多维表格通用知识

飞书多维表格英文名是 `Base`，曾用名 `Bitable`；因此旧文档、返回字段、参数名或错误信息里出现 `bitable` 多属历史兼容，不代表应改用另一套命令体系。

### 3.1 字段分类与可写性

| 字段类型 | 含义 | 能否直接作为 `+record-upsert / +record-batch-create / +record-batch-update` 写入目标 | 说明 |
|----------|------|-----------------------------------------------------------|------|
| 存储字段 | 真实存用户输入的数据 | 可以 | 常见如文本、数字、日期、单选、多选、人员、关联 |
| 附件字段 | 存储文件附件 | 不应直接按普通字段写 | 上传附件走 `+record-upload-attachment`；下载附件走 `lark-cli docs +media-download` |
| 系统字段 | 平台自动维护 | 不可以 | 常见如创建时间、更新时间、创建人、修改人、自动编号 |
| `formula` 字段 | 通过表达式计算 | 不可以 | 只读字段 |
| `lookup` 字段 | 通过跨表规则查找引用 | 不可以 | 只读字段 |

### 3.2 任务选路心智模型

| 用户诉求 | 优先方案 | 不要误走 |
|---------|----------|----------|
| 一次性分析 / 临时统计 | `+data-query` | 不要用 `+record-list` / `+record-search` 拉全量后手算 |
| 要把结果长期显示在表里 | `formula` 字段 | 不要只给一次性手工分析结果 |
| 用户明确要求 lookup，或天然是固定查找配置 | `lookup` 字段 | 不要默认先上 lookup；先判断 formula 是否更合适 |
| 读取原始记录明细 / 关键词检索 / 导出 | `+record-search / +record-list / +record-get` | 不要拿 `+data-query` 当取数命令 |
| 上传附件到记录 | `+record-upload-attachment` | 不要用 `+record-upsert` / `+record-batch-*` 伪造附件值 |
| 下载记录里的附件文件 | `lark-cli docs +media-download --token <file_token> --output <path>` | `file_token` 从 `+record-get` 返回的附件字段里取；用法见 [`../lark-doc/references/lark-doc-media-download.md`](../lark-doc/references/lark-doc-media-download.md) |
| 基于视图做筛选读取 | `+view-set-filter` + `+record-list` | 不要跳过视图筛选直接猜条件 |
| 本地 Excel / CSV 导入为 Base | `lark-cli drive +import --type bitable` | 不要误走 `+base-create`、`+table-create` 或 `+record-upsert` |

### 3.3 表名、字段名与表达式引用

1. 表名、字段名必须精确匹配真实返回，来源应是 `+table-list / +table-get / +field-list`。
2. 不要凭自然语言猜名称，不要自行改写用户口述中的表名、字段名。
3. `formula / lookup / data-query / workflow` 中出现的名称同样必须精确匹配；表达式引用、where 条件、DSL 字段名、workflow 配置都遵守同一规则。
4. 跨表场景必须额外读取目标表结构，不能只看当前表。

### 3.4 Token 与链接

这是高优先级章节。只要用户输入里出现链接、token，或报错涉及 `baseToken` / `wiki_token` / `obj_token`，都应优先回到这里检查。

| 输入类型 | 正确处理方式 | 说明 |
|---------|--------------|------|
| 直接 Base 链接 `/base/{token}` | 直接提取 token 作为 `--base-token` | 不要把完整 URL 直接作为 `--base-token` |
| Wiki 链接 `/wiki/{token}` | 先 `wiki.spaces.get_node`，再取 `node.obj_token` | 不要把 `wiki_token` 直接当 `--base-token` |
| URL 中的 `?table={id}` | 先按前缀判断对象类型 | `tbl` 开头表示数据表 `table-id`，可作为 `--table-id`；`blk` 开头表示仪表盘 `dashboard-ID`；`wkf` 开头表示 `workflow-ID`；`ldx` 开头表示内嵌文档，不要一律当成 `--table-id` |
| URL 中的 `?view={id}` | 提取为 `--view-id` | 适合直接定位视图 |

| `lark-cli wiki spaces get_node` 返回的 `obj_type` | 后续路线 | 说明 |
|-----------------------------------------------|----------|------|
| `bitable` | 优先走 `lark-cli base +...` | 如果 shortcut 不覆盖，再用 `lark-cli base <resource> <method>`；不要改走 `lark-cli api /open-apis/bitable/v1/...` |
| `docx` | 转到文档 / Drive 相关 skill | 不继续使用本 skill 的 Base 命令 |
| `sheet` | 转到 Sheets 相关 skill | 不继续使用本 skill 的 Base 命令 |
| `slides` | 转到 Drive 相关 skill | 不继续使用本 skill 的 Base 命令 |
| `mindnote` | 转到 Drive 相关 skill | 不继续使用本 skill 的 Base 命令 |

### 3.5 执行身份与人员字段

- 人员字段 / 用户字段：注意 `user_id_type` 与执行身份（user / bot）差异。
- bot 身份：bot 看不到用户私有资源；行为以应用身份执行。
- user 身份：依赖用户授权和 scope；更适合操作用户资源。

## 4. 执行规则

### 4.1 标准执行顺序

1. 先判断任务属于哪个模块，选对命令族。
2. 如果用户给了链接，先解析 token，不要把 wiki token、完整 URL 或其他对象 ID 误当成 `base_token`。
3. 先拿结构，再写命令，避免猜表名、字段名、表达式引用。
4. 定位到命令后，先读对应 reference，再执行命令。
5. 执行命令，并按返回结果判断下一步。
6. 回复时返回关键结果和后续可继续操作的信息，方便 agent 链式执行下一步。

### 4.2 不可违反规则

1. 先拿结构，再写命令；至少先拿当前表结构，跨表时还要拿目标表结构。
2. 不要猜表名、字段名、表达式引用，一律以真实返回为准。
3. 只使用原子命令；不要回退到旧的聚合式 `+table / +field / +record / +view / +history / +workspace`。
4. 写记录前先读字段结构；先 `+field-list`，再按字段类型构造写入值。
5. 写字段前先看字段属性规范；先读 `lark-base-shortcut-field-properties.md`，再构造 `+field-create / +field-update` 的 JSON。
6. 只写可写字段；系统字段、附件字段、`formula`、`lookup` 默认不作为普通记录写入目标。
7. 聚合分析与取数分流；统计走 `+data-query`，关键词检索走 `+record-search`，明细走 `+record-list / +record-get`。
8. 筛选查询按视图能力执行；先用 `+view-set-filter` 配置筛选，再结合 `+record-list` 读取。
9. Base 场景不要改走裸 API，不要切去 `lark-cli api /open-apis/bitable/v1/...`。
10. 统一使用 `--base-token`，不使用旧 `--app-token`。
11. workflow 场景先读 schema，不要凭自然语言猜 `type`。
12. dashboard 场景先读 guide；提到图表、看板、block 就先进入 dashboard 模块。
13. formula / lookup 场景先读 guide；没读 guide 前不要直接创建或更新。

### 4.3 并发、分页与批量限制

- `+table-list / +field-list / +record-list / +view-list / +record-history-list / +role-list / +dashboard-list / +dashboard-block-list / +workflow-list` 禁止并发调用，只能串行执行。
- `+record-list` 分页时，`--limit` 最大 `200`；先拉首批并检查 `has_more`，只有用户明确需要更多数据时再继续翻页。
- 批量写入时，单批建议不超过 `500` 条。
- 连续写入同一表时，建议串行写入，批次间延迟 `0.5–1` 秒。

### 4.4 确认与回复规则

- 视图重命名时，用户已明确“把哪个视图改成什么名字”时，`+view-rename` 直接执行即可。
- 删除记录 / 字段 / 表时，如果用户已经明确说要删除，且目标明确，`+record-delete / +field-delete / +table-delete` 可直接执行，并带 `--yes`。
- 删除目标仍有歧义时，先用 `+record-get / +field-get / +table-get` 或相应 list 命令确认。
- `+base-create / +base-copy` 成功后，回复中必须主动返回新 Base 的标识信息；若结果带可访问链接，也应一并返回。
- 若 Base 由 bot 身份创建且当前 CLI 存在可用 user 身份，优先继续补授当前 user 为 `full_access`；owner 转移必须单独确认，禁止擅自执行。

## 5. 常见错误与恢复

| 错误 / 现象 | 含义 | 恢复动作 |
|-------------|------|----------|
| `1254064` | 日期格式错误 | 用毫秒时间戳，非字符串 / 秒级 |
| `1254068` | 超链接格式错误 | 用 `{text, link}` 对象 |
| `1254066` | 人员字段错误 | 用 `[{id:"ou_xxx"}]`，并确认 `user_id_type` |
| `1254045` | 字段名不存在 | 检查字段名（含空格、大小写） |
| `1254015` | 字段值类型不匹配 | 先 `+field-list`，再按类型构造 |
| `param baseToken is invalid` / `base_token invalid` | 把 wiki token、workspace token 或其他 token 当成了 `base_token` | 如果输入来自 `/wiki/...`，先用 `lark-cli wiki spaces get_node` 取真实 `obj_token`；当 `obj_type=bitable` 时，用 `node.obj_token` 作为 `--base-token` 重试，不要改走 `bitable/v1` |
| `not found` 且用户给的是 wiki 链接 | 常见于把 wiki token 当成 base token | 优先回退检查 wiki 解析，而不是改走 `bitable/v1` |
| formula / lookup 创建失败 | 指南未读或结构不合法 | 先读 `formula-field-guide.md` / `lookup-field-guide.md`，再按 guide 重建请求 |
| 系统字段 / 公式字段写入失败 | 只读字段被当成可写字段 | 改为写存储字段，计算结果交给 formula / lookup / 系统字段自动产出 |
| `1254104` | 批量超 500 条 | 分批调用 |
| `1254291` | 并发写冲突 | 串行写入 + 批次间延迟 |

## 6. 参考文档

- [lark-base-shortcut-field-properties.md](references/lark-base-shortcut-field-properties.md) — `+field-create/+field-update` 调用前必看，各类型 field JSON 规范
- [role-config.md](references/role-config.md) — 角色权限配置详解
- [lark-base-shortcut-record-value.md](references/lark-base-shortcut-record-value.md) — record 写入（`+record-upsert / +record-batch-create / +record-batch-update`）调用前必看，各类型 record JSON 规范
- [lark-base-record-batch-create.md](references/lark-base-record-batch-create.md) — `+record-batch-create` 用法与 `--json` 结构
- [lark-base-record-batch-update.md](references/lark-base-record-batch-update.md) — `+record-batch-update` 用法与 `--json` 结构
- [formula-field-guide.md](references/formula-field-guide.md) — formula 字段写法、函数约束、CurrentValue 规则、跨表计算模式
- [lookup-field-guide.md](references/lookup-field-guide.md) — lookup 字段配置规则、where/aggregate 约束、与 formula 的取舍
- [lark-base-view-set-filter.md](references/lark-base-view-set-filter.md) — 视图筛选配置
- [lark-base-record-list.md](references/lark-base-record-list.md) — 记录列表读取与分页
- [lark-base-record-search.md](references/lark-base-record-search.md) — 关键词搜索记录
- [lark-base-advperm-enable.md](references/lark-base-advperm-enable.md) — `+advperm-enable` 启用高级权限
- [lark-base-advperm-disable.md](references/lark-base-advperm-disable.md) — `+advperm-disable` 停用高级权限
- [lark-base-role-list.md](references/lark-base-role-list.md) — `+role-list` 列出角色
- [lark-base-role-get.md](references/lark-base-role-get.md) — `+role-get` 获取角色详情
- [lark-base-role-create.md](references/lark-base-role-create.md) — `+role-create` 创建角色
- [lark-base-role-update.md](references/lark-base-role-update.md) — `+role-update` 更新角色
- [lark-base-role-delete.md](references/lark-base-role-delete.md) — `+role-delete` 删除角色
- [lark-base-dashboard.md](references/lark-base-dashboard.md) — dashboard 模块工作流指引
- [dashboard-block-data-config.md](references/dashboard-block-data-config.md) — Block `data_config` 结构、图表类型、filter 规则
- [lark-base-workflow.md](references/lark-base-workflow.md) — workflow 命令索引
- [lark-base-workflow-schema.md](references/lark-base-workflow-schema.md) — `+workflow-create/+workflow-update` JSON body 结构详解
- [lark-base-data-query.md](references/lark-base-data-query.md) — `+data-query` 聚合分析，含 DSL 结构、支持字段类型、聚合函数
- [examples.md](references/examples.md) — 完整操作示例

## 7. 命令分组

> **执行前必做：** 从下表定位到命令后，务必先阅读对应命令的 reference 文档，再调用命令。

| 命令分组 | 说明 |
|----------|------|
| [`table commands`](references/lark-base-table.md) | `+table-list / +table-get / +table-create / +table-update / +table-delete` |
| [`field commands`](references/lark-base-field.md) | `+field-list / +field-get / +field-create / +field-update / +field-delete / +field-search-options` |
| [`record commands`](references/lark-base-record.md) | `+record-search / +record-list / +record-get / +record-upsert / +record-batch-create / +record-batch-update / +record-upload-attachment / +record-delete` |
| [`view commands`](references/lark-base-view.md) | `+view-list / +view-get / +view-create / +view-delete / +view-get-* / +view-set-* / +view-rename` |
| [`data-query commands`](references/lark-base-data-query.md) | `+data-query` |
| [`history commands`](references/lark-base-history.md) | `+record-history-list` |
| [`base / workspace commands`](references/lark-base-workspace.md) | `+base-create / +base-get / +base-copy` |
| [`advperm commands`](references/lark-base-advperm-enable.md) | `+advperm-enable / +advperm-disable` |
| [`role commands`](references/lark-base-role-list.md) | `+role-list / +role-get / +role-create / +role-update / +role-delete` |
| [`form commands`](references/lark-base-form-create.md) | `+form-list / +form-get / +form-create / +form-update / +form-delete` |
| [`form questions commands`](references/lark-base-form-questions-create.md) | `+form-questions-list / +form-questions-create / +form-questions-update / +form-questions-delete` |
| [`workflow commands`](references/lark-base-workflow.md) | `+workflow-list / +workflow-get / +workflow-create / +workflow-update / +workflow-enable / +workflow-disable` |
| [`dashboard / dashboard-block commands`](references/lark-base-dashboard.md) | `+dashboard-list / +dashboard-get / +dashboard-create / +dashboard-update / +dashboard-delete / +dashboard-arrange / +dashboard-block-list / +dashboard-block-get / +dashboard-block-create / +dashboard-block-update / +dashboard-block-delete` |
