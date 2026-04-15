# base +view-create

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

创建一个或多个视图。

## 推荐命令

```bash
lark-cli base +view-create \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --json '{"name":"进行中","type":"grid"}' 

lark-cli base +view-create \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --json '[{"name":"进行中","type":"grid"},{"name":"日历","type":"calendar"}]'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--json <body>` | 是 | 视图 JSON 对象或数组 |

## API 入参详情

**HTTP 方法和路径：**

```
POST /open-apis/base/v3/bases/:base_token/tables/:table_id/views
```

## 返回重点

- 总是返回 `views` 数组；即使只创建了一个视图也一样。

## 关键规则

- `type` 仅支持 `grid` `kanban` `gallery` `calendar` `gantt`。
- `/views` 不接受 `type=form`；表单创建走 `/forms`。
- `name` 必填，长度 `1..100`，且同表内必须唯一。

## JSON 结构（`--json`）

支持单对象或对象数组：

```json
{ "name": "进行中", "type": "grid" }
```

```json
[
  { "name": "进行中", "type": "grid" },
  { "name": "日历", "type": "calendar" }
]
```


## JSON Schema（原文）

```json
{"type":"object","properties":{"type":{"type":"string","enum":["grid","kanban","gallery","gantt","calendar"],"default":"grid","description":"view type"},"name":{"type":"string","minLength":1,"maxLength":100,"description":"View name"}},"required":["name"],"additionalProperties":false,"$schema":"http://json-schema.org/draft-07/schema#"}

```

## 工作流


1. 多视图批量创建时，优先用数组一次提交，减少重复调用。
2. 如果用户要“查看视图字段顺序”或“查看可见字段”，使用 `+view-get-visible-fields` 读取当前 `visible_fields`。
3. 如果用户同时要求“视图字段顺序”或“可见字段”，创建完成后必须继续调用 `+view-set-visible-fields` 设置 `visible_fields`；`+view-create` 本身不负责字段顺序/可见性配置。

## 坑点

- ⚠️ 这是写入操作，执行前必须确认。

## 参考

- [lark-base-view.md](lark-base-view.md) — view 索引页
