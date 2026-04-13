# base +workflow-create

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

在 Base 中创建一个新的自动化工作流。新建后状态为 `disabled`，需调用 `+workflow-enable` 才能启用。

## ⚠️ 执行前必读

创建工作流前请按顺序完成：

1. **先读本文档**，了解 `--json` 参数格式和 `client_token` 的必填要求
2. **阅读 [workflow-guide.md](lark-base-workflow-guide.md)**，获取 Loop、IfElseBranch、SwitchBranch 等**完整示例**
3. **参考 [workflow-schema.md](lark-base-workflow-schema.md)**，查询具体字段定义
4. **不需要先调用 `+workflow-list`**，创建操作不依赖现有工作流列表
5. **按需调用 `+table-list` 和 `+field-list`** 获取表名和字段名（只在需要时调用）
6. **若遇到单多选字段，可调用`+field-get`命令**来获取选项详情
7. **调用命令时，请将 body 数据直接通过 --json 传入，禁止创建任何的临时文件，即禁止使用 --json @filename**

**常见错误**:
- ❌ 缺少 `client_token` → 报错: `client token is empty`
- ❌ 猜测 StepType → 报错: `unknown step type 'CreateTrigger'`（应该是 `AddRecordTrigger`）
- ❌ 字段引用路径错误 → 报错: `prompt references an unknown reference`

> 💡 **提示**: 复杂场景（循环、分支、多步骤组合）的完整示例请直接阅读 [workflow-guide.md](lark-base-workflow-guide.md)，本文档只包含基础用法。

## 推荐命令

```bash
lark-cli base +workflow-create \
  --base-token BascXxxxxx \
  --json '{"client_token":"1704067200","title":"新订单自动通知","steps":[{"id":"trigger_1","type":"AddRecordTrigger","title":"监控新订单","next":"action_1","data":{"table_name":"订单表","watched_field_name":"订单号"}},{"id":"action_1","type":"LarkMessageAction","title":"发送通知","next":null,"data":{"receiver":[{"value_type":"user","value":{"id":"ou_xxxx"}}],"send_to_everyone":false,"title":[{"value_type":"text","value":"新订单提醒"}],"content":[{"value_type":"text","value":"收到新订单"}],"btn_list":[]}}]}'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 多维表格 Base Token（`Basc` 开头） |
| `--json <body>` | 是 | 工作流 body JSON，包含 `title` 和 `steps` |

## 如何从链接中提取参数

用户通常会提供如下 URL：

```
https://example.feishu.cn/base/<base_token>
```

- `--base-token`：取 `/base/` 后面的字符串（`Basc` 开头）

## API 入参详情

**HTTP 方法和路径：**

```
POST /open-apis/base/v3/bases/:base_token/workflows
```

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | 多维表格 Base Token |

**Request Body（JSON）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `client_token` | string | **是** | 幂等键，每次创建必须传一个唯一随机值（如时间戳 `"1704067200"`），防重复提交，缺失会报错 |
| `title` | string | 否 | 工作流标题 |
| `steps` | WorkflowStep[] | 否 | 步骤列表 |
| `user_id_type` | string | 否 | 用户 ID 类型：`open_id` / `union_id` / `user_id`，默认 `open_id` |

> **步骤数据结构非常复杂，详见 [lark-base-workflow-schema.md](lark-base-workflow-schema.md)**

**Request Body 示例：**
```json
{
  "client_token": "124131231421312312",
  "title": "新订单自动通知",
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

## API 出参详情

**Response `data` 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `workflow_id` | string | 新建工作流的唯一 ID（`wkf` 开头） |
| `title` | string | 工作流标题 |
| `status` | string | 工作流状态，新建固定为 `disabled` |
| `steps` | WorkflowStep[] | 完整步骤列表 |
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
    "title": "新订单自动通知",
    "status": "disabled",
    "steps": [...],
    "creator_id": "ou_xxxx",
    "updater_id": "ou_xxxx",
    "create_time": 1704067200,
    "update_time": 1704067200
  }
}
```

## 工作流

> [!CAUTION]
> 这是**写入操作** — 执行前必须向用户确认。

1. 与用户确认 `--base-token` 和工作流定义（`--json` 内容）
2. 执行命令，报告返回的 `workflow_id`（`wkf` 开头）
3. 提示用户：新建工作流初始状态为 `disabled`，需调用 `+workflow-enable --workflow-id <返回的 workflow_id>` 才会生效

## 坑点

> ⚠️ **【重要】client_token 必传**：缺失会返回 `[code=800004006] client token is empty`，这**不是权限问题**，是 **JSON body 缺字段**。每次请求传唯一值即可（如 `"$(date +%s)"` 或 `"1743078000"`）

- ⚠️ **新建后默认禁用**：`status` 固定返回 `disabled`，需要额外调用 `+workflow-enable` 才能让工作流生效；不要误报"创建成功即启用"
- ⚠️ **steps 中 id 字段必须唯一**：每个步骤的 `id` 由调用方指定，且在工作流内必须唯一；`next` 和 `children.links[].to` 引用的 ID 必须在同一 steps 数组中存在，否则服务端返回 `[2200] Internal Error`
- ⚠️ **字段类型校验**：设置字段值时，`value_type` 必须与字段实际类型匹配：
   - **select 类型字段**（单选/多选/流程）：必须用 `option`，不能用 `text`
     ```json
     // ✅ 正确
     { "field_name": "大区", "value": [{"value_type": "option", "value": {"name": "华东"}}] }
     // ❌ 错误 - 会报错 valueType 'text' not allowed for fieldType '3'
     { "field_name": "大区", "value": [{"value_type": "text", "value": "华东"}] }
     ```
   - **SetRecordTrigger 的 field_watch_info** 同样受此限制，select 类型字段的 value 必须用 `option`
     常见 action 输出：`FindRecordAction` → `$.step_id.recordNum`（记录数）、`$.step_id.fieldRecords`（查找到的记录列表）；`AddRecordAction` → `$.step_id.recordId`
- ⚠️ **权限不足**：如遇 `permission denied`，先确认当前身份（bot 或 user）是否对该 Base 有编辑权限，再检查 scope 是否已开通。参考 [lark-shared](../../lark-shared/SKILL.md) 中的权限不足处理流程
- ⚠️ **user_id_type**：涉及用户的 `value_type: "user"` 的 value 字段传 OpenID，服务端会根据 `user_id_type`（默认 `open_id`）解析；如需传 `user_id` 格式需在 body 里显式声明 `"user_id_type": "user_id"`

## 参考

- [lark-base-workflow-schema.md](lark-base-workflow-schema.md) — 完整 Workflow 数据结构
- [lark-base-workflow-update](lark-base-workflow-update.md) — 全量更新工作流
- [lark-base-workflow-enable](lark-base-workflow-enable.md) — 启用工作流
- [lark-base-workflow-list](lark-base-workflow-list.md) — 列出全部工作流
- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
