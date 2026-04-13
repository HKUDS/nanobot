# base shortcut field JSON 规范（lark-base-shortcut-field-properties）

> 适用命令：`lark-cli base +field-create`、`lark-cli base +field-update`

本文件定义 **shortcut 写字段** 时 `--json` 的推荐格式，避免 AI 混用旧版 `type=数字 + field_name + property` 结构。

## 1. 顶层规则（必须遵守）

- `--json` 必须是 JSON 对象。
- 顶层统一使用：`type` + `name` + 类型特有字段。
- 如需字段说明，直接传 `description`；支持纯文本，也支持 Markdown 链接。
- 不要使用旧结构：`field_name`、`property`、`ui_type`、数字枚举 `type`。
- `+field-update` 是 `PUT` 语义，建议先 `+field-get` 再全量提交目标字段配置。
- `type=formula` 或 `type=lookup` 创建时，必须先读对应 guide。

```json
{
  "type": "text",
  "name": "需求背景",
  "description": "记录需求背景与已知约束；填写口径可参考[说明模板](https://example.com/spec)"
}
```

## 2. 各类型格式与示例

### 2.1 text

**要求**：`name` 必填；可选传 `description`；`style.type` 可选，默认 `plain`。

```json
{
  "type": "text",
  "name": "标题",
  "style": { "type": "plain" }
}
```

`style.type` 常用值：`plain`、`phone`、`url`、`email`、`barcode`。

**Schema**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "const": "text", "description": "Text field type" },
    "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" },
    "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" },
    "style": {
      "type": "object",
      "properties": { "type": { "type": "string", "enum": ["plain", "phone", "url", "email", "barcode"], "description": "Text style type" } },
      "required": ["type"],
      "additionalProperties": false,
      "description": "Text style",
      "default": { "type": "plain" }
    }
  },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "Text field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

### 2.2 number

**要求**：`name` 必填；`style.type` 常用 `plain/currency/progress/rating`。

```json
{
  "type": "number",
  "name": "工时",
  "style": {
    "type": "plain",
    "precision": 2,
    "percentage": false,
    "thousands_separator": true
  }
}
```

```json
{
  "type": "number",
  "name": "预算",
  "style": { "type": "currency", "precision": 2, "currency_code": "CNY" }
}
```

```json
{
  "type": "number",
  "name": "完成度",
  "style": { "type": "progress", "percentage": true, "color": "Blue" }
}
```

```json
{
  "type": "number",
  "name": "评分",
  "style": { "type": "rating", "icon": "star", "min": 1, "max": 5 }
}
```

**Schema**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "const": "number", "description": "Number field type" },
    "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" },
    "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" },
    "style": {
      "anyOf": [
        {
          "type": "object",
          "properties": {
            "type": { "type": "string", "const": "plain", "description": "Plain style type" },
            "precision": { "type": "number", "minimum": 0, "maximum": 4, "default": 2, "description": "Decimal precision" },
            "percentage": { "type": "boolean", "default": false, "description": "Use percentage" },
            "thousands_separator": { "$ref": "#/properties/style/anyOf/0/properties/percentage", "default": false, "description": "Use thousand separator" }
          },
          "required": ["type"],
          "additionalProperties": false,
          "description": "Plain number style"
        },
        {
          "type": "object",
          "properties": {
            "type": { "type": "string", "const": "currency", "description": "Currency style type" },
            "precision": { "type": "number", "minimum": 0, "maximum": 4, "default": 2, "description": "Decimal precision" },
            "currency_code": {
              "type": "string",
              "enum": ["CNY", "USD", "EUR", "GBP", "AED", "AUD", "BRL", "CAD", "CHF", "HKD", "INR", "IDR", "JPY", "KRW", "MOP", "MXN", "MYR", "PHP", "PLN", "RUB", "SGD", "THB", "TRY", "TWD", "VND"],
              "default": "CNY",
              "description": "Currency code"
            }
          },
          "required": ["type"],
          "additionalProperties": false,
          "description": "Currency style"
        },
        {
          "type": "object",
          "properties": {
            "type": { "type": "string", "const": "progress", "description": "Progress style type" },
            "percentage": { "$ref": "#/properties/style/anyOf/0/properties/percentage", "default": true, "description": "Use percentage" },
            "color": {
              "type": "string",
              "enum": ["Blue", "Purple", "DarkGreen", "Green", "Cyan", "Orange", "Red", "Gray", "WhiteToBlueGradient", "WhiteToPurpleGradient", "WhiteToOrangeGradient", "GreedToRedGradient", "RedToGreenGradient", "BlueToPinkGradient", "PinkToBlueGradient", "SpectralGradient"],
              "description": "Progress color"
            }
          },
          "required": ["type", "color"],
          "additionalProperties": false,
          "description": "Progress style"
        },
        {
          "type": "object",
          "properties": {
            "type": { "type": "string", "const": "rating", "description": "Rating style type" },
            "icon": { "type": "string", "enum": ["star", "heart", "thumbsup", "fire", "smile", "lightning", "flower", "number"], "default": "star", "description": "Rating icon" },
            "min": { "type": "integer", "minimum": 0, "maximum": 1, "default": 1, "description": "Minimum rating" },
            "max": { "type": "integer", "minimum": 1, "maximum": 10, "default": 5, "description": "Maximum rating" }
          },
          "required": ["type"],
          "additionalProperties": false,
          "description": "Rating style"
        }
      ],
      "default": { "type": "plain" },
      "description": "Number style"
    }
  },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "Number field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

