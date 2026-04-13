# base +workflow-list

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

列出 Base 中所有自动化工作流，自动分页获取全量数据。

## 推荐命令

```bash
# 列出全部工作流
lark-cli base +workflow-list \
  --base-token BascXxxxxx

# 只看已启用的工作流
lark-cli base +workflow-list \
  --base-token BascXxxxxx \
  --status enabled

# 只看已禁用的工作流
lark-cli base +workflow-list \
  --base-token BascXxxxxx \
  --status disabled
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 多维表格 Base Token（`Basc` 开头） |
| `--status <value>` | 否 | 过滤状态：`enabled` 或 `disabled`；不传则返回全部 |
| `--page-size <n>` | 否 | 每页大小，默认 100，最大 100 |

## API 入参详情

**HTTP 方法和路径：**

```
POST /open-apis/base/v3/bases/:base_token/workflows/list
```

> ⚠️ **注意：列表接口用 POST**，不是 GET。

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | 多维表格 Base Token |

**Request Body（JSON）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page_size` | int | 否 | 分页大小，默认 20，最大 100 |
| `page_token` | string | 否 | 分页标记，首次请求不填，翻页时传上一页返回的 `page_token` |
| `status` | string | 否 | 过滤状态：`enabled` / `disabled` |

## API 出参详情

**Response `data` 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `has_more` | boolean | 是否还有更多数据 |
| `page_token` | string | 下一页 token（`has_more` 为 true 时返回） |
| `total` | int | 符合条件的工作流总数 |
| `items` | []object | 工作流列表 |
| `items[].workflow_id` | string | 工作流唯一标识（`wkf` 开头） |
| `items[].title` | string | 工作流标题 |
| `items[].status` | string | 当前状态：`enabled` / `disabled` |
| `items[].trigger_type` | string | 触发器类型，如 `AddRecordTrigger` |
| `items[].creator_id` | string | 创建人的 open_id |
| `items[].updater_id` | string | 最后修改人的 open_id |
| `items[].create_time` | int | 创建时间，Unix 秒级时间戳 |
| `items[].update_time` | int | 最后更新时间，Unix 秒级时间戳 |

## 返回值

命令成功后输出 JSON（已合并所有分页）：

```json
{
  "ok": true,
  "data": {
    "items": [
      {
        "workflow_id": "wkfxxxxxx",
        "title": "自动发送通知",
        "status": "enabled",
        "trigger_type": "AddRecordTrigger",
        "creator_id": "ou_xxxxx",
        "updater_id": "ou_yyyyy",
        "create_time": 1704067200,
        "update_time": 1704153600
      }
    ],
    "total": 1
  }
}
```

## ⚡ 性能提示
### 场景适用性
**✅ 需要先 list 的场景**:
- 批量操作：启用/停用多个工作流（先 list，再批量 enable/disable）
- 查询统计：统计定时触发的工作流数量（先 list，再筛选）
- 修改操作：修改指定名称的工作流（先 list ，从列表中找到对应名称工作流的 workflow_id，再 get/update）
  **❌ 不需要先 list 的场景**:
- **创建工作流**：直接调用 `+workflow-create`，不需要先 list
- 查看指定工作流详情：如果已知 workflow_id，直接 `+workflow-get`
### 缓存策略
同一会话中处理多个工作流时，只需调用一次 `+workflow-list` 获取全部结果，然后从中筛选所需的工作流，避免重复查询。

## 坑点

- ⚠️ **列表用 POST 不用 GET**：`/workflows/list` 是 POST 接口，`page_token` 放在 Request Body 里而不是 Query 参数，常见误区
- ⚠️ **workflow_id 前缀 `wkf`**：返回的 `workflow_id` 以 `wkf` 开头，传给 `+workflow-enable` / `+workflow-disable` 时直接使用即可，不要和 table_id（`tbl` 开头）混淆
- ⚠️ **scope 待确认**：内部文档未列出权限名，代码使用 `base:workflow:read`，如遇 `[230013] permission denied` 需核对实际 scope

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-base-workflow-enable-disable](lark-base-workflow-enable-disable.md) — 启用/禁用工作流
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
