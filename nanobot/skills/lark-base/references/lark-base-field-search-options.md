# base +field-search-options

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

搜索单选 / 多选字段的候选项。

## 推荐命令

```bash
lark-cli base +field-search-options \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --field-id fld_status \
  --keyword 已完成 \
  --offset 0 \
  --limit 30
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--field-id <id_or_name>` | 是 | 字段 ID 或字段名 |
| `--keyword <text>` | 否 | 查询关键字；会映射到 API 的 `query` |
| `--offset <n>` | 否 | 分页偏移，默认 `0` |
| `--limit <n>` | 否 | 分页大小，默认 `30` |

## API 入参详情

**HTTP 方法和路径：**

```
GET /open-apis/base/v3/bases/:base_token/tables/:table_id/fields/:field_id/options
```

## 返回重点

- 返回 `options`、`total`、以及回显的 `field_id / field_name / keyword`。

## 坑点

- ⚠️ 只适用于带选项集的字段；普通文本 / 数字字段没有可搜索选项。

## 参考

- [lark-base-field.md](lark-base-field.md) — field 索引页
