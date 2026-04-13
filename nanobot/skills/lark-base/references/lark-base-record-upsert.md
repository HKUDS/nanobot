# base +record-upsert

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

创建记录，或在带 `--record-id` 时更新记录。

## 推荐命令

```bash
lark-cli base +record-upsert \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --json '{"项目名称":"Apollo","状态":"进行中"}' 

lark-cli base +record-upsert \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --record-id rec_xxx \
  --json '{"项目名称":"Apollo","状态":"进行中","标签":["高优","外部依赖"],"截止日期":"2026-03-24 10:00:00"}'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--record-id <id>` | 否 | 传入时走更新，不传时走创建 |
| `--json <body>` | 是 | 记录 JSON 对象 |

## API 入参详情

**HTTP 方法和路径：**

```
POST /open-apis/base/v3/bases/:base_token/tables/:table_id/records
```

- 带 `--record-id` 时内部改走 `PATCH /records/:record_id`。

## JSON 值规范

- `--json` 必须是 **JSON 对象**。
- key 可用字段名或字段 ID，但一次请求里同一字段只用一种标识，避免重复写入冲突。
- value 必须匹配字段类型；先 `+field-list` 再构造值。
- 推荐值形状（常用）：
  - 文本：`"标题"`
  - 数字：`12.5`
  - 单选：`"Todo"`
  - 多选：`["A","B"]`
  - 复选框：`true`
  - 人员：`[{"id":"ou_xxx"}]`
  - 关联记录：`[{"id":"rec_xxx"}]`
  - 日期：`"YYYY-MM-DD HH:mm:ss"`（如 `"2026-03-24 10:00:00"`）
- 需要清空字段时优先传 `null`（字段允许清空时）。
- 公式、查找引用、创建/更新时间、创建/修改人等只读字段不要写入。

**正确（base +record-upsert）**

```json
{
  "项目名称": "Apollo",
  "状态": "进行中",
  "标签": ["高优", "外部依赖"],
  "负责人": [{ "id": "ou_xxx" }],
  "截止日期": "2026-03-24 10:00:00"
}
```

## 返回重点

- 创建时返回 `record` 和 `created: true`。
- 更新时返回 `record` 和 `updated: true`。

## 工作流


1. 先确定是新增还是修改。

## 坑点

- ⚠️ `--json` 必须是对象，不支持数组。
- ⚠️ 有 `--record-id` 就一定走更新；不传就一定走创建，不会自动查重。
- ⚠️ 这是写入操作，执行前必须确认。

## 参考

- [lark-base-record.md](lark-base-record.md) — record 索引页
- [lark-base-shortcut-record-value.md](lark-base-shortcut-record-value.md) — shortcut 记录值格式规范（推荐）
