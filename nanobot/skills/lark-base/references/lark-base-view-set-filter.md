# base +view-set-filter

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

更新筛选配置。

## 推荐命令

```bash
lark-cli base +view-set-filter \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --view-id viw_xxx \
  --json '{"logic":"and","conditions":[["fld_status","intersects",["Doing"]],["fld_owner","intersects",[{"id":"ou_xxx"}]],["fld_end","empty"]]}'
```

## JSON 结构

```json
{
  "logic": "and",
  "conditions": [
    ["fld_status", "intersects", ["Doing"]],
    ["fld_owner", "intersects", [{ "id": "ou_xxx" }]],
    ["fld_end", "empty"]
  ]
}
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--view-id <id_or_name>` | 是 | 视图 ID 或视图名 |
| `--json <body>` | 是 | JSON 对象 |

## API 入参详情

**HTTP 方法和路径：**

```
PUT /open-apis/base/v3/bases/:base_token/tables/:table_id/views/:view_id/filter
```

## 返回重点

- 返回更新后的筛选配置。

## 结构规则

- `logic`：可选，`and` / `or`，默认 `and`
- `conditions`：数组，可为空；每项必须是 `[field, operator, value?]`
- `field`：字段 id 或字段名，长度 `1..100`
- `operator`：`== != > >= < <= intersects disjoint empty non_empty`
- `value`：按字段类型填写；`empty` / `non_empty` 可省略 `value`

### 典型 `value` 形状

- `text` / `location` / `formula`：字符串
- `number` / `auto_number`：数字
- `select`：`["Todo"]`
- `user` / `created_by` / `updated_by`：`[{ "id": "ou_xxx" }]`
- `link`：`[{ "id": "rec_xxx" }]`
- `checkbox`：`true` / `false`
- `datetime` / `created_at` / `updated_at`：`"ExactDate(YYYY-MM-DD)"`、`"Today"`、`"Tomorrow"`、`"Yesterday"`


## JSON Schema（原文）

```json
{"type":"object","properties":{"logic":{"type":"string","enum":["and","or"],"default":"and","description":"Filter Condition Logic"},"conditions":{"type":"array","items":{"type":"array","minItems":3,"maxItems":3,"items":[{"type":"string","minLength":1,"maxLength":100,"description":"Field id or name"},{"type":"string","enum":["==","!=",">",">=","<","<=","intersects","disjoint","empty","non_empty"],"description":"Condition operator"},{"anyOf":[{"not":{}},{"anyOf":[{"anyOf":[{"type":"string","description":"text & formula & location field support string as filter value"},{"type":"number","description":"number & auto_number(the underfly incremental_number) field support number as filter value"},{"type":"array","items":{"type":"string","description":"option name"},"description":"select field support one option: [\"option1\"] or multiple options: `[\"option1\", \"option2\"]` as filter value."},{"type":"array","items":{"type":"object","properties":{"id":{"type":"string","description":"record id"}},"required":["id"],"additionalProperties":false},"description":"link field support record id list as filter value"},{"type":"string","description":"\ndatetime & create_at & updated_at field support relative and absolute filter value.\nabsolute:\n- \"ExactDate(yyyy-MM-dd)\"\nrelative:\n- Today\n- Tomorrow\n- Yesterday\n"},{"type":"array","items":{"type":"object","properties":{"id":{"type":"string","description":"user id"}},"required":["id"],"additionalProperties":false},"description":"user field support user id list as filter value"},{"type":"boolean","description":"checkbox field support boolean as filter value"}]},{"type":"null"}]}]}],"description":"one condition expression. shape: [field_id, filter_operator, value]. when operator is \"empty\" or \"non_empty\", the value is not required."},"default":[]}},"additionalProperties":false,"$schema":"http://json-schema.org/draft-07/schema#"}

```

## 工作流


1. 建议先用 `+view-get-filter` 拉现状，再做最小化修改。

## 坑点

- ⚠️ 这是写入操作，执行前必须确认。
- ⚠️ 条件必须用 tuple，不要再写旧的 `{"field_name":...,"operator":...}` 对象风格。
- ⚠️ `empty` / `non_empty` 不要硬塞 value；`select` / `user` / `link` 也不要直接写单值。
- ⚠️ 日期值要保留 `ExactDate(...)` 外壳，不要直接写裸日期字符串。

## 参考

- [lark-base-view.md](lark-base-view.md) — view 索引页
- [lark-base-view-get-filter.md](lark-base-view-get-filter.md) — 读取筛选
