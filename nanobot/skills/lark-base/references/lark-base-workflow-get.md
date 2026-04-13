# base +workflow-get

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。
> 💡 **按需查阅：** 如需深入理解返回的 `steps` 节点结构，可参考 [workflow-schema.md](lark-base-workflow-schema.md)。简单统计（如节点数量）无需阅读 schema。

获取一个 workflow 的完整定义，包括标题、状态、所有步骤（steps）及其配置。

## 推荐命令

```bash
# 基本用法
lark-cli base +workflow-get \
  --base-token BascXxxxxx \
  --workflow-id wkfxxxxxx

# 指定用户 ID 类型（creator_id / updater_id 字段的格式）
lark-cli base +workflow-get \
  --base-token BascXxxxxx \
  --workflow-id wkfxxxxxx \
  --user-id-type open_id
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 多维表格 Base Token，以 `Basc` 开头 |
| `--workflow-id <id>` | 是 | Workflow ID，以 `wkf` 开头 |
| `--user-id-type <type>` | 否 | 控制 `creator_id` / `updater_id` 字段返回的用户 ID 格式；枚举值：`open_id`（默认）、`union_id`、`user_id` |

## 如何从链接中提取参数

用户通常会提供如下 URL（在 Base 的自动化管理页面复制）：

```
https://xxx.feishu.cn/base/<base_token>?table=<table_id>&view=<view_id>
```

- `--base-token`：取 `/base/` 后面的字符串（`Basc` 开头）
- `--workflow-id`：以 `wkf` 开头，可从 `+workflow-list` 的输出中获取，URL 上通常不直接暴露

## API 入参详情

**HTTP 方法和路径：**

```
GET /open-apis/base/v3/bases/:base_token/workflows/:workflow_id
```

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | 多维表格 Base Token |
| `workflow_id` | 是 | Workflow ID（`wkf` 开头） |

**Query 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `user_id_type` | 否 | 用户 ID 类型：`open_id` / `union_id` / `user_id` |

**Request Body：** 无

## API 出参详情

**Response `data` 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `workflow_id` | string | Workflow 唯一标识，`wkf` 开头 |
| `title` | string | Workflow 标题 |
| `status` | string | 状态：`enabled`（已启用）/ `disabled`（已停用） |
| `creator_id` | string | 创建人 ID（格式受 `user_id_type` 控制） |
| `updater_id` | string | 最后修改人 ID |
| `create_time` | string | 创建时间（Unix 时间戳，秒） |
| `update_time` | string | 最后更新时间（Unix 时间戳，秒） |
| `steps` | []step | 步骤列表，见下方 |

**steps 元素字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 步骤唯一 ID |
| `type` | string | 步骤类型，见 [workflow-schema.md](lark-base-workflow-schema.md) |
| `title` | string | 步骤标题 |
| `children` | object | 子关系边，`children.links[]` 承担分支/循环/slot 连线，结构见 schema |
| `children.links[].kind` | string | 关系类型：`if_true` / `if_false` / `case` / `loop_start` / `slot` |
| `children.links[].to` | string | 目标节点 ID |
| `children.links[].label` | string | 可选标签（如 `branch_1`、`tool`） |
| `children.links[].desc` | string | 可选语义说明 |
| `next` | string \| null | 线性后继节点 ID；`null` 表示流程结束 |
| `data` | object | 步骤详细配置，结构随 `type` 变化，见 [workflow-schema.md](lark-base-workflow-schema.md) |
| `meta` | object | 扩展元信息，仅 `APIHubAction` / `AIAgentLLMAction` / `AIAgentMCPAction` 等子节点有值 |

> 步骤类型（`type`）的完整枚举和每种类型的 `data` 字段结构，参见 [lark-base-workflow-schema.md](lark-base-workflow-schema.md)。

## 返回值

命令成功后输出 JSON：

```json
{
  "ok": true,
  "data": {
    "workflow_id": "wkfxxxxxx",
    "title": "新订单自动通知",
    "status": "enabled",
    "creator_id": "ou_xxxx",
    "updater_id": "ou_xxxx",
    "create_time": "1704067200",
    "update_time": "1704153600",
    "steps": [
      {
        "id": "trigger_1",
        "type": "AddRecordTrigger",
        "title": "监控新订单",
        "next": "action_1",
        "data": { "table_name": "订单表", "watched_field_name": "订单号" }
      },
      {
        "id": "action_1",
        "type": "LarkMessageAction",
        "title": "发送通知",
        "next": null,
        "data": { "..." : "..." }
      }
    ]
  }
}
```

## 坑点

- ⚠️ **workflow_id 来源**：`workflow_id` 以 `wkf` 开头，从 `+workflow-list` 命令输出中获取；URL 上通常拿不到，不要把 `table_id`（`tbl` 开头）误当成 `workflow_id`
- ⚠️ **steps 可能为空**：未配置任何步骤的 workflow 返回的 `steps` 为空数组，不代表接口异常
- ⚠️ **文档中 `title` 字段类型标注为 int**：这是文档笔误，实际为 string
- ⚠️ **API 路径版本**：本接口使用 `base/v3`，路径必须从原始文档提取，禁止用 WebSearch 补全，否则会拿到错误路径导致 `[2200] Internal Error`
- ⚠️ **只读接口，GET 请求 body 传 nil**：`baseV3Call` 的 body 参数传 `nil` 是正确的，不同于 PATCH/POST 写接口

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-base-workflow-schema.md](lark-base-workflow-schema.md) — Workflow 步骤数据结构完整参考
- [lark-base-workflow-list.md](lark-base-workflow-list.md) — 列出所有 workflow（可用来获取 workflow_id）
- [lark-base-workflow-create.md](lark-base-workflow-create.md) — 创建 workflow
- [lark-base-workflow-update.md](lark-base-workflow-update.md) — 更新 workflow
