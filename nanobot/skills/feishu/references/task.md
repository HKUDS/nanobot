# 任务管理 (Task)

任务 CRUD 使用 v1 API（全面支持 `tenant_access_token`），任务清单使用 v2 API。

## API 函数

### task_create

创建任务。v1 API 要求 `origin` 字段，函数已内置默认值。

```python
from feishu_api import task_create

data = task_create(
    summary="完成季度报告",
    description="包含 Q1 数据汇总",
    due={"time": "1710500000", "timezone": "Asia/Shanghai"},
    collaborator_ids=["ou_xxx"],
    follower_ids=["ou_yyy"],
)
# data["task"] -> {id, summary, description, due, collaborators, followers, ...}
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py task create --summary "完成季度报告" --description "Q1数据"
```

### task_get

获取任务详情。

```python
from feishu_api import task_get

data = task_get("task_id_xxx")
# data["task"] -> {id, summary, description, due, complete_time, collaborators, ...}
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py task get --task-id xxx
```

### task_list

获取任务列表。使用 `tenant_access_token` 时，返回该应用通过 `task_create` 创建的所有任务。

```python
from feishu_api import task_list

data = task_list(page_size=50, completed=False)
# data["items"] -> [{id, summary, ...}]
# data["has_more"], data["page_token"]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py task list --limit 50
```

### task_update

更新任务（PATCH 语义，只更新传入的字段）。

```python
from feishu_api import task_update

task_update("task_id_xxx", {"summary": "新标题", "description": "新描述"})
```

### task_complete

完成任务。

```python
from feishu_api import task_complete

task_complete("task_id_xxx")
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py task complete --task-id xxx
```

### tasklist_create

创建任务清单（v2 API）。

```python
from feishu_api import tasklist_create

data = tasklist_create("本周待办")
# data["tasklist"] -> {guid, name, ...}
```

### tasklist_list

获取任务清单列表（v2 API）。

```python
from feishu_api import tasklist_list

data = tasklist_list()
# data["items"] -> [{guid, name, ...}]
```

### tasklist_add_task

将任务添加到清单（v2 API）。

```python
from feishu_api import tasklist_add_task

tasklist_add_task("task_guid", "tasklist_guid")
```

## 成员角色

| 参数 | 含义 |
|------|------|
| collaborator_ids | 执行者（open_id 列表） |
| follower_ids | 关注者（open_id 列表） |

## v1 与 v2 API 选择说明

| 操作 | 使用版本 | 原因 |
|------|---------|------|
| task_create/get/list/update/complete | v1 | v1 全面支持 `tenant_access_token` |
| tasklist_create/list/add_task | v2 | v2 独有功能，支持 `tenant_access_token` |

Task v2 的 GET 类接口（list、get）**不支持** `tenant_access_token`，只接受 `user_access_token`，
因此任务 CRUD 统一使用 v1 以避免此限制。

## 所需权限

| 权限 | 用途 | 适用接口 |
|------|------|---------|
| task:task | 任务完整权限（读写） | task_create/update/complete |
| task:task:readonly | 任务只读 | task_list/get |
| task:tasklist:read | 读取任务清单 | tasklist_list |
| task:tasklist:write | 管理任务清单 | tasklist_create/add_task |
