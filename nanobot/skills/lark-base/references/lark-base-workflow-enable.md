# base +workflow-enable

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

启用 Base 中的一个自动化工作流。

## 推荐命令

```bash
lark-cli base +workflow-enable \
  --base-token BascXxxxxx \
  --workflow-id wkfxxxxxx
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 多维表格 Base Token（`Basc` 开头） |
| `--workflow-id <id>` | 是 | 工作流 ID（`wkf` 开头） |

## 如何从链接中提取参数

用户通常会提供如下 URL：

```
https://example.feishu.cn/base/<base_token>?table=<table_or_workflow_id>
```

- `--base-token`：取 `/base/` 后面的字符串（`Basc` 开头）
- `--workflow-id`：取 `?table=` 后面的值，当其以 `wkf` 开头时即为 workflow_id

> ⚠️ **注意区分 ID 前缀**：table_id 以 `tbl` 开头，workflow_id 以 `wkf` 开头，两者在 URL 的 `?table=` 参数里都会出现，需要根据前缀判断。

## API 入参详情

**HTTP 方法和路径：**

```
PATCH /open-apis/base/v3/bases/:base_token/workflows/:workflow_id/enable
```

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | 多维表格 Base Token |
| `workflow_id` | 是 | 工作流唯一标识 |

**Request Body：** 无

## API 出参详情

**Response `data` 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `workflow_id` | string | 工作流唯一标识符 |
| `status` | string | 操作后的最新状态，固定为 `enabled` |

## 返回值

```json
{
  "ok": true,
  "data": {
    "workflow_id": "wkfxxxxxx",
    "status": "enabled"
  }
}
```

## 工作流

> [!CAUTION]
> 这是**写入操作** — 执行前必须向用户确认。

1. 向用户确认 `--base-token` 和 `--workflow-id`
2. 执行命令
3. 报告返回的 `status` 字段，确认值为 `enabled`

## 坑点

- ⚠️ **workflow_id 来源**：workflow_id 以 `wkf` 开头，从 URL 的 `?table=wkf...` 参数提取，不是表格的 table_id（`tbl` 开头），混淆会导致 `[2200] Internal Error`
- ⚠️ **API 路径末尾动词**：`/enable` 是路径的最后一段，不是 body 字段；漏掉这个后缀会命中错误接口
- ⚠️ **PATCH body 不能为 nil**：接口虽无请求体，仍需传 `{}` 空对象，否则服务端可能返回 `server time out error`
- ⚠️ **scope 待确认**：内部文档未列出权限名称，代码中使用 `base:workflow:update`，如遇 `[230013] permission denied` 需核对实际 scope

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-base-workflow-disable](lark-base-workflow-disable.md) — 禁用工作流
- [lark-base-workflow-list](lark-base-workflow-list.md) — 列出全部工作流
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