### 2.3 select（单选/多选）

**要求**：`name` 必填；`multiple` 控制单/多选；`options` 为对象数组。

```json
{
  "type": "select",
  "name": "状态",
  "multiple": false,
  "options": [
    { "name": "Todo", "hue": "Blue", "lightness": "Lighter" },
    { "name": "Done", "hue": "Green", "lightness": "Light" }
  ]
}
```

- `options[].name` 必填。
- `options` 不要传 `id`（创建场景由后端生成）。

**Schema**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "const": "select", "description": "Select field type" },
    "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" },
    "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" },
    "multiple": { "type": "boolean", "default": false, "description": "Allow multiple" },
    "options": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": { "type": "string", "description": "Option name" },
          "hue": { "type": "string", "enum": ["Red", "Orange", "Yellow", "Lime", "Green", "Turquoise", "Wathet", "Blue", "Carmine", "Purple", "Gray"], "description": "Option hue", "default": "Blue" },
          "lightness": { "type": "string", "enum": ["Lighter", "Light", "Standard", "Dark", "Darker"], "description": "Option lightness", "default": "Lighter" }
        },
        "required": ["name"],
        "additionalProperties": false,
        "description": "Select option"
      },
      "maxItems": 10000,
      "description": "Static options"
    }
  },
  "required": ["type", "name", "options"],
  "additionalProperties": false,
  "description": "Select field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

### 2.4 datetime / created_at / updated_at

**要求**：`name` 必填；`style.format` 可选。

```json
{
  "type": "datetime",
  "name": "截止时间",
  "style": { "format": "yyyy-MM-dd HH:mm" }
}
```

```json
{ "type": "created_at", "name": "创建时间", "style": { "format": "yyyy/MM/dd" } }
```

```json
{ "type": "updated_at", "name": "更新时间", "style": { "format": "yyyy/MM/dd HH:mm" } }
```

**Schema - datetime**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "const": "datetime", "description": "Date time type" },
    "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" },
    "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" },
    "style": {
      "type": "object",
      "properties": { "format": { "type": "string", "enum": ["yyyy/MM/dd", "yyyy/MM/dd HH:mm", "yyyy/MM/dd HH:mm Z", "yyyy-MM-dd", "yyyy-MM-dd HH:mm", "yyyy-MM-dd HH:mm Z", "MM-dd", "MM/dd/yyyy", "dd/MM/yyyy"], "default": "yyyy/MM/dd", "description": "Date format" } },
      "additionalProperties": false,
      "default": { "format": "yyyy/MM/dd" },
      "description": "Date time style"
    }
  },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "Date time field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

**Schema - created_at**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "const": "created_at", "description": "Created time type" },
    "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" },
    "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" },
    "style": {
      "type": "object",
      "properties": { "format": { "type": "string", "enum": ["yyyy/MM/dd", "yyyy/MM/dd HH:mm", "yyyy/MM/dd HH:mm Z", "yyyy-MM-dd", "yyyy-MM-dd HH:mm", "yyyy-MM-dd HH:mm Z", "MM-dd", "MM/dd/yyyy", "dd/MM/yyyy"], "default": "yyyy/MM/dd", "description": "Date format" } },
      "additionalProperties": false,
      "default": { "format": "yyyy/MM/dd" },
      "description": "Created time style"
    }
  },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "Created time field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

**Schema - updated_at**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "const": "updated_at", "description": "Modified time type" },
    "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" },
    "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" },
    "style": {
      "type": "object",
      "properties": { "format": { "type": "string", "enum": ["yyyy/MM/dd", "yyyy/MM/dd HH:mm", "yyyy/MM/dd HH:mm Z", "yyyy-MM-dd", "yyyy-MM-dd HH:mm", "yyyy-MM-dd HH:mm Z", "MM-dd", "MM/dd/yyyy", "dd/MM/yyyy"], "default": "yyyy/MM/dd", "description": "Date format" } },
      "additionalProperties": false,
      "default": { "format": "yyyy/MM/dd" },
      "description": "Modified time style"
    }
  },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "Modified time field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

