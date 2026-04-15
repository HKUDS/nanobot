# base +table-list

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

分页列出一个 Base 下的数据表。

## 推荐命令

```bash
lark-cli base +table-list \
  --base-token app_xxx \
  --offset 0 \
  --limit 50
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--offset <n>` | 否 | 分页偏移，默认 `0` |
| `--limit <n>` | 否 | 分页大小，默认 `50`，范围 `1-100` |

## API 入参详情

**HTTP 方法和路径：**

```
GET /open-apis/base/v3/bases/:base_token/tables
```

## 返回重点

- 返回 `items / offset / limit / count / total`。
- `items` 会被简化为 `table_id` 和 `table_name`。

## 坑点

- ⚠️ `+table-list` 禁止并发调用；批量列多个 Base 时必须串行。

## 参考

- [lark-base-table.md](lark-base-table.md) — table 索引页
