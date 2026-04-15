# dashboard block data_config 参考

Block 的 `data_config` 字段因 `type` 不同而变化。本文档描述所有共享结构。

## 支持的组件类型（`type` 枚举）

| type 值 | 说明 |
|---------|------|
| `column` | 柱状图 |
| `bar` | 条形图 |
| `line` | 折线图 |
| `pie` | 饼图 |
| `ring` | 环形图 |
| `area` | 面积图 |
| `combo` | 组合图 |
| `scatter` | 散点图 |
| `funnel` | 漏斗图 |
| `wordCloud` | 词云 |
| `radar` | 雷达图 |
| `statistics` | 指标卡 |
| `text` | 文本（支持 Markdown） |

## 字段类型与操作符速查（AI 决策用）

> `+field-list` 返回的 `type` 字段映射：number（数字）、text（文本）、select（单选）、multi_select（多选）、datetime（日期时间）、checkbox（复选框）、user（人员）

```
文本/电话/URL/邮箱:  is, isNot, contains, doesNotContain, isEmpty, isNotEmpty
数字/货币/进度:      is, isNot, isGreater, isGreaterEqual, isLess, isLessEqual, isEmpty, isNotEmpty
单选:               is, isNot, isEmpty, isNotEmpty
多选:               is, isNot, contains, doesNotContain, isEmpty, isNotEmpty
日期/时间:          is, isGreater, isGreaterEqual, isLess, isLessEqual, isEmpty, isNotEmpty
复选框:             is (value: true/false)
人员/创建人/修改人:  is, isNot, isEmpty, isNotEmpty
```

## data_config 通用结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `table_name` | string | 关联数据表名称 |
| `series` | `[{ "field_name": "xxx", "rollup": "SUM" }]` | 指标/Y 轴（与 `count_all` 二选一）。rollup 支持 `SUM` / `MAX` / `MIN` / `AVERAGE` |
| `count_all` | boolean | COUNTA 聚合，统计所有记录数（与 `series` 二选一） |
| `group_by` | `[{ "field_name": "xxx", "mode": "integrated", "sort": {...} }]` | X 轴分组维度。`mode` 必填，`sort` 可选，见下方说明 |
| `filter` | object | 筛选条件 |
| `filter.conjunction` | `"and"` / `"or"` | 筛选逻辑 |
| `filter.conditions` | `[{ "field_name", "operator", "value" }]` | 筛选条件数组，value 类型因字段类型而异（见下方 filter 格式规则） |

### text 类型特殊结构

`text` 类型组件用于展示富文本内容，**不需要数据源配置**（无 `table_name`、`series`、`group_by`、`filter`）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | string | **必填**。支持 Markdown 语法，详见下方说明 |

**支持的 Markdown 语法：**

| 语法 | 示例 | 效果 |
|------|------|------|
| 一级标题 | `# 标题` | 大标题 |
| 二级标题 | `## 标题` | 中标题 |
| 三级标题 | `### 标题` | 小标题 |
| 加粗 | `**文字**` | **文字** |
| 斜体 | `*文字*` | *文字* |
| 删除线 | `~~文字~~` | ~~文字~~ |
| 有序列表 | `1. 项目` | 1. 项目 |
| 无序列表 | `- 项目` | - 项目 |

> **注意**：以上未提及的 Markdown 语法（如链接、图片、代码块、表格等）均不支持。

## group_by 详细说明

### mode 枚举

| mode | 含义 | 适用场景 |
|------|------|----------|
| `integrated` | 聚合分组（默认） | 绝大部分场景，按字段值分组统计 |
| `enumerated` | 多值拆分统计 | 多选、人员等多值字段，将每个选项/人员拆开独立统计 |

> 多选、人员等多值字段默认用 `enumerated`；其他字段默认用 `integrated`。

### sort 排序

| sort.type | 含义 | 典型场景 |
|-----------|------|----------|
| `group` | 按横轴值排序 | 按月份升序、按品类名字母序 |
| `value` | 按纵轴值排序 | 按销售额从大到小 |
| `view` | 按数据源记录顺序 | 保持原表行序（不常用） |

`sort.order`：`asc`（升序）/ `desc`（降序）

示例 — 柱状图按销售额降序：

```json
{
  "table_name": "订单表",
  "series": [{ "field_name": "金额", "rollup": "SUM" }],
  "group_by": [{ "field_name": "类别", "mode": "integrated", "sort": {"type": "value", "order": "desc"} }]
}
```

## filter 格式规则

**基本结构：**

```json
{
  "filter": {
    "conjunction": "and",
    "conditions": [
      { "field_name": "字段名", "operator": "操作符", "value": "值" }
    ]
  }
}
```