### 2.5 user / created_by / updated_by

```json
{ "type": "user", "name": "负责人", "multiple": true }
```

```json
{ "type": "created_by", "name": "创建人" }
```

```json
{ "type": "updated_by", "name": "更新人" }
```

**Schema - user**

```json
{
  "type": "object",
  "properties": { "type": { "type": "string", "const": "user", "description": "User field type" }, "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" }, "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" }, "multiple": { "type": "boolean", "default": true, "description": "Allow multiple" } },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "User field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

**Schema - created_by**

```json
{
  "type": "object",
  "properties": { "type": { "type": "string", "const": "created_by", "description": "Created by type" }, "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" }, "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" } },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "Created by field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

**Schema - updated_by**

```json
{
  "type": "object",
  "properties": { "type": { "type": "string", "const": "updated_by", "description": "Modified by type" }, "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" }, "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" } },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "Modified by field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

### 2.6 link

**要求**：`link_table` 必填；`bidirectional` 默认 `false`。

```json
{
  "type": "link",
  "name": "关联任务",
  "link_table": "任务表",
  "bidirectional": true,
  "bidirectional_link_field_name": "反向关联"
}
```

**Schema**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "const": "link", "description": "Link field type" },
    "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" },
    "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" },
    "link_table": { "type": "string", "minLength": 1, "maxLength": 100, "description": "Linked table" },
    "bidirectional": { "type": "boolean", "default": false, "description": "Bidirectional link" },
    "bidirectional_link_field_name": { "$ref": "#/properties/name", "description": "Bidirectional link field name" }
  },
  "required": ["type", "name", "link_table"],
  "additionalProperties": false,
  "description": "Link field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

### 2.7 formula

**要求**：`expression` 必填。

```json
{
  "type": "formula",
  "name": "合计",
  "expression": "1+1"
}
```

**Schema**

```json
{
  "type": "object",
  "properties": { "type": { "type": "string", "const": "formula", "description": "Formula field type" }, "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" }, "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" }, "expression": { "type": "string", "description": "Formula expression" } },
  "required": ["type", "name", "expression"],
  "additionalProperties": false,
  "description": "Formula field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

### 2.8 lookup

**要求**：`from`、`select`、`where` 必填；`aggregate` 可选。`where.logic` 仅支持 `and/or`，`conditions` 每项必须是三元组 `[field, op, value]`。

```json
{
  "type": "lookup",
  "name": "状态汇总",
  "from": "任务表",
  "select": "状态",
  "where": {
    "logic": "and",
    "conditions": [
      ["负责人", "==", { "type": "field_ref", "field": "当前负责人" }],
      ["状态", "non_empty", null]
    ]
  },
  "aggregate": "raw_value"
}
```

**Schema**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "const": "lookup", "description": "Lookup field type" },
    "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" },
    "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" },
    "from": { "type": "string", "minLength": 1, "maxLength": 100, "description": "Source data table" },
    "select": { "type": "string", "minLength": 1, "maxLength": 100, "description": "Field to aggregate from source table" },
    "where": {
      "type": "object",
      "properties": {
        "logic": { "type": "string", "enum": ["and", "or"], "default": "and", "description": "Filter Condition Logic" },
        "conditions": {
          "type": "array",
          "items": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": [
              { "type": "string", "minLength": 1, "maxLength": 100, "description": "Field from source table to filter on" },
              { "type": "string", "enum": ["==", "!=", ">", ">=", "<", "<=", "intersects", "disjoint", "empty", "non_empty"], "description": "Condition operator" },
              {
                "anyOf": [
                  {
                    "anyOf": [
                      {
                        "type": "object",
                        "properties": {
                          "type": { "type": "string", "const": "constant" },
                          "value": {
                            "anyOf": [
                              { "type": "string", "description": "text & formula & location field support string as filter value" },
                              { "type": "number", "description": "number & auto_number(the underfly incremental_number) field support number as filter value" },
                              { "type": "array", "items": { "type": "string", "description": "option name" }, "description": "select field support one option: [\"option1\"] or multiple options: `[\"option1\", \"option2\"]` as filter value." },
                              { "type": "array", "items": { "type": "object", "properties": { "id": { "type": "string", "description": "record id" } }, "required": ["id"], "additionalProperties": false }, "description": "link field support record id list as filter value" },
                              { "type": "string", "description": "\ndatetime & create_at & updated_at field support relative and absolute filter value.\nabsolute:\n- \"ExactDate(yyyy-MM-dd)\"\nrelative:\n- Today\n- Tomorrow\n- Yesterday\n" },
                              { "type": "array", "items": { "type": "object", "properties": { "id": { "type": "string", "description": "user id" } }, "required": ["id"], "additionalProperties": false }, "description": "user field support user id list as filter value" },
                              { "type": "boolean", "description": "checkbox field support boolean as filter value" }
                            ]
                          }
                        },
                        "required": ["type", "value"],
                        "additionalProperties": false,
                        "description": "Constant filter value"
                      },
                      {
                        "type": "object",
                        "properties": { "type": { "type": "string", "const": "field_ref" }, "field": { "type": "string", "minLength": 1, "maxLength": 100, "description": "Field id or name" } },
                        "required": ["type", "field"],
                        "additionalProperties": false,
                        "description": "Dynamic field reference from current table"
                      }
                    ]
                  },
                  { "type": "null" }
                ],
                "description": "Condition value (null for isEmpty/isNotEmpty)"
              }
            ],
            "description": "Lookup condition tuple: [fieldRef, operator, value?]"
          },
          "minItems": 1,
          "description": "Filter conditions"
        }
      },
      "required": ["conditions"],
      "additionalProperties": false
    },
    "aggregate": { "type": "string", "enum": ["raw_value", "sum", "average", "counta", "unique_counta", "max", "min", "unique"], "default": "raw_value", "description": "Aggregation function" }
  },
  "required": ["type", "name", "from", "select", "where"],
  "additionalProperties": false,
  "description": "Lookup field. You MUST Read xxx document first!",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

