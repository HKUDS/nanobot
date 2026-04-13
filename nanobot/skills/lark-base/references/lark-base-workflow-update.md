# base +workflow-update

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

全量替换 Base 中一个已有工作流的定义（`title` 和/或 `steps`）。使用 PUT 语义，传入的内容会完整覆盖原有定义。

## ⚠️ 执行前必读

更新工作流前请按顺序完成：

1. **先读本文档**，了解 `--json` 参数格式和 PUT 全量覆盖的语义
2. **阅读 [workflow-guide.md](lark-base-workflow-guide.md)**，获取 Loop、IfElseBranch、SwitchBranch 等**完整示例**（与创建场景共用相同的步骤结构）
3. **参考 [workflow-schema.md](lark-base-workflow-schema.md)**，查询具体字段定义
4. **按需调用 `+workflow-list`** 获取工作流 ID（`wkf` 开头）
5. **如需基于现有工作流修改**，先调用 `+workflow-get` 导出当前定义，在此基础上修改

## 推荐命令

```bash
lark-cli base +workflow-update \
  --base-token BascXxxxxx \
  --workflow-id wkfosaYTS1V6rhjF \
  --json '{"title":"新标题","steps":[{"id":"trigger_1","type":"AddRecordTrigger","title":"监控新订单","next":"action_1","data":{"table_name":"订单表","watched_field_name":"订单号"}},{"id":"action_1","type":"LarkMessageAction","title":"发送通知","next":null,"data":{"receiver":[{"value_type":"user","value":{"id":"ou_xxxx"}}],"send_to_everyone":false,"title":[{"value_type":"text","value":"新订单提醒"}],"content":[{"value_type":"text","value":"收到新订单"}],"btn_list":[]}}]}'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 多维表格 Base Token（`Basc` 开头） |
| `--workflow-id <id>` | 是 | 工作流 ID（`wkf` 开头），可从 `+workflow-list` 获取 |
| `--json <body>` | 是 | 工作流 body JSON，包含 `title` 和/或 `steps`|

## 如何从链接中提取参数

用户通常会提供如下 URL：

```
https://example.feishu.cn/base/<base_token>?table=<table_or_workflow_id>
```

- `--base-token`：取 `/base/` 后面的字符串（`Basc` 开头）
- `--workflow-id`：取 `?table=` 后面的值，当其以 `wkf` 开头时即为 workflow_id

> ⚠️ **注意区分 ID 前缀**：table_id 以 `tbl` 开头，workflow_id 以 `wkf` 开头。

## API 入参详情

**HTTP 方法和路径：**

```
PUT /open-apis/base/v3/bases/:base_token/workflows/:workflow_id
```

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | 多维表格 Base Token |
| `workflow_id` | 是 | 工作流唯一标识（`wkf` 开头） |

**Request Body（JSON）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | 否 | 工作流标题 |
| `steps` | WorkflowStep[] | 否 | 步骤列表（PUT 语义，全量替换） |
| `user_id_type` | string | 否 | 用户 ID 类型：`open_id` / `union_id` / `user_id`，默认 `open_id` |

> **步骤数据结构非常复杂，详见 [lark-base-workflow-schema.md](lark-base-workflow-schema.md)**

**Request Body 示例：**

```json
{
  "title": "新订单自动通知（更新版）",
  "steps": [
    {
      "id": "trigger_1",
      "type": "AddRecordTrigger",
      "title": "监控新订单",
      "next": "action_1",
      "data": {
        "table_name": "订单表",
        "watched_field_name": "订单号"
      }
    },
    {
      "id": "action_1",
      "type": "LarkMessageAction",
      "title": "发送通知",
      "next": null,
      "data": {
        "receiver": [{ "value_type": "user", "value": {"id": "ou_xxxx"} }],
        "send_to_everyone": false,
        "title": [{ "value_type": "text", "value": "新订单提醒" }],
        "content": [
          { "value_type": "text", "value": "收到新订单，客户：" },
          { "value_type": "ref", "value": "$.trigger_1.fldCustomerName" }
        ],
        "btn_list": []
      }
    }
  ]
}
```

> **注意**：Trigger 和 Action 节点不应设置 `children` 字段，只有 Branch（如 IfElseBranch、SwitchBranch）和 System（如 Loop）节点才需要 `children` 来描述分支或循环结构。

## API 出参详情

**Response `data` 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `workflow_id` | string | 工作流唯一 ID（`wkf` 开头） |
| `title` | string | 更新后的工作流标题 |
| `status` | string | 当前状态：`enabled` / `disabled` |
| `steps` | WorkflowStep[] | 完整步骤列表（更新后） |
| `creator_id` | string | 创建人 OpenID |
| `updater_id` | string | 最后修改人 OpenID |
| `create_time` | number | 创建时间（Unix 秒级时间戳） |
| `update_time` | number | 更新时间（Unix 秒级时间戳） |

## 返回值

```json
{
  "ok": true,
  "data": {
    "workflow_id": "wkfosaYTS1V6rhjF",
    "title": "新订单自动通知（更新版）",
    "status": "disabled",
    "steps": [...],
    "creator_id": "ou_xxxx",
    "updater_id": "ou_yyyy",
    "create_time": 1704067200,
    "update_time": 1704153600
  }
}
```

## 工作流

> [!CAUTION]
> 这是**写入操作** — 执行前必须向用户确认。PUT 语义，会**完整覆盖**原有工作流定义。

1. 确认 `--base-token` 和 `--workflow-id`（建议先用 `+workflow-list` 查出 ID）
2. 确认 `--json` 的完整内容 — PUT 会全量覆盖，漏传 `steps` 会清空所有步骤
3. 执行命令，报告返回的 `workflow_id` 和 `update_time`

## 坑点

- ⚠️ **PUT 是全量覆盖**：传什么就写什么；如果只传 `title` 不传 `steps`，原有 steps 会被清空；如需只改标题，使用 PATCH 接口（目前无对应 shortcut，可参考 API 文档直接调用）
- ⚠️ **workflow_id 前缀**：以 `wkf` 开头，从 URL 的 `?table=wkf...` 提取；和 table_id（`tbl` 开头）混淆会导致 `[2200] Internal Error`
- ⚠️ **steps 中 id 字段必须唯一**：每个步骤的 `id` 在同一工作流内必须唯一；`next` 和 `children.links[].to` 引用的 ID 必须在 steps 数组中存在
- ⚠️ **更新不影响 enabled 状态**：`+workflow-update` 不会改变工作流的 `enabled/disabled` 状态；需要另外调用 `+workflow-enable` / `+workflow-disable`

## 参考

- [lark-base-workflow-schema.md](lark-base-workflow-schema.md) — Workflow 数据结构参考
- [lark-base-workflow-guide.md](lark-base-workflow-guide.md) — **完整示例、构造技巧、常见错误**
- [lark-base-workflow-create](lark-base-workflow-create.md) — 创建工作流
- [lark-base-workflow-enable](lark-base-workflow-enable.md) — 启用工作流
- [lark-base-workflow-list](lark-base-workflow-list.md) — 列出全部工作流
- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