**多条件示例（and/or）：**

```json
{
  "filter": {
    "conjunction": "and",
    "conditions": [
      { "field_name": "状态", "operator": "is", "value": "已完成" },
      { "field_name": "金额", "operator": "isGreater", "value": 1000 }
    ]
  }
}
```

**操作符：**

| 操作符 | 含义 | 是否需要 value |
|--------|------|---------------|
| `is` | 等于 | 是 |
| `isNot` | 不等于 | 是 |
| `contains` | 包含 | 是 |
| `doesNotContain` | 不包含 | 是 |
| `isEmpty` | 为空 | 否 |
| `isNotEmpty` | 不为空 | 否 |
| `isGreater` | 大于 | 是 |
| `isGreaterEqual` | 大于等于 | 是 |
| `isLess` | 小于 | 是 |
| `isLessEqual` | 小于等于 | 是 |

**各字段类型的 value 格式：**

| 字段类型 | value 类型 | 适用操作符 | 示例 |
|----------|-----------|-----------|------|
| 文本 / 电话 / URL | string | is, isNot, contains, doesNotContain, isEmpty, isNotEmpty | `{"field_name":"姓名","operator":"contains","value":"张"}` |
| 数字 | number | is, isNot, isGreater, isGreaterEqual, isLess, isLessEqual, isEmpty, isNotEmpty | `{"field_name":"金额","operator":"isGreater","value":0}` |
| 单选 | string（选项名） | is, isNot, isEmpty, isNotEmpty | `{"field_name":"状态","operator":"is","value":"已完成"}` |
| 多选 | string[]（选多个）/ string（选单个） | is, isNot, contains, doesNotContain, isEmpty, isNotEmpty | 多选传数组如 `["标签1","标签2"]`；单选传单个字符串 |
| 日期时间 / 创建时间 / 修改时间 | number（Unix 毫秒时间戳，13位） | is, isGreater, isGreaterEqual, isLess, isLessEqual, isEmpty, isNotEmpty | `{"field_name":"创建日期","operator":"isGreater","value":1704038400000}` |
| 复选框 | boolean | is | `{"field_name":"已审核","operator":"is","value":true}` |
| 人员 / 创建人 / 修改人 | string 或 string[]（用户 ID，格式 `ou_xxx`） | is, isNot, isEmpty, isNotEmpty | `{"field_name":"负责人","operator":"is","value":"ou_xxxxxxxxxxxxxxxx"}` |
| 所有类型（为空/不为空） | 不需要 value | isEmpty, isNotEmpty | `{"field_name":"备注","operator":"isEmpty"}` |

> `value` 类型为 `string | number | boolean | string[]`，需根据字段类型匹配正确格式

## 约束与本地校验

- 必填与互斥
  - 图表类型必填：`table_name`
  - text 类型必填：`text`
  - 互斥：`series` 与 `count_all` 二选一，且至少提供其一（仅图表类型）
  - text 类型**不支持**：`series`、`count_all`、`group_by`、`filter`
- 长度/结构
  - `group_by` 最多 2 个；每项 `field_name` 必填
  - `group_by[].sort.type` 取值 `group|value|view`；`order` 取值 `asc|desc`
- 规范化（CLI 自动处理）
  - `series[].rollup` 自动转成大写（如 `sum` → `SUM`）
  - `group_by[].sort.type/order` 自动转成小写
- 本地校验（可通过 `--no-validate` 跳过）
  - `+dashboard-block-create` 默认对 `data_config` 做轻量校验；失败会聚合错误并给出修复建议
  - `+dashboard-block-update` 不做强类型校验，由后端验证具体字段
  - 仅需传入合法 JSON；CLI 不会擅自改写你的业务含义

## 可复制模板

**按意图选择模板：**
- 比较不同类别数值 → 柱状图 / 条形图
- 看趋势变化 → 折线图 / 面积图
- 看占比分布 → 饼图 / 环形图 / 词云
- 多指标对比 → 组合图
- 看两变量关系 → 散点图
- 看流程转化 → 漏斗图
- 看多维度评分 → 雷达图
- 显示单个指标 → 指标卡（统计数字或记录数）

最小柱状图：

```json
{
  "table_name": "表名",
  "series": [{ "field_name": "数值字段", "rollup": "SUM" }],
  "group_by": [{ "field_name": "分组字段", "mode": "integrated" }]
}
```

最小饼图/环形图（按分类字段统计行数占比）：

```json
{
  "table_name": "表名",
  "count_all": true,
  "group_by": [{ "field_name": "分类字段", "mode": "integrated" }]
}
```

