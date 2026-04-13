# base +view-set-timebar

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

更新时间轴配置。

## 推荐命令

```bash
lark-cli base +view-set-timebar \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --view-id viw_xxx \
  --json {"start_time":"fld_start","end_time":"fld_end","title":"fld_title"}
```

## JSON 结构

```json
{
  "start_time": "fld_start",
  "end_time": "fld_end",
  "title": "fld_title"
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
PUT /open-apis/base/v3/bases/:base_token/tables/:table_id/views/:view_id/timebar
```

## 返回重点

- 返回更新后的时间轴配置。

## 结构规则

- `start_time`：必填，字段 id 或字段名，长度 `1..100`
- `end_time`：必填，字段 id 或字段名，长度 `1..100`
- `title`：必填，字段 id 或字段名，长度 `1..100`
- `start_time` / `end_time` 必须是时间条支持的日期类字段；当前以 `datetime` / `created_at` 这类字段为准，优先传字段 id
- `title` 通常传主字段，用来显示条目标题


## JSON Schema（原文）

```json
{"type":"object","properties":{"start_time":{"type":"string","minLength":1,"maxLength":100,"description":"start time field id or name (must be a datetime/created_at field)"},"end_time":{"type":"string","minLength":1,"maxLength":100,"description":"end time field id or name (must be a datetime/created_at field)"},"title":{"type":"string","minLength":1,"maxLength":100,"description":"title datasource field id or name"}},"required":["start_time","end_time","title"],"additionalProperties":false,"$schema":"http://json-schema.org/draft-07/schema#"}

```

## 工作流


1. 建议先用 `+view-get-timebar` 拉现状，再修改。

## 坑点

- ⚠️ 这是写入操作，执行前必须确认。
- ⚠️ 只支持 `calendar` / `gantt`。
- ⚠️ `start_time` 和 `end_time` 不能填普通文本、选项或链接字段。
- ⚠️ 字段不存在或类型不对会直接失败，不要靠猜。

## 参考

- [lark-base-view.md](lark-base-view.md) — view 索引页
- [lark-base-view-get-timebar.md](lark-base-view-get-timebar.md) — 读取时间轴
