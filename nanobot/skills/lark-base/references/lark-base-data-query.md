
# base +data-query

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

对多维表格数据进行聚合查询（分组、过滤、排序、聚合计算），基于以下语法的 JSON DSL：

## 限制

- **权限要求**：调用者必须是目标多维表格的管理员，它才能拥有目标多维表格的 **FA（Full Access / 完全访问权限）**，否则返回权限错误
- **支持的字段类型**（白名单，仅以下类型可用于 dimensions / measures / filters / sort）：
  文本、邮箱、条码、数字、进度、货币、评分、单选、多选、日期、复选框、人员、超链接
- **不支持的字段类型**：公式、查找引用、附件、时长、阶段、创建时间、修改时间、创建人、修改人、群组、电话号码、自动编号、地理位置、关联、双向关联 —— 不可用于 dimensions / measures / filters / sort，使用会返回校验错误

## 推荐命令

```bash
# 按字段分组计数
lark-cli base +data-query \
  --base-token MAGObxxxxx \
  --dsl '{
    "datasource": {"type": "table", "table": {"tableId": "tblxxxxxxxx"}},
    "dimensions": [{"field_name": "城市", "alias": "dim_city"}],
    "measures": [{"field_name": "城市", "aggregation": "count", "alias": "count"}],
    "shaper": {"format": "flat"}
  }'

# 带过滤条件 + 排序 + 限制条数
lark-cli base +data-query \
  --base-token MAGObxxxxx \
  --dsl '{
    "datasource": {"type": "table", "table": {"tableId": "tblxxxxxxxx"}},
    "dimensions": [{"field_name": "城市", "alias": "dim_city"}],
    "measures": [{"field_name": "金额", "aggregation": "sum", "alias": "total_amount"}],
    "filters": {
      "type": 1,
      "conjunction": "and",
      "conditions": [{"field_name": "城市", "operator": "isNot", "value": [""]}]
    },
    "sort": [{"field_name": "total_amount", "order": "desc"}],
    "pagination": {"limit": 100},
    "shaper": {"format": "flat"}
  }'

# 使用 tableName（表名）代替 tableId
lark-cli base +data-query \
  --base-token MAGObxxxxx \
  --dsl '{
    "datasource": {"type": "table", "table": {"tableName": "销售数据"}},
    "measures": [{"field_name": "金额", "aggregation": "sum", "alias": "total"}],
    "shaper": {"format": "flat"}
  }'
```

## 参数

| 参数                     | 必填 | 说明 |
|------------------------|------|------|
| `--base-token <token>` | 是 | 多维表格 App Token（base_token） |
| `--dsl <json>`         | 是 | LiteQuery Protocol JSON DSL 查询语句 |

## 如何从链接中提取参数

用户通常会提供如下 URL：

```
https://example.feishu.cn/base/<app_token>?table=<table_id>
```

- `--base-token`：取 `/base/` 后面的字符串
- DSL 中的 `tableId`：取 `table=` 后面的值

## API 入参详情

**HTTP 方法和路径：**

```
POST /open-apis/base/v3/bases/:base_token/data/query
```

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | 多维表格 App Token |

**Request Body — DSL 结构：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `datasource` | object | 是 | 数据源，包含 `type`（固定 `"table"`）和 `table` 对象 |
| `datasource.table.tableId` | string | 二选一 | 目标数据表 ID |
| `datasource.table.tableName` | string | 二选一 | 目标数据表名称 |
| `dimensions` | Dimension[] | 否* | 分组维度字段（GROUP BY） |
| `measures` | Measure[] | 否* | 聚合度量字段 |
| `filters` | FilterGroup | 否 | 过滤条件（WHERE） |
| `sort` | Sort[] | 否 | 排序规则 |
| `pagination` | object | 否 | 限制返回行数，`{limit: N}`，最大 5000 |
| `shaper` | object | 否 | 结果格式，固定 `{format: "flat"}` |

> \* `dimensions` 和 `measures` 至少填写一个。

