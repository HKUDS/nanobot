---
name: feishu-approval-leave
description: 通过飞书审批 API v4 创建/查询/撤回请假审批实例。当用户需要提交请假申请、查询审批状态、撤回审批时使用此技能。支持年假、事假、病假、调休假、婚假、产假、陪产假、丧假、哺乳假等假期类型。
---

# 飞书请假审批

通过飞书审批 API v4 创建/查询/撤回请假审批实例。

## 配置

通过系统环境变量配置飞书应用凭据（与其他飞书 skill 共用）：

```bash
export NANOBOT_CHANNELS__FEISHU__APP_ID=cli_xxx
export NANOBOT_CHANNELS__FEISHU__APP_SECRET=xxx
```

## 审批模板编码

请假审批使用固定的模板编码，**无需向用户询问**：

```
approval_code = "E565EC28-57C7-461C-B7ED-1E2D838F4878"
```

此编码对应组织内的「请假」审批流程，所有请假类型（年假、事假、病假等）共用同一个模板。

## 前置条件

- 环境变量已配置飞书 App ID / App Secret
- 已知申请人的 open_id（飞书用户唯一标识，格式如 `ou_xxxxxxxxxxxx`）

## 使用方式

运行 `scripts/feishu_approval_leave.py`，支持四个子命令：`create`、`get`、`cancel`、`list`。

### 1. 创建请假审批 (create)

**Python API:**
```python
from feishu_approval_leave import create_leave_approval

APPROVAL_CODE = "E565EC28-57C7-461C-B7ED-1E2D838F4878"

result = create_leave_approval(
    approval_code=APPROVAL_CODE,
    user_id="ou_xxxxxxxxxxxx",
    leave_type="年假",
    start_time="2026-03-11T09:00:00+08:00",
    end_time="2026-03-11T18:00:00+08:00",
    reason="请假事由",
    unit="DAY"
)
```

**命令行:**
```bash
python scripts/feishu_approval_leave.py create \
  --user-id ou_xxxxxxxxxxxx \
  --leave-type 年假 \
  --start-time "2026-03-11T09:00:00+08:00" \
  --end-time "2026-03-11T18:00:00+08:00" \
  --reason "请假事由"
```

### 2. 获取审批实例详情 (get)

**命令行:**
```bash
python scripts/feishu_approval_leave.py get \
  --instance-code 983DE237-3ED0-4649-80AE-332471ADA41A
```

### 3. 撤回审批实例 (cancel)

**命令行:**
```bash
python scripts/feishu_approval_leave.py cancel \
  --instance-code 983DE237-3ED0-4649-80AE-332471ADA41A \
  --user-id ou_xxxxxxxxxxxx \
  --reason "撤销申请"
```

### 4. 批量获取审批实例 (list)

**命令行:**
```bash
python scripts/feishu_approval_leave.py list \
  --approval-code E565EC28-57C7-461C-B7ED-1E2D838F4878 \
  --start-time "1773100000000" \
  --end-time "1773400000000" \
  --user-id ou_xxxxxxxxxxxx
```

## 关键注意事项

1. **form 必须是 JSON 字符串数组**，使用 `json.dumps(form_array)` 序列化，不是直接传对象
2. **时间格式必须为 RFC3339**，如 `2026-03-11T09:00:00+08:00`（不能用 `2026-03-11 09:00:00`）
3. 使用 `tenant_access_token`，不需要 `user_access_token`
4. 限额假期类型会检查余额，不足时创建失败
5. **user_id 参数实际使用 open_id 值**（企业可能未配置自定义 user_id）
6. **撤回接口 URL 必须包含 `user_id_type=open_id` 参数**：
   ```
   POST /open-apis/approval/v4/instances/cancel?user_id_type=open_id
   ```
7. **list 接口返回字段是 `instance_code_list`**（字符串数组），不是 `items`
8. **list 接口时间参数必须是毫秒时间戳**（13 位），单次查询范围不超过 10 小时

## 修复记录

**2026-03-11** - list 接口修复：
- 问题：API 返回字段是 `instance_code_list`，脚本误用 `items`
- 修复：修改 `list_approval_instances()` 函数读取正确字段
- 验证：查询到 10 条历史审批记录

## 测试验证

所有功能已通过测试（2026-03-11）：

```bash
# ✅ 创建审批实例
python scripts/feishu_approval_leave.py create \
  --user-id ou_xxxx \
  --leave-type 事假 \
  --start-time "2026-03-14T09:00:00+08:00" \
  --end-time "2026-03-14T18:00:00+08:00" \
  --reason "测试 user_id_type"
# 输出：✅ 审批实例创建成功
#        实例码：AEAB3A49-AE4F-44D8-AB36-2A3A5B34961F

# ✅ 撤回审批实例
python scripts/feishu_approval_leave.py cancel \
  --instance-code AEAB3A49-AE4F-44D8-AB36-2A3A5B34961F \
  --user-id ou_xxxx \
  --reason "测试撤回"
# 输出：✅ 审批实例已撤回

# ✅ 获取审批详情
python scripts/feishu_approval_leave.py get \
  --instance-code 983DE237-3ED0-4649-80AE-332471ADA41A
# 输出：✅ 审批实例详情（包含状态、请假类型、时间等）

# ✅ 批量列表
python scripts/feishu_approval_leave.py list \
  --approval-code E565EC28-57C7-461C-B7ED-1E2D838F4878 \
  --start-time "1773100000000" \
  --end-time "1773400000000" \
  --user-id ou_xxxx
# 输出：✅ 审批实例列表（包含实例码、状态、创建时间等）
```

## 假期类型

| 名称 | leave_id |
|------|----------|
| 年假 | 7138673249737506817 |
| 事假 | 7138673250187935772 |
| 病假 | 7138673250640347138 |
| 调休假 | 7138673251139731484 |
| 婚假 | 7138673251697475612 |
| 产假 | 7138673252143726594 |
| 陪产假 | 7138673252595236865 |
| 丧假 | 7138673253106663426 |
| 哺乳假 | 7138673253534695425 |

## 参考资料

- 假期类型列表、完整参数说明、错误码：见 [references/api-guide.md](references/api-guide.md)
- 飞书官方文档：
  - 创建实例：https://open.feishu.cn/document/server-docs/approval-v4/instance/create
  - 获取详情：https://open.feishu.cn/document/server-docs/approval-v4/instance/get
  - 撤回实例：https://open.feishu.cn/document/server-docs/approval-v4/instance/cancel
  - 批量列表：https://open.feishu.cn/document/server-docs/approval-v4/instance/list
