
# contact +search-user（搜索员工）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

通过关键词搜索员工（姓名/邮箱/手机号等），结果通常按亲密度排序。

本 skill 对应 shortcut：`lark-cli contact +search-user`（底层调用 `GET /open-apis/search/v1/user`）。

## 命令

```bash
# 搜索员工（默认表格输出）
lark-cli contact +search-user --query "张三"

# 分页（取下一页）
lark-cli contact +search-user --query "张三" --page-size 50 --page-token <PAGE_TOKEN>

# 人类可读格式输出
lark-cli contact +search-user --query "张三" --format pretty
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--query <text>` | 是 | 搜索关键词 |
| `--page-size <n>` | 否 | 分页大小（默认 20，最大 200） |
| `--page-token <token>` | 否 | 分页标记（请求下一页） |
| `--format` | 否 | 输出格式：json（默认） \| pretty |

## 常见用法（给 AI）

- 默认输出 JSON，可直接解析获取用户 `open_id`。用 `--format pretty` 查看人类可读格式。
- 如果结果 `has_more=true`，继续传 `page_token` 翻页，不要盲目调大 `page_size`。

## 参考

- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
