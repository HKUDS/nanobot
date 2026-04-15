# Workflow 数据结构参考

本文档定义 Workflow 的完整数据结构，适用于：
- **查询场景**：理解 `+workflow-get` 返回的 `steps` 结构
- **创建/修改场景**：构造 `+workflow-create` / `+workflow-update` 的 `--json` body
> 💡 **本文档是纯字段参考**。如需**创建/修改**工作流的完整示例，请阅读 [workflow-guide.md](lark-base-workflow-guide.md)。
---
## 📖 快速导航

根据你的需求跳转到对应章节：

| 需求 | 章节 |
|------|------|
| 了解 Step 基础结构 | [WorkflowStep 基础结构](#workflowstep-基础结构) |
| 查询 Trigger 类型及 data 字段 | [Trigger data](#trigger-data-详细结构) |
| 查询 Action 类型及 data 字段 | [Action data](#action-data-详细结构) |
| 查询 Branch/Loop 结构 | [Branch data](#branch-data-详细结构) / [System data](#system-data-详细结构) |
| 查询 ValueInfo/Condition 等公共类型 | [公共类型](#公共类型) |

---

## WorkflowStep 基础结构

每个步骤（Trigger / Action / Branch / System）共享以下字段：

```json
{
  "id": "step_xxx",
  "type": "AddRecordTrigger",
  "title": "监控新订单",
  "next": "step_yyy",
  "data": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 步骤唯一 ID（用户自定义，被 `next` 和 `children.links[].to` 引用） |
| `type` | string | 是 | 步骤类型，见下方枚举 |
| `title` | string | 否 | 步骤标题 |
| `children` | StepChildren | 否 | 子关系边，承担所有分支/循环 |
| `next` | string | null | 否 | 线性后继节点 ID；`null` 表示流程结束 |
| `data` | object | 是 | 步骤详细配置，按 `type` 区分，见后续各节 |

> **总原则**：连线写 `children`，扩展标识写 `meta`，输入参数写 `data`。

---

## StepChildren 与 ChildLink

### StepChildren

```json
{
  "links": [ /* ChildLink[] */ ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `links` | ChildLink[] | 子关系边列表；无子关系时为空数组 `[]` |

### ChildLink

每条关系边描述从当前节点到目标节点的有向连线：

```json
{ "kind": "if_true", "to": "step_4", "label": "branch_1", "desc": "金额大于1000" }
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `kind` | string | 是 | 关系类型：`if_true` / `if_false` / `case` / `loop_start` / `slot` |
| `to` | string | 是 | 目标节点 ID |
| `label` | string | 否 | 可选标签（如 `branch_1`、`tool`、`llm`、`memory`） |
| `desc` | string | 否 | 可选语义说明（如"销售部门"、"积极情绪"） |

`kind` 使用场景：

| kind | 使用节点 | 说明 |
|------|---------|------|
| `if_true` | IfElseBranch | 条件为真时跳转 |
| `if_false` | IfElseBranch | 条件为假时跳转 |
| `case` | SwitchBranch / AIClassificationBranch | 多路分支，`label` 建议用 `branch_1` 等中性标签，`desc` 写语义 |
| `loop_start` | Loop | 循环体入口 |
| `slot` | AIAgentAction | 挂载 LLM / 工具 / 记忆子节点，`label` 为 `llm` / `tool` / `memory` |

---

## StepType 枚举

### Trigger 类型

| type | 说明 |
|------|------|
| `AddRecordTrigger` | 新增记录时触发 |
| `SetRecordTrigger` | 记录被修改时触发 |
| `ChangeRecordTrigger` | 记录满足条件时触发 |
| `TimerTrigger` | 定时触发 |
| `ReminderTrigger` | 日期提醒触发 |
| `LarkMessageTrigger` | 接收飞书消息触发 |

> 所有 Trigger 节点**请勿设置** `children` ，通过 `next` 串联后继。

### 触发器选型指南

| 需求描述 | 触发器 |
|---------|--------|
| 新增记录时 | `AddRecordTrigger` |
| 字段变为特定值时（**仅修改**） | `SetRecordTrigger` |
| **新增或修改**都触发 | `ChangeRecordTrigger` |
| 拿不准用哪个 | `ChangeRecordTrigger` |

> ⚠️ `SetRecordTrigger` 仅监听修改，`ChangeRecordTrigger` 同时监听新增 + 修改。

### Action 类型

| type | 说明 |
|------|------|
| `AddRecordAction` | 新增记录 |
| `SetRecordAction` | 更新记录 |
| `FindRecordAction` | 查找记录 |
| `Delay` | 延迟 |
| `LarkMessageAction` | 发送飞书消息 |
| `GenerateAiTextAction` | AI 生成文本 |

> 所有 Action 节点**请勿设置** `children` ，通过 `next` 串联后继。

### Branch 类型

| type | 说明 |
|------|------|
| `IfElseBranch` | 条件分支，`children.links` 含 `if_true` 和 `if_false` |
| `SwitchBranch` | 多路分支，`children.links` 含多个 `case` |

### System 类型

| type | 说明 |
|------|------|
| `Loop` | 循环，`children.links` 含 `loop_start` 指向循环体入口 |

---

## Trigger data 详细结构


### AddRecordTrigger

```json
{
  "table_name": "订单表",
  "watched_field_name": "状态",
  "trigger_control_list": ["pasteUpdate", "automationBatchUpdate"],
  "condition_list": [] /* AndCondition 数组 */ 
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `table_name` | 是 | 监控的数据表名 |
| `watched_field_name` | 是 | 监控的字段名 |
| `trigger_control_list` | 否 | 触发控制，可选值：`pasteUpdate` / `automationBatchUpdate` / `syncUpdate` / `appendImport` / `openAPIBatchUpdate` |
| `condition_list` | 否 | 过滤条件数组，数组中每个元素为 AndCondition 结构，多个 AndCondition 之间为 OR 关系 |

### ChangeRecordTrigger

```json
{
  "table_name": "任务表",
  "trigger_control_list": [],
  "condition": null
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `table_name` | 是 | 监控的数据表名 |
| `trigger_control_list` | 否 | 触发控制，可选值：`pasteUpdate` / `automationBatchUpdate` / `syncUpdate` / `appendImport` |
| `condition_list` | 否 | 过滤条件数组，数组中每个元素为 AndCondition 结构，多个 AndCondition 之间为 OR 关系 |

### SetRecordTrigger

```json
{
  "table_name": "订单表",
  "record_watch_conjunction": "and",
  "record_watch_info": [ /* FieldCondition[] */ ],
  "field_watch_info": [
    { "field_name": "状态", "operator": "is", "value": [{ "value_type": "text", "value": "已发货" }] }
  ],
  "trigger_control_list": [],
  "condition_list": null
}
```

| 字段 | 必填 | 说明 |
|------|----|------|
| `table_name` | 是  | 监控的数据表名 |
| `record_watch_conjunction` | 否  | 记录筛选组合方式：`and` / `or`，默认 `and` |
| `record_watch_info` | 否  | 记录级过滤条件（修改前值匹配），为空则监听全部 |
| `field_watch_info` | 是  | 字段级监控条件列表，至少一个 |
| `trigger_control_list` | 否  | 触发控制，可选值：`pasteUpdate` / `automationBatchUpdate` / `syncUpdate` / `appendImport` |
| `condition_list` | 否  | 过滤条件数组，数组中每个元素为 AndCondition 结构，多个 AndCondition 之间为 OR 关系 |

`FieldWatchItem`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `field_name` | string | 监听字段名称 |
| `operator` | string | 操作符（仅明确要求字段满足条件时填） |
| `value` | ValueInfo[] | 触发值 |

### TimerTrigger

```json
{
  "rule": "WEEKLY",
  "start_time": "2025-01-01 09:00",
  "sub_unit": [1, 3, 5],
  "is_never_end": true
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `rule` | 是 | `NO_REPEAT` / `DAILY` / `WEEKLY` / `MONTHLY` / `YEARLY` / `WORKDAY` / `CUSTOM` |
| `start_time` | 否 | 开始时间，格式 `yyyy-MM-dd HH:mm` |
| `interval` | 否 | 自定义间隔 [1,30]（仅 CUSTOM） |
| `unit` | 否 | 自定义单位：`SECOND` / `MINUTE` / `HOUR` / `DAY` / `WEEK` / `MONTH` / `YEAR` |
| `sub_unit` | 否 | 子单位（`WEEKLY` 时为星期几数组 0-6，`MONTHLY` 时为几号数组 1-31） |
| `end_time` | 否 | 结束时间 |
| `is_never_end` | 否 | 是否永不结束 |

### ReminderTrigger

```json
{
  "table_name": "项目表",
  "field_name": "截止日期",
  "offset": 1,
  "unit": "DAY",
  "hour": 9,
  "minute": 0,
  "condition_list": null
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `table_name` | 是 | 数据表名 |
| `field_name` | 是 | 日期字段名（必须为 DateTime / CreatedTime / Formula / Lookup 类型） |
| `unit` | 是 | 偏移单位：`MINUTE` / `HOUR` / `DAY` / `WEEK` / `MONTH` |
| `offset` | 是 | 提前/延后的偏移量（正数=提前，负数=延后；范围由 `unit` 决定）：`MINUTE` ∈ {0, 5, 15, 30, -5, -15, -30}；`HOUR` ∈ [-6, -1] ∪ [1, 6]；`DAY` ∈ [-7, 7]；`WEEK` ∈ [-7, -1] ∪ [1, 7]；`MONTH` ∈ [-7, -1] ∪ [1, 7] |
| `hour` | 是 | 触发小时 (0-23)，默认 9 |
| `minute` | 是 | 触发分钟 (0-59)，默认 0 |
| `condition_list` | 否 | 过滤条件数组，数组中每个元素为 AndCondition 结构，多个 AndCondition 之间为 OR 关系  | 


### LarkMessageTrigger

```json
{
  "receive_scene": "group",
  "receiver": [{ "value_type": "group", "value": {"id": "oc_xxxx", "name": "测试群"} }],
  "scope": "all",
  "filter": {
    "conjunction": "and",
    "content_contains": ["关键词"],
    "sender_contains": [{ "value_type": "user", "value": {"id": "ou_xxxx", "name": ""} }],
    "is_new_message": true,
    "is_message_contain_attachment": false
  }
}
```

| 字段 | 必填 | 说明|
|------|------|---|
| `receive_scene` | 是 | 接收场景：`group`（群聊）/ `chat`（单聊）|
| `receiver` | 是 | 触发来源，支持 `user` / `group` / `ref`。在单聊场景下，该字段指“可以和机器人单聊的用户”；在群聊场景下，该字段指“接收信息的群组”|
| `scope` | 是 | 触发范围：`at`（@提及）/ `all`（所有消息）。该参数仅在群聊场景有效，单聊场景请勿指定该参数|
| `filter` | 是 | MessageFilter 消息过滤条件|

`MessageFilter`：

| 字段 | 类型 | 说明 |
|------|------|----|
| `conjunction` | string | `and` 满足所有条件 / `or` 任一条件|
| `content_contains` | string[] | 关键词列表|
| `sender_contains` | ValueInfo[] | 筛选发送人（仅群聊+群组来源时生效，单聊场景请勿指定该参数）|
| `is_new_message` | boolean | 仅新话题消息（仅群聊时有效，单聊场景请勿指定该参数）|
| `is_message_contain_attachment` | boolean | 是否仅附件消息触发|

## Action data 详细结构

### AddRecordAction

```json
{
  "table_name": "订单表",
  "field_values": [
    { "field_name": "客户名称", "value": [{ "value_type": "text", "value": "张三" }] },
    { "field_name": "金额", "value": [{ "value_type": "number", "value": 100 }] },
    { "field_name": "创建人", "value": [{ "value_type": "ref", "value": "$.trigger_1.fieldIdxxx" }] }
  ]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `table_name` | 是 | 目标数据表名 |
| `field_values` | 是 | RecordFieldValue[] |

### SetRecordAction

```json
{
  "table_name": "订单表",
  "max_set_record_num": 10,
  "field_values": [
    { "field_name": "状态", "value": [{ "value_type": "option", "value": { "id": "opt1", "name": "已完成" } }] }
  ],
  "filter_info": { /* RecordFilterInfo */ },
  "ref_info": { "step_id": "step_trigger" }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `table_name` | 是 | 目标数据表名 |
| `max_set_record_num` | 否 | 最大更新记录数，默认 100，范围 1-15000 |
| `field_values` | 是 | RecordFieldValue[] |
| `filter_info` | 否* | RecordFilterInfo 过滤条件（与 `ref_info` 互斥） |
| `ref_info` | 否* | RefInfo 引用前置步骤的记录（与 `filter_info` 互斥） |

### FindRecordAction

```json
{
  "table_name": "客户表",
  "field_names": ["客户名称", "联系方式", "等级"],
  "should_proceed_when_no_results": true,
  "filter_info": { /* RecordFilterInfo */ }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `table_name` | 是 | 目标数据表名 |
| `field_names` | 是 | 要检索的字段名列表，至少一个 |
| `should_proceed_when_no_results` | 否 | 无结果时是否继续后续步骤，默认 `true` |
| `filter_info` | 否* | RecordFilterInfo（与 `ref_info` 互斥） |
| `ref_info` | 否* | RefInfo（与 `filter_info` 互斥） |

### Delay

```json
{ "duration": 30 }
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `duration` | 是 | 延迟时长（分钟），范围 [1, 120] |

### LarkMessageAction

```json
{
  "receiver": [{ "value_type": "user", "value": {"id": "ou_xxxx"} }],
  "send_to_everyone": false,
  "title": [{ "value_type": "text", "value": "新订单通知" }],
  "content": [
    { "value_type": "text", "value": "客户 " },
    { "value_type": "ref", "value": "$.trigger_1.fldCustomerName" },
    { "value_type": "text", "value": " 创建了新订单" }
  ],
  "btn_list": [
    { "text": "查看详情", "btn_action": "openLink", "link": [{ "value_type": "text", "value": "https://example.com" }] }
  ]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `receiver` | 是 | ValueInfo[] |
| `send_to_everyone` | 是 | 是否发送给所有人 |
| `title` | 否 | TextRefItem[] 消息标题 |
| `content` | 是 | TextRefItem[] 消息内容 |
| `btn_list` | 是 | 按钮列表，不需要时为空数组 |

`ButtonConfig`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | string | 按钮文字 |
| `btn_action` | string | `addRecord` / `setRecord` / `openLink` |
| `link` | ValueInfo[] | 跳转链接（`openLink` 时使用） |
| `table_name` | string | 操作表名（`addRecord` 时使用） |
| `record_values` | RecordFieldValue[] | 记录赋值（`addRecord` / `setRecord` 时使用） |

### GenerateAiTextAction

```json
{
  "prompt": [
    { "value_type": "text", "value": "请总结以下内容：" },
    { "value_type": "ref", "value": "$.step_1.fieldxxx" }
  ]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `prompt` | 是 | TextRefItem[] 提示词，支持 `text` / `ref` |


## Branch data 详细结构

### IfElseBranch

`children.links` 包含 `if_true` 和 `if_false` 两条边，`next` 指向两个分支汇合后的后继节点。

**如果涉及到复杂的多分支场景(分支数目 >= 3时)，你应该采用 SwitchBranch，而不是嵌套的 IfElseBranch**

```json
{
  "condition": {
    "conjunction": "or",
    "conditions": [
      {
        "conjunction": "and",
        "conditions": [
          {
            "left_value": { "value_type": "ref", "value": "$.step_1.fieldxxx" },
            "operator": "isGreater",
            "right_value": [{ "value_type": "number", "value": 1000 }]
          }
        ]
      }
    ]
  }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `condition` | 是 | OrGroup 判断条件，结构为 `(A and B) or (C and D)` |

### SwitchBranch

`children.links` 包含多个 `case` 边（`label` 建议用 `branch_1`、`branch_2`，语义写在 `desc`）。

```json
{
  "mode": "exclusive",
  "no_match_action": "classifyToOther",
  "child_branch_list": [
    {
      "name": "高优先级",
      "condition": {
        "conjunction": "or",
        "conditions": [
          {
            "conjunction": "and",
            "conditions": [
              {
                "left_value": { "value_type": "ref", "value": "$.step_1.fieldxxx" },
                "operator": "is",
                "right_value": [{ "value_type": "text", "value": "P0" }]
              }
            ]
          }
        ]
      }
    }
  ]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `mode` | 否 | 分支模式。`exclusive`：排他模式，仅执行一个满足条件的子分支；`parallel`：并行模式，执行所有满足条件的子分支。默认 `exclusive` |
| `no_match_action` | 否 | `mode=exclusive` 时使用，无匹配时的处理策略。`classifyToOther`：归类到其他分支；`fail`：报错终止。默认 `classifyToOther` |
| `fail_mode` | 否 | `mode=parallel` 时使用，部分分支出错时策略。`partialSuccess`：部分成功即继续；`fail`：任一失败即终止。默认 `partialSuccess` |
| `match_mode` | 否 | `mode=parallel` 时使用，所有分支不满足时策略。`noneMatchSkip`：跳过继续；`noneMatchFail`：报错终止。默认 `noneMatchSkip` |
| `child_branch_list` | 是 | BranchItem[]，1-10 个条件分支 |

`BranchItem`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 分支名称 |
| `condition` | OrGroup | 分支条件 |


## System data 详细结构

### Loop

`children.links` 包含 `loop_start` 边指向循环体入口，`next` 指向循环结束后的后继节点。

```json
{
  "loop_mode": "continue",
  "max_loop_times": 100,
  "data": [{ "value_type": "ref", "value": "$.find_record_stepIdxxx.fieldRecords" }]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `data` | 是 | ValueInfo[]（仅支持 `ref` 类型），循环数据源，只能填一个 |
| `loop_mode` | 否 | 单次错误时是否继续：`end`（终止）/ `continue`（继续） |
| `max_loop_times` | 否 | 最大循环次数 |

---


## 公共类型

### ValueInfo

所有值的基础类型，通过 `value_type` 区分：

| value_type | value 类型 | 说明 | 示例 |
|------------|-----------|------|------|
| `text` | string | 文本 | `"张三"` |
| `number` | number | 数字 | `100` |
| `boolean` | boolean | 布尔值 | `true` |
| `date` | string | 日期，可以是具体时间字符串，或者相对时间值 | `"2025/01/01"`、`"2025/01/01 11:00"`、`"now"`、`"now 11:00"`、`"today"`、`"today 11:00"`、`"yesterday"`、`"yesterday 11:00"`、`"lastWeek"`、`"currentMonth"`、`"lastMonth"`、`"theLastWeek"`、`"theNextWeek"`、`"theLastMonth"`、`"theNextMonth"` |
| `option` | `{ id, name }` | 选项 | `{ "id": "opt1", "name": "已完成" }` |
| `link` | `{ text, link }` | 链接（含文字和 URL）， 文字和 URL 的格式可以是 ValueInfo 中的 text/ref 类型 | `{ "text": [{ "value_type": "text", "value": "查看详情" }], "link": [{ "value_type": "text", "value": "https://example.com" }] }`、`{ "text": [{ "value_type": "text", "value": "查看详情" }], "link": [{ "value_type": "ref", "value": "$.step_1.fldXXX" }] }` |
| `user` | `{ id, name }` | 用户 OpenID、名字 | `{ "id": "ou_xxxx", "name": "张三" }` |
| `group` | `{ id, name }` | 群 Chat ID、名字 | `{ "id": "oc_xxx", "name": "测试群" }` |
| `ref` | `string` | 引用前置节点输出的路径 | 参考 ref 引用变量详解 章节 |

> ⚠️ **所有涉及用户的 value 中的 id 统一使用 OpenID（`ou_xxxx` 格式）**，由 CLI 层来完成转换
> ⚠️ **所有涉及群的 value 中的 id 统一使用 ChatID（`oc_xxxx` 格式）**，由 CLI 层来完成转换

### ref 引用变量详解

`ref` 类型是工作流中节点间数据传递的核心机制。当 `value_type` 为 `ref` 时，`value` 指向前置节点的某个输出变量。本节详细描述每个节点可供引用的输出变量定义。

#### 引用路径格式

```
$.{stepId}
$.{stepId}.{pathId}
$.{stepId}.{pathId}.{childPathId}
$.{stepId}.{pathId}.{childPathId}.{grandChildPathId}
```

- `{stepId}`：前置节点的 `id`（即 WorkflowStep 中的 `id` 字段）
- `{pathId}`：节点输出的路径标识符
- 支持多层下钻，如引用字段的属性：`$.step_1.fldXXX.name`

---

#### 触发器节点输出

##### 记录触发器（AddRecordTrigger / ChangeRecordTrigger / SetRecordTrigger / ReminderTrigger）

这 4 个触发器的输出结构完全一致：

| pathId | 说明 | 引用示例 |
|--------|------|----------|
| `{fieldId}` | 字段id，从配置表的所有字段或者指定字段id生成，可下钻字段属性 | `$.{stepId}.{fieldId}` |
| `{fieldId}.fieldId` | 字段id属性 | `$.{stepId}.{fieldId}.fieldId}` |
| `{fieldId}.fieldName` | 字段名属性 | `$.{stepId}.{fieldId}.fieldName}` |
| `startTime` | 触发时间戳 | `$.{stepId}.startTime` |
| `recordId` | 记录 ID | `$.{stepId}.recordId` |
| `recordLink` | 记录链接 | `$.{stepId}.recordLink` |
| `recordCreatedUser` | 记录创建者 | `$.{stepId}.recordCreatedUser` |
| `recordCreatedTime` | 记录创建时间 | `$.{stepId}.recordCreatedTime` |
| `recordModifiedUser` | 最后修改者 | `$.{stepId}.recordModifiedUser` |
| `recordModifiedTime` | 最后修改时间 | `$.{stepId}.recordModifiedTime` |

**动态字段输出规则**：

- 读取触发器所配置的数据表的所有字段
- 每个字段生成一条输出：`pathId` = fieldId
- 若字段为关联字段，children 为关联表所有字段（单层下钻，不再递归）
- 每个字段可下钻特定的字段属性（见「字段属性下钻」）

**recordLink 的 children**：如果配置了数据表，则为该表所有视图的列表，每个视图 `{ pathId: viewId, pathName: viewName, pathType: 'string' }`。引用示例：`$.{stepId}.recordLink.{viewId}`。

##### TimerTrigger（定时触发器）

| pathId | 说明 | 引用示例 |
|--------|------|----------|
| `scheduleTime` | 定时触发时间 | `$.{stepId}.scheduleTime` |

##### LarkMessageTrigger（飞书消息触发器）

| pathId | 说明 | 引用示例 |
|--------|------|----------|
| `Sender` | 消息发送者 | `$.{stepId}.Sender` |
| `AtUser` | 消息中被@的用户 | `$.{stepId}.AtUser` |
| `SenderGroup` | 消息所在群（仅群聊场景） | `$.{stepId}.SenderGroup` |
| `MessageSendTime` | 消息发送时间 | `$.{stepId}.MessageSendTime` |
| `MessageContent` | 消息正文 | `$.{stepId}.MessageContent` |
| `MessageType` | 消息类型标识 | `$.{stepId}.MessageType` |
| `MessageID` | 消息唯一标识 | `$.{stepId}.MessageID` |
| `MessageLink` | 消息链接（仅群聊场景） | `$.{stepId}.MessageLink` |
| `ParentID` | 回复的消息 ID | `$.{stepId}.ParentID` |
| `ThreadID` | 所在话题消息 ID | `$.{stepId}.ThreadID` |
| `Attachments` | 消息中的附件 | `$.{stepId}.Attachments` |

条件限制：

- 若场景为单聊（`receive_scene = "Chat"`），则 `SenderGroup` 和 `MessageLink` 不可用

---

#### 操作节点输出

##### FindRecordAction（查找记录）

| pathId | 说明 | 引用示例|
|--------|------|-------|
| `fieldRecords` | 所有找到的记录的引用（可用于 Loop 遍历） | `$.{stepId}.fieldRecords`|
| `firstfieldsRecord` | 第一条匹配记录 | `$.{stepId}.firstfieldsRecord`|
| `firstfieldsRecord.{fieldId}` | 首条记录的字段值，可下钻字段属性 | `$.{stepId}.firstfieldsRecord.{fieldId}`|
| `firstfieldsRecord.recordId` | 记录 ID 数组 | `$.{stepId}.firstfieldsRecord.recordId`|
| `fields` | 查找到的所有记录某列值 | 不支持引用|
| `fields.{fieldId}` | 用户选择的字段 | `$.{stepId}.fields.{fieldId}`|
| `fields.{fieldId}.fieldId` | 用户选择的字段id数组 | `$.{stepId}.fields.{fieldId}.fieldId`|
| `fields.{fieldId}.fieldName` | 用户选择的字段名数组 | `$.{stepId}.fields.{fieldId}.fieldName`|
| `fields.recordId` | 记录 ID 数组 | `$.{stepId}.fields.recordId`|
| `recordNum` | 找到记录总数 | `$.{stepId}.recordNum`|

##### AddRecordAction（新增记录）

| pathId | 说明 | 引用示例 |
|--------|------|----------|
| `{fieldId}` | 用户配置的字段值，可下钻字段属性 | `$.{stepId}.{fieldId}` |
| `{fieldId}.fieldId` | 用户配置的字段id | `$.{stepId}.{fieldId}.fieldId}` |
| `{fieldId}.fieldName` | 用户配置的字段名 | `$.{stepId}.{fieldId}.fieldName}` |
| `recordId` | 新增的记录 ID | `$.{stepId}.recordId` |
| `recordLink` | 新增的记录 URL | `$.{stepId}.recordLink` |

##### SetRecordAction（更新记录）

| pathId | 说明 | 引用示例 |
|--------|------|----------|
| `{fieldId}` | 用户配置的字段值，可下钻字段属性 | `$.{stepId}.{fieldId}` |
| `{fieldId}.fieldId` | 用户配置的字段id | `$.{stepId}.{fieldId}.fieldId}` |
| `{fieldId}.fieldName` | 用户配置的字段名 | `$.{stepId}.{fieldId}.fieldName}` |
| `recordId` | 记录 ID 数组（因可能更新多条记录） | `$.{stepId}.recordId` |

##### GenerateAiTextAction（AI 生成文本）

| pathId | 说明 | 引用示例 |
|--------|------|----------|
| （整体出参） | AI 生成的文本内容（不支持下钻，只能引用 `$.{stepId}`） | `$.{stepId}` |

##### 无输出的操作节点

以下节点不产生任何可引用的输出数据：

- **Delay**（延时等待）
- **LarkMessageAction**（发送飞书消息）

---

#### 分支节点输出

以下分支节点均不产生任何可引用的输出数据：

- **IfElseBranch**（条件分支）
- **SwitchBranch**（多条件分支）

---

#### 系统节点输出

##### Loop（循环）

| pathId | 说明 | 引用示例 |
|--------|------|----------|
| `item` | 当前循环元素 | `$.{stepId}.item` |
| `index` | 从 0 开始的循环索引 | `$.{stepId}.index` |

**`item` 的类型推断规则**（由循环数据源决定）：

**场景一：遍历组合记录** — 数据源为 `record` 类型时（如 FindRecordAction 的 `fieldRecords`），`item` 类型为 `record`，可向下选择具体字段：

| 说明 | 引用示例 |
|------|----------|
| 当前遍历的记录（record） | `$.{loopStepId}.item` |
| 记录的具体字段 | `$.{loopStepId}.item.{fieldId}` |
| 从 0 开始的索引（number） | `$.{loopStepId}.index` |

**场景二：遍历字段** — 数据源为某个多值类型字段时，比如附件字段、人员字段，`item` 继承该字段的类型并可继续下钻字段属性：

| 说明 | 引用示例 |
|------|----------|
| 当前遍历的元素（类型继承数据源字段类型，例如人员字段） | `$.{loopStepId}.item` |
| 用户姓名 | `$.{loopStepId}.item.name` |
| 从 0 开始的索引（number） | `$.{loopStepId}.index` |

---

#### 字段属性下钻

每个字段变量都可以进一步下钻选择字段的属性。所有字段至少支持 `fieldId` 和 `fieldName` 两个基础属性，部分字段还支持额外属性：

| 字段类型 | 属性名称 | 属性 pathId | 属性 pathType | 说明 |
|----------|---------|-------------|--------------|------|
| **所有字段（基础）** | 字段 ID | `fieldId` | `string` | 字段的唯一标识 |
| | 字段名称 | `fieldName` | `string` | 字段的显示名称 |
| **人员字段**（User / CreatedUser / ModifiedUser） | 姓名 | `name` | `string` | 用户姓名 |
| **日期字段**（DateTime / CreatedTime / ModifiedTime） | 时间戳 | `timestamp` | `number` | 时间戳数值 |
| **附件字段**（Attachment） | 文件名 | `fileName` | `string` | 附件文件名 |
| | 文件类型 | `fileType` | `string` | MIME 类型 |
| | 文件大小 | `size` | `number` | 文件字节数 |
| | 文件 Token | `fileToken` | `string` | 附件 token |
| **超链接字段**（URL） | 文本 | `text` | `string` | 链接文本部分 |
| | 链接 | `link` | `string` | 链接 URL 部分 |
| **自动编号字段**（AutoNumber） | 序号 | `sequence` | `number` | 编号的纯数字序号 |
| **关联字段**（SingleLink / DuplexLink） | 字段下钻 | `{fieldId}` | - | 可下钻到关联表的字段 |

> 其他字段类型（如文本、数字、复选框、单选/多选、电话、地理位置、进度、公式、引用查找等）仅支持 `fieldId` 和 `fieldName` 两个基础属性。

下钻引用示例：

```
$.{stepId}.{fieldId}              → 字段值本身
$.{stepId}.{fieldId}.fieldId      → 字段 ID（string）
$.{stepId}.{fieldId}.fieldName    → 字段名称（string）
$.{stepId}.{fieldId}.name         → 人员姓名列表（array<string>，仅人员字段）
$.{stepId}.{fieldId}.unionId      → 人员 unionId 列表（array<string>，仅人员字段）
$.{stepId}.{fieldId}.timestamp    → 时间戳（array<number>，仅日期字段）
$.{stepId}.{fieldId}.fileName     → 文件名列表（array<string>，仅附件字段）
$.{stepId}.{fieldId}.fileToken    → 文件 Token 列表（array<string>，仅附件字段）
```

---

#### 节点输出能力总览

| 节点 | 类型 | 有输出 | 输出特性 |
|------|------|--------|---------|
| AddRecordTrigger | 触发器 | ✅ | 动态（表字段 + 记录属性） |
| ChangeRecordTrigger | 触发器 | ✅ | 动态（表字段 + 记录属性） |
| SetRecordTrigger | 触发器 | ✅ | 动态（表字段 + 记录属性） |
| ReminderTrigger | 触发器 | ✅ | 动态（表字段 + 记录属性） |
| TimerTrigger | 触发器 | ✅ | 静态（仅 scheduleTime） |
| LarkMessageTrigger | 触发器 | ✅ | 静态（消息属性列表） |
| FindRecordAction | 动作 | ✅ | 动态（用户选择的字段） |
| AddRecordAction | 动作 | ✅ | 动态（用户配置的字段） |
| SetRecordAction | 动作 | ✅ | 动态（用户配置的字段） |
| GenerateAiTextAction | 动作 | ✅ | 静态（单 string） |
| Delay | 动作 | ❌ | 无输出 |
| LarkMessageAction | 动作 | ❌ | 无输出 |
| IfElseBranch | 分支 | ❌ | 无输出 |
| SwitchBranch | 分支 | ❌ | 无输出 |
| Loop | 系统 | ✅ | 动态（取决于数据源） |

---

### TextRefItem

文本与引用混排，用于消息内容等动态拼接场景：

```json
[
  { "value_type": "text", "value": "客户 " },
  { "value_type": "ref", "value": "$.step_1.fieldxxx" },
  { "value_type": "text", "value": " 创建了新订单" }
]
```

### RecordFieldValue

```json
{ "field_name": "客户名称", "value": [{ "value_type": "text", "value": "张三" }] }
```

### AndCondition（Trigger 过滤条件）

```json
{
  "conjunction": "and",
  "conditions": [
    { "field_name": "状态", "operator": "is", "value": [{ "value_type": "text", "value": "进行中" }] }
  ]
}
```

### OrGroup（Branch 分支条件）

```json
{
  "conjunction": "or",
  "conditions": [
    {
      "conjunction": "and",
      "conditions": [
        {
          "left_value": { "value_type": "ref", "value": "$.step_1.fieldxxx" },
          "operator": "isGreater",
          "right_value": [{ "value_type": "number", "value": 1000 }]
        }
      ]
    }
  ]
}
```

**operator 可选值：** `is` / `isNot` / `containsAny` / `doesNotContainAny` / /`containsAll`/ `isEmpty` / `isNotEmpty` / `isGreater` / `isGreaterEqual` / `isLess` / `isLessEqual`

### RecordFilterInfo
** 由于 conjunction 只支持 and，若需要实现 字段X 等于 A 或 B，你可以使用 containsAny
```json
{
  "conjunction": "and",
  "conditions": [
    { "field_name": "状态", "operator": "is", "value": [{ "value_type": "text", "value": "进行中" }] }
  ]
}
```

### Select / MultiSelect 字段多值匹配

| 操作 | operator | 正确写法 |
|------|---------|---------|
| 等于单个值 | `is` | `[{"value_type": "option", "value": {"name": "L2"}}]` |
| 匹配多个值（L2 或 L3） | `containsAny` | `[{"value_type": "option", "value": {"name": "L2"}}, {"value_type": "option", "value": {"name": "L3"}}]` |

> ⚠️ 不要用多个 `is` 条件（会被当作 OR，无法实现 AND）。推荐使用 `containsAny` 操作符匹配多个值。

> ⚠️ **Select 字段条件**：`value_type` 必须为 `option`，`value` 对象可只传 `name`（如 `{"name": "L2"}`），无需提供选项 ID。

### RefInfo

```json
{ "step_id": "step_trigger" }
```

---

## 完整示例：条件分支 + 发送消息

```json
{
  "title": "新订单自动通知",
  "steps": [
    {
      "id": "step_1",
      "type": "AddRecordTrigger",
      "title": "当「订单表」新增记录时触发",
      "next": "step_2",
      "data": {
        "table_name": "订单表",
        "watched_field_name": "订单编号"
      }
    },
    {
      "id": "step_2",
      "type": "IfElseBranch",
      "title": "判断订单金额是否大于 1000",
      "children": {
        "links": [
          { "kind": "if_true", "to": "step_3" },
          { "kind": "if_false", "to": "step_4" }
        ]
      },
      "next": "step_5",
      "data": {
        "condition": {
          "conjunction": "or",
          "conditions": [{
            "conjunction": "and",
            "conditions": [{
              "left_value": { "value_type": "ref", "value": "$.step_1.fieldxxx" },
              "operator": "isGreater",
              "right_value": [{ "value_type": "number", "value": 1000 }]
            }]
          }]
        }
      }
    },
    {
      "id": "step_3",
      "type": "LarkMessageAction",
      "title": "通知主管审批大额订单",
      "next": null,
      "data": {
        "receiver": [{ "value_type": "ref", "value": "$.step_1.fieldxxx" }],
        "send_to_everyone": false,
        "title": [{ "value_type": "text", "value": "大额订单提醒" }],
        "content": [
          { "value_type": "text", "value": "新订单金额为：" },
          { "value_type": "ref", "value": "$.step_1.fieldxxx" },
          { "value_type": "text", "value": "元，请及时审批。" }
        ],
        "btn_list": []
      }
    },
    {
      "id": "step_4",
      "type": "SetRecordAction",
      "title": "自动标记小额订单为已通过",
      "next": null,
      "data": {
        "table_name": "订单表",
        "ref_info": { "step_id": "step_1" },
        "field_values": [
          { "field_name": "审批状态", "value": [{ "value_type": "text", "value": "已通过" }] }
        ]
      }
    },
    {
      "id": "step_5",
      "type": "GenerateAiTextAction",
      "title": "AI 生成订单处理日报",
      "next": null,
      "data": {
        "prompt": [
          { "value_type": "text", "value": "请根据以下订单信息生成一份简要的处理日报：" },
          { "value_type": "ref", "value": "$.step_1.fieldxxx" }
        ]
      }
    }
  ]
}
```

---

## 参考

- [lark-base-workflow-create](lark-base-workflow-create.md) — 创建工作流命令
- [lark-base-workflow-update](lark-base-workflow-update.md) — 更新工作流命令
- [lark-base-workflow-list](lark-base-workflow-list.md) — 列出工作流命令