**Dimension 字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `field_name` | string | 是 | 字段名称 |
| `alias` | string | 否 | 输出列别名，需全局唯一 |

**Measure 字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `field_name` | string | 是 | 字段名称 |
| `aggregation` | string | 是 | 聚合函数：`sum`、`avg`、`min`、`max`、`count`、`count_all`、`distinct_count` |
| `alias` | string | 否 | 输出列别名，需全局唯一 |

**聚合函数适用字段类型：**

| 聚合函数 | 适用字段类型 |
|----------|-------------|
| `sum` / `avg` | 数字、进度、货币、评分（不含复选框） |
| `min` / `max` | 数字、进度、货币、评分、日期 |
| `count` | 白名单内所有类型，计数非空值 |
| `count_all` | 白名单内所有类型，计数所有行 |
| `distinct_count` | 白名单内所有类型 |

**FilterGroup：**

```json
{
  "filters": {
    "type": 1,
    "conjunction": "and",
    "conditions": [
      {"field_name": "城市", "operator": "is", "value": ["北京"]}
    ]
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | int | 是 | 固定填 `1` |
| `conjunction` | string | 否 | 条件组合逻辑：`"and"` 或 `"or"`，默认 `"and"` |
| `conditions` | Condition[] | 否 | 条件列表 |

**Condition：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `field_name` | string | 是 | 字段名称（必须与表中字段名精确匹配） |
| `operator` | string | 是 | 运算符（见下方运算符表） |
| `value` | string[] | 是 | 条件值数组；`isEmpty`/`isNotEmpty` 时**必须**传空数组 `[]` |

**运算符：**

| 运算符 | 说明 |
|--------|------|
| `is` | 等于 |
| `isNot` | 不等于 |
| `contains` | 包含 |
| `doesNotContain` | 不包含 |
| `isEmpty` | 为空 |
| `isNotEmpty` | 不为空 |
| `isGreater` | 大于 |
| `isGreaterEqual` | 大于等于 |
| `isLess` | 小于 |
| `isLessEqual` | 小于等于 |

> 各运算符的适用字段类型见下方「按各字段类型筛选时 value 格式详解」。

**按各字段类型筛选时 value 格式详解：**

*文本 / 邮箱 / 条码*

| 运算符 | value 格式 | 元素个数 | 示例 |
|--------|-----------|---------|------|
| `is` / `isNot` / `contains` / `doesNotContain` | `["文本内容"]` | 仅 1 个 | `["Hello"]` |
| `isEmpty` / `isNotEmpty` | `[]` | 0 个 | `[]` |

*数字 / 货币*

| 运算符 | value 格式 | 元素个数 | 示例 |
|--------|-----------|---------|------|
| `is` / `isNot` / `isGreater` / `isGreaterEqual` / `isLess` / `isLessEqual` | `["数字字符串"]` | 仅 1 个 | `["23.4"]`、`["-100"]` |
| `isEmpty` / `isNotEmpty` | `[]` | 0 个 | `[]` |

> value 必须为合法数字的字符串形式。

*进度*

| 运算符 | value 格式 | 元素个数 | 示例 |
|--------|-----------|---------|------|
| `is` / `isNot` / `isGreater` / `isGreaterEqual` / `isLess` / `isLessEqual` | `["小数字符串"]` | 仅 1 个 | `["0.34"]`（= 34%） |
| `isEmpty` / `isNotEmpty` | `[]` | 0 个 | `[]` |

> **用小数表示百分比**：`["0.34"]` 表示 34%，不是 `["34"]`。

*评分*

| 运算符 | value 格式 | 元素个数 | 示例 |
|--------|-----------|---------|------|
| `is` / `isNot` / `isGreater` / `isGreaterEqual` / `isLess` / `isLessEqual` | `["数字字符串"]` | 仅 1 个 | `["4"]` |
| `isEmpty` / `isNotEmpty` | `[]` | 0 个 | `[]` |

*单选 / 多选*

| 运算符 | value 格式 | 元素个数 | 示例 |
|--------|-----------|---------|------|
| `is` / `isNot` | `["选项名"]` | **仅 1 个** | `["选项A"]` |
| `contains` / `doesNotContain` | `["选项A", "选项B"]` | 可多个 | `["选项A", "选项B"]` |
| `isEmpty` / `isNotEmpty` | `[]` | 0 个 | `[]` |

*人员*

| 运算符 | value 格式 | 元素个数 | 示例                     |
|--------|-----------|---------|------------------------|
| `is` / `isNot` | `["用户ID"]` | **仅 1 个** | `["ou_aaa"]`           |
| `contains` / `doesNotContain` | `["用户ID1", "用户ID2"]` | 可多个 | `["ou_aaa", "ou_bbb"]` |
| `isEmpty` / `isNotEmpty` | `[]` | 0 个 | `[]`                   |

> 用户 ID 使用 `open_id`（`ou_` 前缀），接口层会自动做 ID 转换。

*超链接*

| 运算符 | value 格式 | 元素个数 | 示例 |
|--------|-----------|---------|------|
| `is` / `isNot` / `contains` / `doesNotContain` | `["链接显示名称"]` | 仅 1 个 | `["点击查看"]` |
| `isEmpty` / `isNotEmpty` | `[]` | 0 个 | `[]` |

> **按显示名称筛选**，不是按 URL 本身。

*复选框*

| 运算符 | value 格式 | 元素个数 | 示例 |
|--------|-----------|---------|------|
| `is` | `["true"]` 或 `["false"]` | 仅 1 个 | `["true"]` |

> 仅支持 `is` 运算符，不支持其他运算符。

*日期*

日期字段仅支持 `is`、`isEmpty`、`isNotEmpty`、`isGreater`、`isLess` 五种运算符。

value 使用预定义关键字机制，第一个元素为字符串常量名称：

| 关键字 | 说明 | value 格式 | 支持的运算符 |
|--------|------|-----------|-------------|
| `ExactDate` | 精确日期 | `["ExactDate", "1773187200000"]`（毫秒时间戳） | `is`、`isGreater`、`isLess` |
| `Today` | 今天 | `["Today"]` | `is`、`isGreater`、`isLess` |
| `Tomorrow` | 明天 | `["Tomorrow"]` | `is`、`isGreater`、`isLess` |
| `Yesterday` | 昨天 | `["Yesterday"]` | `is`、`isGreater`、`isLess` |
| `CurrentWeek` | 本周 | `["CurrentWeek"]` | 仅 `is` |
| `LastWeek` | 上周 | `["LastWeek"]` | 仅 `is` |
| `CurrentMonth` | 本月 | `["CurrentMonth"]` | 仅 `is` |
| `LastMonth` | 上月 | `["LastMonth"]` | 仅 `is` |
| `TheLastWeek` | 过去七天 | `["TheLastWeek"]` | 仅 `is` |
| `TheNextWeek` | 未来七天 | `["TheNextWeek"]` | 仅 `is` |
| `TheLastMonth` | 过去三十天 | `["TheLastMonth"]` | 仅 `is` |
| `TheNextMonth` | 未来三十天 | `["TheNextMonth"]` | 仅 `is` |

> - **ExactDate 时区行为**：毫秒时间戳在实际筛选时会被转为**文档时区当天零点**，跨时区场景需注意日期可能偏移一天。
> - **范围型关键字**（`CurrentWeek`、`LastWeek`、`CurrentMonth`、`LastMonth`、`TheLastWeek`、`TheNextWeek`、`TheLastMonth`、`TheNextMonth`）仅支持 `is` 运算符。
> - **关键字大小写敏感**：`ExactDate`、`Today`、`CurrentWeek` 等首字母大写，写错大小写会导致校验失败。

**Sort 字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `field_name` | string | 是 | 字段名称或 alias |
| `order` | string | 否 | `"asc"`（默认）或 `"desc"` |

**Pagination 字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `limit` | int | 否 | 返回记录数上限，必须为正整数，最大 5000；不填时使用系统默认值。不支持 offset |

**Shaper 字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `format` | string | 是 | 固定为 `"flat"`，表示返回扁平化的对象数组 |

## API 出参详情

**成功时：**

```json
{"code": 0, "data": {"main_data": [{"dim_city": {"value": "北京"}, "total_amount": {"value": 12345.00}}, ...]}, "msg": ""}
```

**失败时：**

```json
{"code": 800004006, "data": {"error": {"code": 800004006, ...}}, "msg": "DSL validation failed"}
```

**Response 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 状态码，0 为成功 |
| `msg` | string | 错误信息 |
| `data.main_data` | []object | 查询结果数组，每个元素为一行数据 |
| `data.error` | object | 失败时的错误详情 |

每行数据的字段值封装在 CellValue 中：

```json
{
  "dim_city": {
    "value": "北京"
  },
  "total_amount": {
    "value": 12345.00
  }
}
```

- `value`：展示值（人员名称、选项名称、格式化日期等）

## 返回值

命令成功后输出 `data` 字段的内容：

```json
{
  "main_data": [
    {
      "dim_city": {"value": "直营"},
      "measure_count": {"value": 1}
    },
    {
      "dim_city": {"value": "加盟"},
      "measure_count": {"value": 2}
    }
  ]
}
```

## 工作流

1. 确认 base-token 和 table-id
2. **先查表结构**：执行 `lark-cli base app.table.fields list --params '{"app_token":"<token>","table_id":"<id>"}'`
3. 从返回的字段列表中：
   - 获取 field_name（DSL 中使用的字段名称）
   - 仅选择白名单内的字段类型（见「限制」章节），排除公式、查找引用、附件等不支持的字段
4. 根据字段信息构造 DSL JSON
5. 执行 +data-query
6. 解读返回结果：
   - 结果在 `data.main_data` 数组中，每个元素代表一行
   - 每行对象的 key 为 DSL 中指定的 `alias`；未指定 alias 时，key 为自动生成的列名
   - 每个 value 是 CellValue 对象，实际值在 `value` 字段中，如 `{"value": "北京"}` 或 `{"value": 12345.00}`
   - 失败时结果在 `data.error` 中，包含具体错误码和信息

## 坑点

- ⚠️ **必须先查表结构**：DSL 的 `field_name` 必须与表中字段名称精确匹配（区分大小写），不能凭猜测构造。先用 `base app.table.fields list` 获取真实字段名
- ⚠️ **权限要求 FA**：调用者必须是目标多维表格的管理员，它才能拥有目标多维表格的 **FA（Full Access / 完全访问权限）**，否则返回权限错误
- ⚠️ **alias 不支持中文**：dimensions 和 measures 的 alias 必须使用英文（如 `dim_city`、`total_amount`），中文 alias 会导致错误
- ⚠️ **API 路径是 `base/v3`**：本接口路径为 `/open-apis/base/v3/bases/:base_token/data/query`，不是 `bitable/v1`。两者完全不同，用错版本号会返回 `[2200] Internal Error`
- ⚠️ **`dimensions` 和 `measures` 至少填一个**：两个都不填会返回 DSL 校验错误
- ⚠️ **`shaper` 必须为 `{"format": "flat"}`**：不填或填其他值会导致结果格式不可预期，建议始终显式指定
- ⚠️ **数据表标识 `tableId` vs `tableName`**：datasource 中可以用 `tableId`（如 `tblXXX`）或 `tableName`（数据表的用户自定义显示名称），二选一，不要混用
- ⚠️ **`pagination.limit` 最大 5000**：超过会报错，且不支持 offset，只支持 limit
- ⚠️ **所有 alias 必须全局唯一**：dimensions 和 measures 之间的 alias 也不能重名

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
- [lark-base-shortcut-record-value.md](lark-base-shortcut-record-value.md) — shortcut 字段值格式规范
- [lark-base-shortcut-field-properties.md](lark-base-shortcut-field-properties.md) — shortcut 字段类型与 JSON 结构