### 2.9 auto_number

```json
{
  "type": "auto_number",
  "name": "编号",
  "style": {
    "rules": [
      { "type": "text", "text": "TASK-" },
      { "type": "incremental_number", "length": 4 }
    ]
  }
}
```

**Schema**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "const": "auto_number", "description": "Auto number type" },
    "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" },
    "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" },
    "style": {
      "type": "object",
      "properties": {
        "rules": {
          "type": "array",
          "items": {
            "anyOf": [
              {
                "type": "object",
                "properties": { "type": { "type": "string", "const": "text", "description": "Text rule type" }, "text": { "type": "string", "description": "Prefix text" } },
                "required": ["type", "text"],
                "additionalProperties": false,
                "description": "Auto number text rule"
              },
              {
                "type": "object",
                "properties": { "type": { "type": "string", "const": "incremental_number", "description": "Increment rule type" }, "length": { "type": "integer", "minimum": 1, "maximum": 9, "description": "Serial length" } },
                "required": ["type", "length"],
                "additionalProperties": false,
                "description": "Auto number increment rule"
              },
              {
                "type": "object",
                "properties": {
                  "type": { "type": "string", "const": "created_time", "description": "Date rule type(auto fill record created date)" },
                  "date_format": { "type": "string", "enum": ["yyyyMMdd", "yyyyMM", "yyMM", "MMdd", "yyyy", "MM", "dd"], "description": "Date format" }
                },
                "required": ["type", "date_format"],
                "additionalProperties": false,
                "description": "Auto number date rule"
              }
            ]
          },
          "minItems": 1,
          "maxItems": 9,
          "description": "Numbering rules"
        }
      },
      "required": ["rules"],
      "additionalProperties": false,
      "default": {
        "rules": [
          { "type": "text", "text": "NO." },
          { "type": "incremental_number", "length": 3 }
        ]
      },
      "description": "Auto number style"
    }
  },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "Auto number field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

### 2.10 attachment / location / checkbox

```json
{ "type": "attachment", "name": "附件" }
```

```json
{ "type": "location", "name": "位置" }
```

```json
{ "type": "checkbox", "name": "完成" }
```

**Schema - attachment**

```json
{
  "type": "object",
  "properties": { "type": { "type": "string", "const": "attachment", "description": "Attachment field type" }, "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" }, "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" } },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "Attachment field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

**Schema - location**

```json
{
  "type": "object",
  "properties": { "type": { "type": "string", "const": "location", "description": "Location field type" }, "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" }, "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" } },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "Location field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

**Schema - checkbox**

```json
{
  "type": "object",
  "properties": { "type": { "type": "string", "const": "checkbox", "description": "Checkbox field type" }, "name": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "Field name" }, "description": { "type": "string", "description": "Field description; supports plain text or Markdown links" } },
  "required": ["type", "name"],
  "additionalProperties": false,
  "description": "Checkbox field",
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

## 3. 推荐工作流

1. `+field-list` / `+field-get` 先拿当前字段结构。
2. 按本规范构造 `--json`。
3. `type=formula/lookup` 时先读对应 guide，再创建。
