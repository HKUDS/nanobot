# Workflow 构造指南

本文档提供 Workflow 的完整构造示例、常见模式和错误避免指南。

> **配套文档**:
> - Workflow 的数据结构参考：[lark-base-workflow-schema.md](lark-base-workflow-schema.md)
> - 创建命令：[lark-base-workflow-create.md](lark-base-workflow-create.md)
> - 更新命令：[lark-base-workflow-update.md](lark-base-workflow-update.md)

---

## 快速开始

### 最简单的 Workflow

新增记录时发送消息通知：

```json
{
  "client_token": "1704067200",
  "title": "新订单自动通知",
  "steps": [
    {
      "id": "trigger_1",
      "type": "AddRecordTrigger",
      "title": "监控新订单",
      "next": "action_1",
      "data": {
        "table_name": "订单表",
        "watched_field_name": "订单号"
      }
    },
    {
      "id": "action_1",
      "type": "LarkMessageAction",
      "title": "发送通知",
      "next": null,
      "data": {
        "receiver": [{ "value_type": "user", "value": {"id": "ou_xxxx", "name": "张三"} }],
        "send_to_everyone": false,
        "title": [{ "value_type": "text", "value": "新订单提醒" }],
        "content": [
          { "value_type": "text", "value": "收到新订单" }
        ],
        "btn_list": []
      }
    }
  ]
}
```

---

## 场景速查表