折线图（按月趋势）：

```json
{
  "table_name": "表名",
  "series": [{ "field_name": "金额", "rollup": "SUM" }],
  "group_by": [{ "field_name": "月份", "mode": "integrated", "sort": {"type":"group","order":"asc"} }]
}
```

条形图（横向柱状图）：

```json
{
  "table_name": "表名",
  "series": [{ "field_name": "数值字段", "rollup": "SUM" }],
  "group_by": [{ "field_name": "分组字段", "mode": "integrated" }]
}
```

面积图（趋势填充）：

```json
{
  "table_name": "表名",
  "series": [{ "field_name": "数值字段", "rollup": "SUM" }],
  "group_by": [{ "field_name": "时间字段", "mode": "integrated", "sort": {"type":"group","order":"asc"} }]
}
```

组合图（柱+线等多指标对比）：

```json
{
  "table_name": "表名",
  "series": [
    { "field_name": "指标1", "rollup": "SUM" },
    { "field_name": "指标2", "rollup": "SUM" }
  ],
  "group_by": [{ "field_name": "分类字段", "mode": "integrated" }]
}
```

散点图（两变量相关性）：

```json
{
  "table_name": "表名",
  "series": [{ "field_name": "Y轴字段（数值/指标）", "rollup": "SUM" }],
  "group_by": [{ "field_name": "X轴字段（分类/维度）", "mode": "integrated" }]
}
```

漏斗图（流程转化）：

```json
{
  "table_name": "表名",
  "series": [{ "field_name": "数值字段", "rollup": "SUM" }],
  "group_by": [{ "field_name": "阶段字段", "mode": "integrated" }]
}
```

词云（文本频率）：

```json
{
  "table_name": "表名",
  "count_all": true,
  "group_by": [{ "field_name": "文本字段", "mode": "integrated" }]
}
```

雷达图（多维度评分）：

```json
{
  "table_name": "表名",
  "series": [
    { "field_name": "维度1", "rollup": "SUM" },
    { "field_name": "维度2", "rollup": "SUM" },
    { "field_name": "维度3", "rollup": "SUM" }
  ],
  "group_by": [{ "field_name": "分类字段", "mode": "integrated" }]
}
```

指标卡（统计数字）：

```json
{
  "table_name": "数据表",
  "series": [{ "field_name": "数字", "rollup": "SUM" }]
}
```

指标卡（统计记录数）：

```json
{
  "table_name": "数据表",
  "count_all": true
}
```

文本组件（Markdown 富文本）：

```json
{
  "text": "# 🚀 一级标题\n这是一个 **加粗** *斜体* ~~删除线~~ 的示例。\n\n## 📌 二级标题\n1. 有序列表项 1\n2. 有序列表项 2\n\n### 📌 三级标题\n- 无序列表项 1\n- 无序列表项 2"
}
```

> **注意**：text 类型组件不需要 `table_name`、`series`、`group_by`、`filter` 等数据源相关字段。

## 常见错误与修复

- 同时存在 `series` 与 `count_all`
  - 现象：后端/本地校验报互斥错误
  - 修复：见「关键约束」章节的二选一规则
- 缺少 `table_name`
  - 现象：本地校验缺少必填字段
  - 修复：指定数据源表名（使用表名，非表 ID）
- `series[].rollup` 大小写/取值不合法
  - 现象：本地校验提示枚举不支持
  - 修复：改为 `SUM|MAX|MIN|AVERAGE` 中之一（不区分大小写，CLI 会统一为大写；计数请使用 `count_all:true`）
- `group_by` 超出 2 个或字段名为空
  - 修复：保留前 2 个，或补齐 `field_name`
- 排序枚举不合法
  - 修复：`group_by.sort.type` 仅能为 `group|value|view`；`order` 为 `asc|desc`
- filter 写法不规范
  - 修复：`conjunction` 取 `and|or`；`conditions[].operator` 必须在本页表格列举的范围内；除 `isEmpty/isNotEmpty` 外需提供 `value`

## 坑点

- **`count_all` 与 `series` 二选一** — 两者不能同时使用
- **filter `value` 类型因字段而异** — 文本/单选为 string，数字为 number，日期为毫秒时间戳，多选/人员可为 string[]，复选框为 boolean；`isEmpty`/`isNotEmpty` 不需要 value
- **`data_config` 结构随 `type` 变化** — 不同组件类型的字段不同，创建前务必确认类型对应的字段
- **表名用 name，不是 ID** — `table_name` 对应的是表名称（如「订单表」），不是 `table_id`
