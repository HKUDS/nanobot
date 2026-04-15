# base +view-set-visible-fields

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

更新视图可见字段列表（同时控制视图中的字段顺序）。

## 推荐命令

```bash
lark-cli base +view-set-visible-fields \
  --base-token XXXXXX \
  --table-id tblXXX \
  --view-id vewXXX \
  --json '{"visible_fields":["标题","fldXXX"]}'
```

## JSON 结构

```json
{
  "visible_fields": ["标题", "fldXXX"]
}
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--view-id <id_or_name>` | 是 | 视图 ID 或视图名 |
| `--json <body>` | 是 | JSON 对象，且必须包含 `visible_fields` |

## API 入参详情

**HTTP 方法和路径：**

```
PUT /open-apis/base/v3/bases/:base_token/tables/:table_id/views/:view_id/visible_fields
```

**接口 body 格式：**

```json
{
  "visible_fields": ["标题", "fldXXX"]
}
```

## 返回重点

- 返回可见字段列表与顺序（`primaryField` 会被强制置顶）。

## 结构规则

- `visible_fields`：字符串数组，每项可传字段 id 或字段名
- 数组顺序用于控制视图字段顺序；主字段 `primaryField` 必须存在且位于第一位，否则 API 会强制将其提升到第一位
- `--json` 必须传对象：`{ "visible_fields": [...] }`

## 工作流

1. 用户要求“改字段顺序”或“设置可见字段”时，直接使用本命令。
2. 建议优先使用字段 id，避免字段重名或后续改名带来的歧义。

## 坑点

- ⚠️ 这是写入操作，执行前必须确认。
- ⚠️ 接口最终结果会受后端 `primaryField` 强制显示规则影响，返回顺序可能与传入数组不同。
- ⚠️ 如果传字段名，必须与当前表真实字段名精确匹配。

## 参考

- [lark-base-view.md](lark-base-view.md) — view 索引页
