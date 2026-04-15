# base +field-update

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

更新一个已有字段。

## 推荐命令

```bash
lark-cli base +field-update \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --field-id fld_xxx \
  --json '{"name":"状态","type":"select","multiple":false,"options":[{"name":"Todo","hue":"Blue","lightness":"Lighter"},{"name":"Doing","hue":"Orange","lightness":"Light"},{"name":"Done","hue":"Green","lightness":"Light"}]}'

lark-cli base +field-update \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --field-id fld_xxx \
  --json '{"name":"负责人","type":"user","multiple":false,"description":"用于标记记录的直接负责人；协作约定可参考[团队字段约定](https://example.com/field-spec)"}'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--field-id <id_or_name>` | 是 | 字段 ID 或字段名 |
| `--json <body>` | 是 | 字段属性 JSON 对象 |
## API 入参详情

**HTTP 方法和路径：**

```
PUT /open-apis/base/v3/bases/:base_token/tables/:table_id/fields/:field_id
```

## JSON 值规范

- `--json` 必须是 **JSON 对象**，顶层直接传字段定义。
- 更新语义是 `PUT`（全量字段配置更新），不要只传零散片段；至少显式包含 `name`、`type`，并补齐该类型所需关键配置。
- 如需字段说明，直接传 `description`；支持纯文本，也支持 Markdown 链接，如 `协作约定可参考[团队字段约定](https://example.com/field-spec)`。
- `select` 更新时：`options` 仍按对象数组传，避免混入无效字段。
- `link` 更新限制：
  - 不能把非 `link` 字段改成 `link`，也不能把 `link` 改成非 `link`。
  - 现有 `link` 字段的 `bidirectional` 不能改。

**推荐更新示例**

```json
{
  "name": "状态",
  "type": "select",
  "multiple": false,
  "options": [
    { "name": "Todo", "hue": "Blue", "lightness": "Lighter" },
    { "name": "Doing", "hue": "Orange", "lightness": "Light" },
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

- 返回 `field` 和 `updated: true`。

## 工作流


1. 建议先用 `+field-get` 拉现状，再做最小化修改。
2. `formula/lookup` 类型更新前先阅读对应指南。

## 坑点

- ⚠️ 这是全量字段属性更新语义，不是 patch。
- ⚠️ 这是写入操作，执行前必须确认。
- ⚠️ 当 `type` 是 `formula` 或 `lookup` 时，先阅读对应指南再执行。

## 参考

- [lark-base-field.md](lark-base-field.md) — field 索引页
- [lark-base-field-get.md](lark-base-field-get.md) — 查字段
- [lark-base-shortcut-field-properties.md](lark-base-shortcut-field-properties.md) — shortcut 字段 JSON 规范（推荐）
- [formula-field-guide.md](formula-field-guide.md) — formula 指南（更新公式前必读）
- [lookup-field-guide.md](lookup-field-guide.md) — lookup 指南（更新查找引用前必读）
