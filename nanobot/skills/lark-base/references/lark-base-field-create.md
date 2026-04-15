# base +field-create

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

创建一个字段。

## Agent 最小工作流

1. 先判断是不是 `formula` / `lookup`。
2. 如果是：先读对应 guide。
3. 没读 guide 前，不要直接创建 formula / lookup 字段。
4. 读完 guide 后，再构造 `--json` 并创建字段。
5. 如果是跨表 formula / lookup，再补查**目标表**的结构。

## 推荐命令

```bash
lark-cli base +field-create \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --json '{"name":"预算","type":"number","precision":2}' 

lark-cli base +field-create \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --json '{"name":"状态","type":"select","multiple":false,"options":[{"name":"Todo","hue":"Blue","lightness":"Lighter"},{"name":"Done","hue":"Green","lightness":"Light"}]}'

lark-cli base +field-create \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --json '{"name":"负责人","type":"user","multiple":false,"description":"用于标记记录的直接负责人；协作约定可参考[团队字段约定](https://example.com/field-spec)"}'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--json <body>` | 是 | 字段属性 JSON 对象 |
## API 入参详情

**HTTP 方法和路径：**

```
POST /open-apis/base/v3/bases/:base_token/tables/:table_id/fields
```

## JSON 值规范

- `--json` 必须是 **JSON 对象**，顶层直接传字段定义，不要再套一层。
- 顶层最少包含：`name`、`type`。
- 如需字段说明，直接传 `description`；支持纯文本，也支持 Markdown 链接，如 `协作约定可参考[团队字段约定](https://example.com/field-spec)`。
- `type` 不同，必填子字段不同：
  - `select`：用 `multiple` + `options`（`options` 里只传 `name/hue/lightness`，不要传 `id`）。
  - `link`：必须有 `link_table`，可选 `bidirectional`、`bidirectional_link_field_name`。
  - `formula`：必须有 `expression`；先读 formula guide，再创建。
  - `lookup`：必须有 `from`、`select`、`where`；先读 lookup guide，再创建。

**正确（base +field-create）**

```json
{
  "name": "状态",
  "type": "select",
  "multiple": false,
  "options": [
    { "name": "Todo", "hue": "Blue", "lightness": "Lighter" },
    { "name": "Done", "hue": "Green", "lightness": "Light" }
  ]
}
```

**字段说明示例**

```json
{
  "name": "负责人",
  "type": "user",
  "multiple": false,
  "description": "用于标记记录的直接负责人；协作约定可参考[团队字段约定](https://example.com/field-spec)"
}
```

## 返回重点

- 返回 `field` 和 `created: true`。

## 工作流


1. formula / lookup 字段必须先阅读对应指南；没读之前不要直接创建。

## 坑点

- ⚠️ 这是写入操作，执行前必须确认。
- ⚠️ 当 `type` 是 `formula` 或 `lookup` 时，先读对应 guide，再创建。

## 参考

- [lark-base-field.md](lark-base-field.md) — field 索引页
- [lark-base-shortcut-field-properties.md](lark-base-shortcut-field-properties.md) — shortcut 字段 JSON 规范（推荐）
- [formula-field-guide.md](formula-field-guide.md) — formula 指南（创建公式必读）
- [lookup-field-guide.md](lookup-field-guide.md) — lookup 指南（创建查找引用必读）