| 场景 | 步骤组合 | 示例 |
|------|---------|------|
| 新增触发+通知 | AddRecordTrigger → LarkMessageAction | [下方](#示例1-新增记录触发--发送消息) |
| 定时+循环 | TimerTrigger → FindRecordAction → Loop → LarkMessageAction | [下方](#示例2-定时触发--查找记录--循环遍历--发送消息) |
| 条件判断 | ... → IfElseBranch → 分支处理 | [下方](#示例3-条件分支-ifelsebranch) |
| 多路分类 | ... → SwitchBranch → 多分支处理 | [下方](#示例4-多路分支-switchbranch) |
| 复杂组合 | 定时+查找+循环+分支+消息 | [下方](#示例5-组合场景-定时查找循环分支消息) |

---

## 完整示例

### 示例 1: 新增记录触发 + 发送消息

**场景**: 当订单表新增记录时，发送飞书消息通知负责人。

```json
{
  "client_token": "1704067201",
  "title": "新订单自动通知",
  "steps": [
    {
      "id": "step_trigger",
      "type": "AddRecordTrigger",
      "title": "新增订单时触发",
      "next": "step_notify",
      "data": {
        "table_name": "订单表",
        "watched_field_name": "订单号",
        "condition_list": null
      }
    },
    {
      "id": "step_notify",
      "type": "LarkMessageAction",
      "title": "发送订单通知",
      "next": null,
      "data": {
        "receiver": [{ "value_type": "ref", "value": "$.step_trigger.fldManager" }],
        "send_to_everyone": false,
        "title": [{ "value_type": "text", "value": "新订单提醒" }],
        "content": [
          { "value_type": "text", "value": "客户 " },
          { "value_type": "ref", "value": "$.step_trigger.fldCustomer" },
          { "value_type": "text", "value": " 创建了新订单，金额：¥" },
          { "value_type": "ref", "value": "$.step_trigger.fldAmount" }
        ],
        "btn_list": [
          {
            "text": "查看订单",
            "btn_action": "openLink",
            "link": [{ "value_type": "ref", "value": "$.step_trigger.recordLink" }]
          }
        ]
      }
    }
  ]
}
```

**关键点**:
- `AddRecordTrigger` 监控 `table_name` 表的 `watched_field_name` 字段
- 使用 `ref` 引用触发器输出的字段值（注意是 fieldId，不是字段名）
- `recordLink` 是触发器内置输出，表示记录链接

---

### 示例 2: 定时触发 + 查找记录 + 循环遍历 + 发送消息

**场景**: 每天早上 9 点，查找所有待处理订单，给每个客户发送提醒。

```json
{
  "client_token": "1704067202",
  "title": "每日待处理订单提醒",
  "steps": [
    {
      "id": "step_timer",
      "type": "TimerTrigger",
      "title": "每天早上9点触发",
      "next": "step_find_orders",
      "data": {
        "rule": "DAILY",
        "start_time": "2025-01-01 09:00",
        "is_never_end": true
      }
    },
    {
      "id": "step_find_orders",
      "type": "FindRecordAction",
      "title": "查找所有待处理订单",
      "next": "step_loop_customers",
      "data": {
        "table_name": "订单表",
        "field_names": ["客户名称", "订单金额", "客户联系方式"],
        "should_proceed_when_no_results": false,
        "filter_info": {
          "conjunction": "and",
          "conditions": [
            {
              "field_name": "状态",
              "operator": "is",
              "value": [{ "value_type": "option", "value": { "name": "待处理" } }]
            }
          ]
        }
      }
    },
    {
      "id": "step_loop_customers",
      "type": "Loop",
      "title": "遍历每个订单",
      "children": {
        "links": [
          { "kind": "loop_start", "to": "step_send_reminder" }
        ]
      },
      "next": null,
      "data": {
        "loop_mode": "continue",
        "max_loop_times": 100,
        "data": [{
          "value_type": "ref",
          "value": "$.step_find_orders.fieldRecords"
        }]
      }
    },
    {
      "id": "step_send_reminder",
      "type": "LarkMessageAction",
      "title": "发送催办消息",
      "next": null,
      "data": {
        "receiver": [{
          "value_type": "ref",
          "value": "$.step_loop_customers.item.fldContact"
        }],
        "send_to_everyone": false,
        "title": [{ "value_type": "text", "value": "订单处理提醒" }],
        "content": [
          { "value_type": "text", "value": "您好，您的订单 " },
          { "value_type": "ref", "value": "$.step_loop_customers.item.fldName" },
          { "value_type": "text", "value": " 金额 ¥" },
          { "value_type": "ref", "value": "$.step_loop_customers.item.fldAmount" },
          { "value_type": "text", "value": " 正在处理中。" }
        ],
        "btn_list": []
      }
    }
  ]
}
```

**关键点**:
- `Loop.data` 必须传入 `ref` 类型的数据源（通常是 FindRecordAction 的 `fieldRecords`）
- `Loop.children.links` 必须包含 `kind: "loop_start"` 的链接指向循环体
- 循环体内用 `$.{loopStepId}.item.{fieldId}` 引用当前遍历记录的字段
- `$.{loopStepId}.index` 获取当前索引（从 0 开始）

---

### 示例 3: 条件分支（IfElseBranch）

**场景**: 根据订单金额判断，大额订单通知主管审批，小额订单自动通过。

```json
{
  "client_token": "1704067203",
  "title": "订单金额自动判断",
  "steps": [
    {
      "id": "step_trigger",
      "type": "AddRecordTrigger",
      "title": "新增订单时触发",
      "next": "step_check_amount",
      "data": {
        "table_name": "订单表",
        "watched_field_name": "订单金额"
      }
    },
    {
      "id": "step_check_amount",
      "type": "IfElseBranch",
      "title": "判断是否为大额订单",
      "children": {
        "links": [
          { "kind": "if_true", "to": "step_notify_manager", "label": "high", "desc": "金额>=10000" },
          { "kind": "if_false", "to": "step_auto_approve", "label": "normal", "desc": "金额<10000" }
        ]
      },
      "next": "step_log",
      "data": {
        "condition": {
          "conjunction": "or",
          "conditions": [
            {
              "conjunction": "and",
              "conditions": [
                {
                  "left_value": { "value_type": "ref", "value": "$.step_trigger.fldAmount" },
                  "operator": "isGreaterEqual",
                  "right_value": [{ "value_type": "number", "value": 10000 }]
                }
              ]
            }
          ]
        }
      }
    },
    {
      "id": "step_notify_manager",
      "type": "LarkMessageAction",
      "title": "通知主管审批大额订单",
      "next": "step_log",
      "data": {
        "receiver": [{ "value_type": "user", "value": {"id": "ou_manager", "name": "主管"} }],
        "send_to_everyone": false,
        "title": [{ "value_type": "text", "value": "大额订单待审批" }],
        "content": [
          { "value_type": "text", "value": "有大额订单 ¥" },
          { "value_type": "ref", "value": "$.step_trigger.fldAmount" },
          { "value_type": "text", "value": " 需要您审批" }
        ],
        "btn_list": []
      }
    },
    {
      "id": "step_auto_approve",
      "type": "SetRecordAction",
      "title": "自动标记小额订单为已审核",
      "next": "step_log",
      "data": {
        "table_name": "订单表",
        "ref_info": { "step_id": "step_trigger" },
        "field_values": [
          {
            "field_name": "审批状态",
            "value": [{ "value_type": "option", "value": { "name": "已自动审核" } }]
          }
        ]
      }
    },
    {
      "id": "step_log",
      "type": "GenerateAiTextAction",
      "title": "生成订单处理日志",
      "next": null,
      "data": {
        "prompt": [
          { "value_type": "text", "value": "请生成订单处理日志，金额：" },
          { "value_type": "ref", "value": "$.step_trigger.fldAmount" }
        ]
      }
    }
  ]
}
```

**关键点**:
- `IfElseBranch.children.links` 必须包含 `if_true` 和 `if_false` 两个分支
- `next` 指向两个分支汇合后的步骤（可选，为 null 则分支结束）
- `condition` 使用 OrGroup 结构，支持 `(A and B) or (C and D)` 的复杂条件
- 分支内可以用 `ref_info` 引用触发记录，用 `filter_info` 批量筛选记录

---

### 示例 4: 多路分支（SwitchBranch）

**场景**: 根据订单优先级（P0/P1/P2）执行不同的处理流程。

```json
{
  "client_token": "1704067204",
  "title": "按优先级分类处理订单",
  "steps": [
    {
      "id": "step_trigger",
      "type": "AddRecordTrigger",
      "title": "新增订单时触发",
      "next": "step_classify",
      "data": {
        "table_name": "订单表",
        "watched_field_name": "优先级"
      }
    },
    {
      "id": "step_classify",
      "type": "SwitchBranch",
      "title": "按优先级分类",
      "children": {
        "links": [
          { "kind": "case", "to": "step_p0_handler", "label": "p0", "desc": "P0-紧急" },
          { "kind": "case", "to": "step_p1_handler", "label": "p1", "desc": "P1-高优先级" },
          { "kind": "case", "to": "step_p2_handler", "label": "p2", "desc": "P2-普通" },
          { "kind": "case", "to": "step_other_handler", "label": "other", "desc": "其他" }
        ]
      },
      "next": null,
      "data": {
        "mode": "exclusive",
        "no_match_action": "classifyToOther",
        "child_branch_list": [
          {
            "name": "P0-紧急",
            "condition": {
              "conjunction": "or",
              "conditions": [
                {
                  "conjunction": "and",
                  "conditions": [
                    {
                      "left_value": { "value_type": "ref", "value": "$.step_trigger.fldPriority" },
                      "operator": "is",
                      "right_value": [{ "value_type": "option", "value": { "name": "P0" } }]
                    }
                  ]
                }
              ]
            }
          },
          {
            "name": "P1-高优先级",
            "condition": {
              "conjunction": "or",
              "conditions": [
                {
                  "conjunction": "and",
                  "conditions": [
                    {
                      "left_value": { "value_type": "ref", "value": "$.step_trigger.fldPriority" },
                      "operator": "is",
                      "right_value": [{ "value_type": "option", "value": { "name": "P1" } }]
                    }
                  ]
                }
              ]
            }
          },
          {
            "name": "P2-普通",
            "condition": {
              "conjunction": "or",
              "conditions": [
                {
                  "conjunction": "and",
                  "conditions": [
                    {
                      "left_value": { "value_type": "ref", "value": "$.step_trigger.fldPriority" },
                      "operator": "is",
                      "right_value": [{ "value_type": "option", "value": { "name": "P2" } }]
                    }
                  ]
                }
              ]
            }
          }
        ]
      }
    },
    {
      "id": "step_p0_handler",
      "type": "LarkMessageAction",
      "title": "P0紧急处理",
      "next": null,
      "data": {
        "receiver": [{ "value_type": "user", "value": {"id": "ou_director", "name": "总监"} }],
        "send_to_everyone": false,
        "title": [{ "value_type": "text", "value": "🚨 P0 紧急订单" }],
        "content": [{ "value_type": "text", "value": "有新的 P0 紧急订单需要立即处理" }],
        "btn_list": []
      }
    },
    {
      "id": "step_p1_handler",
      "type": "SetRecordAction",
      "title": "标记高优先级",
      "next": null,
      "data": {
        "table_name": "订单表",
        "ref_info": { "step_id": "step_trigger" },
        "field_values": [
          { "field_name": "处理状态", "value": [{ "value_type": "text", "value": "高优先级待处理" }] }
        ]
      }
    },
    {
      "id": "step_p2_handler",
      "type": "Delay",
      "title": "普通订单延迟处理",
      "next": null,
      "data": { "duration": 60 }
    },
    {
      "id": "step_other_handler",
      "type": "SetRecordAction",
      "title": "标记其他订单",
      "next": null,
      "data": {
        "table_name": "订单表",
        "ref_info": { "step_id": "step_trigger" },
        "field_values": [
          { "field_name": "处理状态", "value": [{ "value_type": "text", "value": "待分类" }] }
        ]
      }
    }
  ]
}
```

**关键点**:
- `SwitchBranch` 适合 3 路及以上的分支场景（少于 3 路用 `IfElseBranch` 更简洁）
- `children.links` 中 `kind: "case"` 的 `label` 对应 `child_branch_list` 中的条件
- `mode: "exclusive"` 表示排他执行（第一个匹配的分支执行后停止）
- `no_match_action: "classifyToOther"` 表示无匹配时走最后一个 `case`（兜底分支）

---

### 示例 5: 组合场景（定时+查找+循环+分支+消息）

**场景**: 每天早上 9 点，查找昨天的订单，按金额分级，给不同级别的销售发送不同的通知。

```json
{
  "client_token": "1704067205",
  "title": "每日订单分级通知",
  "steps": [
    {
      "id": "step_timer",
      "type": "TimerTrigger",
      "title": "每天早上9点触发",
      "next": "step_find_orders",
      "data": {
        "rule": "DAILY",
        "start_time": "2025-01-01 09:00",
        "is_never_end": true
      }
    },
    {
      "id": "step_find_orders",
      "type": "FindRecordAction",
      "title": "查找昨天所有订单",
      "next": "step_loop",
      "data": {
        "table_name": "订单表",
        "field_names": ["订单号", "客户名称", "金额", "销售负责人"],
        "should_proceed_when_no_results": false,
        "filter_info": {
          "conjunction": "and",
          "conditions": [
            { "field_name": "创建时间", "operator": "isGreaterEqual", "value": [{ "value_type": "date", "value": "yesterday" }] }
          ]
        }
      }
    },
    {
      "id": "step_loop",
      "type": "Loop",
      "title": "遍历每个订单",
      "children": {
        "links": [
          { "kind": "loop_start", "to": "step_classify" }
        ]
      },
      "next": "step_summary",
      "data": {
        "loop_mode": "continue",
        "max_loop_times": 500,
        "data": [{ "value_type": "ref", "value": "$.step_find_orders.fieldRecords" }]
      }
    },
    {
      "id": "step_classify",
      "type": "SwitchBranch",
      "title": "按金额分类",
      "children": {
        "links": [
          { "kind": "case", "to": "step_vip_notify", "label": "vip", "desc": "VIP >= 10万" },
          { "kind": "case", "to": "step_normal_notify", "label": "normal", "desc": "普通 < 10万" }
        ]
      },
      "next": null,
      "data": {
        "mode": "exclusive",
        "no_match_action": "fail",
        "child_branch_list": [
          {
            "name": "VIP订单",
            "condition": {
              "conjunction": "or",
              "conditions": [
                {
                  "conjunction": "and",
                  "conditions": [
                    {
                      "left_value": { "value_type": "ref", "value": "$.step_loop.item.fldAmount" },
                      "operator": "isGreaterEqual",
                      "right_value": [{ "value_type": "number", "value": 100000 }]
                    }
                  ]
                }
              ]
            }
          },
          {
            "name": "普通订单",
            "condition": {
              "conjunction": "or",
              "conditions": [
                {
                  "conjunction": "and",
                  "conditions": [
                    {
                      "left_value": { "value_type": "ref", "value": "$.step_loop.item.fldAmount" },
                      "operator": "isLess",
                      "right_value": [{ "value_type": "number", "value": 100000 }]
                    }
                  ]
                }
              ]
            }
          }
        ]
      }
    },
    {
      "id": "step_vip_notify",
      "type": "LarkMessageAction",
      "title": "VIP订单通知",
      "next": null,
      "data": {
        "receiver": [{ "value_type": "ref", "value": "$.step_loop.item.fldSales" }],
        "send_to_everyone": false,
        "title": [{ "value_type": "text", "value": "🌟 VIP大额订单" }],
        "content": [
          { "value_type": "text", "value": "恭喜！您有一笔 VIP 订单 ¥" },
          { "value_type": "ref", "value": "$.step_loop.item.fldAmount" },
          { "value_type": "text", "value": "，客户：" },
          { "value_type": "ref", "value": "$.step_loop.item.fldCustomer" }
        ],
        "btn_list": []
      }
    },
    {
      "id": "step_normal_notify",
      "type": "LarkMessageAction",
      "title": "普通订单通知",
      "next": null,
      "data": {
        "receiver": [{ "value_type": "ref", "value": "$.step_loop.item.fldSales" }],
        "send_to_everyone": false,
        "title": [{ "value_type": "text", "value": "新订单通知" }],
        "content": [
          { "value_type": "text", "value": "您有一笔新订单 ¥" },
          { "value_type": "ref", "value": "$.step_loop.item.fldAmount" }
        ],
        "btn_list": []
      }
    },
    {
      "id": "step_summary",
      "type": "GenerateAiTextAction",
      "title": "生成日报",
      "next": null,
      "data": {
        "prompt": [
          { "value_type": "text", "value": "请生成昨日订单处理日报" }
        ]
      }
    }
  ]
}
```

---

## 构造技巧

### Loop 构造要点

1. **数据源**: `Loop.data` 必须传入 `ref` 类型，通常是 `FindRecordAction` 的 `fieldRecords`
2. **循环体**: `children.links` 必须包含 `kind: "loop_start"` 指向循环体入口
3. **引用**: 循环体内用 `$.{loopStepId}.item.{fieldId}` 引用当前元素
4. **索引**: 用 `$.{loopStepId}.index` 获取当前索引（从 0 开始）

### 分支构造要点

1. **IfElseBranch**:
   - 适合二元判断（是/否、大于/小于）
   - `children.links` 必须包含 `if_true` 和 `if_false`
   - 可以用 `next` 指向汇合点

2. **SwitchBranch**:
   - 适合多路分类（3路及以上）
   - `label` 对应 `child_branch_list` 中的条件顺序
   - 建议加一个兜底分支（其他）

### 字段值构造

| 字段类型 | value_type | 示例 |
|---------|------------|------|
| 文本 | `text` | `{"value_type": "text", "value": "张三"}` |
| 数字 | `number` | `{"value_type": "number", "value": 100}` |
| 单选 | `option` | `{"value_type": "option", "value": {"name": "已完成"}}` |
| 人员 | `user` | `{"value_type": "user", "value": {"id": "ou_xxxx"}}` |
| 引用 | `ref` | `{"value_type": "ref", "value": "$.step_1.fldxxx"}` |

---

## 常见错误避免

### Top 10 高频错误

| # | 错误信息 | 原因 | 解决方案 |
|---|---------|------|---------|
| 1 | `path "xxx" does not exist in the output path tree` | ref 引用路径错误或 stepId 不存在 | 检查 stepId 是否在 steps 数组中；使用 fieldId 而非字段名；确保路径以 `$.` 开头 |
| 2 | `recordInfo.conditions must be non-empty` | `condition_list` 为空数组 `[]` | 改用 `null` 或省略该字段 |
| 3 | `At least one of filter info and ref info is required` | SetRecordAction/FindRecordAction 缺少定位条件 | 必须提供 `filter_info` 或 `ref_info` 之一 |
| 4 | `client token is empty` | 缺少 `client_token` | 每次请求传入唯一值（时间戳或随机字符串） |
| 5 | `valueType 'text' not allowed for fieldType '3'` | select 类型字段值格式错误 | 改用 `option` 类型 |
| 6 | `Undefined Step Type` | 使用了不支持的 StepType | 使用 `AddRecordTrigger` 而非 `CreateRecordTrigger` |
| 7 | `prompt references an unknown reference from step` | 引用的 stepId 不存在 | 确保引用的 step 在同一 workflow 的 steps 数组中 |
| 8 | `[2200] Internal Error` | 1. steps[].id 重复 2. next/children.links 引用了不存在的 step | 确保所有 step id 唯一；检查引用关系 |
| 9 | 工作流结构不完整 | Branch/Loop 节点缺少 `children` | 仅 Branch（IfElseBranch/SwitchBranch）和 Loop 节点需要 `children`，Trigger/Action 节点无需设置 |
| 10 | 嵌套分支过于复杂 | 多层 IfElseBranch 嵌套 | 3+ 路分支用 SwitchBranch 替代嵌套 IfElseBranch |

### 其他常见错误

**1. condition_list 为空数组**
```json
// ❌ 错误
{ "condition_list": [] }

// ✅ 正确
{ "condition_list": null }
// 或省略该字段
```

**2. filter_info 和 ref_info 同时提供**
```json
// ❌ 错误
{ "filter_info": {...}, "ref_info": {...} }

// ✅ 正确（二选一）
{ "filter_info": {...}, "ref_info": null }
{ "filter_info": null, "ref_info": {...} }
```

**3. 使用字段名而非 fieldId**
```json
// ❌ 错误
{ "value": "$.step_1.客户名称" }

// ✅ 正确
{ "value": "$.step_1.fldXXXXXXXX" }
```

---

## 参考

- [lark-base-workflow-schema.md](lark-base-workflow-schema.md) — 字段定义参考
- [lark-base-workflow-create.md](lark-base-workflow-create.md) — 创建命令
- [lark-base-workflow-update.md](lark-base-workflow-update.md) — 更新命令
