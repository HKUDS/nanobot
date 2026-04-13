# base +view-set-group

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

更新分组配置。

## 推荐命令

```bash
lark-cli base +view-set-group \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --view-id viw_xxx \
  --json '{"group_config":[{"field":"fldStatus","desc":false}]}'
```

## JSON 结构

```json
{
  "group_config": [
    { "field": "fldStatus", "desc": false }
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
PUT /open-apis/base/v3/bases/:base_token/tables/:table_id/views/:view_id/group
```

## 返回重点

- 返回更新后的分组配置。

## 结构规则

- `group_config`：数组，长度 `0..3`
- 每项：
  - `field`：字段 id 或字段名，长度 `1..100`
  - `desc`：可选，默认 `false`


## JSON Schema（原文）

```json
{"type":"object","properties":{"group_config":{"type":"array","items":{"type":"object","properties":{"field":{"type":"string","minLength":1,"maxLength":100,"description":"Field id or name"},"desc":{"type":"boolean","default":false,"description":"define how to sort group headers"}},"required":["field"],"additionalProperties":false},"minItems":0,"maxItems":3}},"required":["group_config"],"additionalProperties":false,"$schema":"http://json-schema.org/draft-07/schema#"}

```

## 工作流


1. 优先用字段 id，避免同名字段和后续改名影响。

## 坑点

- ⚠️ 这是写入操作，执行前必须确认。
- ⚠️ 分组只支持 `grid` / `kanban` / `gantt`。
- ⚠️ `group_config` 最多 3 项，超出会直接失败。

## 参考

- [lark-base-view.md](lark-base-view.md) — view 索引页
- [lark-base-view-get-group.md](lark-base-view-get-group.md) — 读取分组
