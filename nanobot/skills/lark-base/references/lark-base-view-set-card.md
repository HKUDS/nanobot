# base +view-set-card

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

更新卡片配置。

## 推荐命令

```bash
lark-cli base +view-set-card \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --view-id viw_xxx \
  --json {"cover_field":"fld_cover"}
```

## JSON 结构

```json
{
  "cover_field": "fld_cover"
}
```

```json
{
  "cover_field": null
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
PUT /open-apis/base/v3/bases/:base_token/tables/:table_id/views/:view_id/card
```

## 返回重点

- 返回更新后的卡片配置。

## 结构规则

- `cover_field`：必填，字段 id 或字段名，长度 `1..100`；也可以显式传 `null`
- 非 `null` 时，字段必须是封面支持字段，实际就是 `attachment` 字段
- 传 `null` 表示清空封面配置


## JSON Schema（原文）

```json
{"type":"object","properties":{"cover_field":{"anyOf":[{"type":"string","minLength":1,"maxLength":100,"description":"Field id or name"},{"type":"null"}],"description":"cover field id or name. must be a attachment field"}},"required":["cover_field"],"additionalProperties":false,"$schema":"http://json-schema.org/draft-07/schema#"}

```

## 工作流


1. 建议先用 `+view-get-card` 拉现状，再修改。

## 坑点

- ⚠️ 这是写入操作，执行前必须确认。
- ⚠️ 只支持 `gallery` / `kanban`。
- ⚠️ `cover_field` 不是任何字段都能填，普通文本/数字字段会直接报错。
- ⚠️ 清空封面必须传 `null`，不要传空字符串。

## 参考

- [lark-base-view.md](lark-base-view.md) — view 索引页
- [lark-base-view-get-card.md](lark-base-view-get-card.md) — 读取卡片
