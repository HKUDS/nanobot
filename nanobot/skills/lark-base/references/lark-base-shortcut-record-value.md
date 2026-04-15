# base shortcut record JSON 规范（lark-base-shortcut-record-value）

> 适用命令：`lark-cli base +record-upsert`

本文件定义 **shortcut 写记录** 时 `--json` 的推荐格式，目标是让 AI 一次写对。

## 1. 顶层规则（必须遵守）

- `--json` 必须是 JSON 对象。
- 顶层直接传字段映射：`{"字段名或字段ID": 值}`。
- 一次 payload 里同一字段只用一种 key（字段名或字段 ID），不要重复。
- 写入前先 `+field-list` 获取字段 `type/style/multiple`，再构造值。

## 2. 各类型值格式与示例

### 2.1 text / phone / url

**推荐值**：字符串。

```json
{
    "标题": "Hello",
    "联系电话": "1380000000000",
    "官网": "https://example.com"
}
```

**Schema**

```json
{ "type": "string", "description": "text field cell, example: \"one string and [one url](https://foo.bar)\"" }
```

### 2.2 number

**推荐值**：数字。

```json
{
    "工时": 12.5,
    "预算": 3000
}
```

**Schema**

```json
{ "type": "number", "description": "number field cell, can be any float64 value" }
```

### 2.3 select（单选/多选/阶段）

**推荐值**：
- 单选：字符串
- 多选：字符串数组

```json
{
    "状态": "Todo",
    "标签": ["后端", "高优"]
}
```

**Schema**

```json
{ "type": "array", "items": { "type": "string", "description": "option name" }, "description": "select field cell, example: [\"option_1\", \"option_2\"]" }
```

### 2.4 datetime

**推荐值**：`YYYY-MM-DD HH:mm:ss` 字符串（稳妥写法）。

```json
{
    "截止时间": "2026-03-24 10:00:00"
}
```

**Schema**

```json
{ "type": "string", "description": "datetime field cell. accepts common datetime strings and timestamp-like values. Prefer \"YYYY-MM-DD HH:mm:ss\" in requests because it is the most stable format and matches the API output. Example: \"2026-01-01 19:30:00\"" }
```

### 2.5 checkbox

**推荐值**：布尔值。

```json
{
    "已完成": true
}
```

**Schema**

```json
{ "type": "boolean", "description": "checkbox field cell" }
```

### 2.6 user

**推荐值**：对象数组，元素至少有 `id`。

```json
{
    "负责人": [
      { "id": "ou_xxx" }
    ]
}
```

**Schema**

```json
{ "type": "array", "items": { "type": "object", "properties": { "id": { "type": "string", "description": "user id" } }, "required": ["id"], "additionalProperties": false }, "description": "user field cell, example: [{\"id\": \"ou_123\"}]" }
```

### 2.7 link

**推荐值**：对象数组，元素至少有 `id`。

```json
{
    "关联任务": [
      { "id": "rec_xxx" }
    ]
}
```

**Schema**

```json
{ "type": "array", "items": { "type": "object", "properties": { "id": { "type": "string", "description": "record id" } }, "required": ["id"], "additionalProperties": false }, "description": "link field cell, example: [{\"id\": \"rec_123\"}]" }
```

### 2.8 location

**推荐值**：对象 `{lng, lat}`。

```json
{
    "坐标": {
      "lng": 116.397428,
      "lat": 39.90923
    }
}
```

**Schema**

```json
{
  "type": "object",
  "properties": { "lng": { "type": "number", "description": "Longitude" }, "lat": { "type": "number", "description": "Latitude" } },
  "required": ["lng", "lat"],
  "additionalProperties": false,
  "description": "location field cell, example: {\"lng\": 113.94765, \"lat\": 22.528533}"
}
```

### 2.9 attachment

对 agent 而言，附件上传是**特殊链路**：如果用户要把本地文件加到记录里，必须使用 `lark-cli base +record-upload-attachment` 上传到已有记录。

**Schema - attachment**

```json
{
  "type": "array",
  "items": { "type": "object", "properties": { "file_token": { "type": "string", "minLength": 0, "maxLength": 50 }, "name": { "type": "string", "minLength": 1, "maxLength": 255 } }, "required": ["file_token", "name"], "additionalProperties": false },
  "description": "attachment field cell. For agent, do not synthesize this payload via +record-upsert; must use +record-upload-attachment to upload files."
}
```

## 3. 只读字段（不要写）

以下字段在写记录时应视为只读：
- `auto_number`
- `lookup`
- `formula`
- `created_time` / `modified_time`
- `created_by` / `modified_by`

## 4. 快速可用完整示例

```json
{
    "标题": "Created from shortcut",
    "状态": "Todo",
    "标签": ["高优", "外部依赖"],
    "工时": 8,
    "截止时间": "2026-03-24 10:00:00",
    "已完成": false,
    "负责人": [{ "id": "ou_123" }],
    "关联任务": [{ "id": "rec_456" }],
    "坐标": { "lng": 116.397428, "lat": 39.90923 }
}
```
