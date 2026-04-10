---
name: feishu-task
description: 飞书任务管理 — 任务 CRUD、任务清单管理。当用户提及飞书任务、创建任务、任务清单、待办、todo、task时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 飞书任务管理 (Task)

任务 CRUD 使用 v1 API（全面支持 `tenant_access_token`），任务清单使用 v2 API。

## 使用流程

1. 根据下方 API 函数说明确认所需操作
2. 通过 `exec` 工具调用脚本执行

## API 函数

### task_create

创建任务（v1 API，要求 `origin` 字段，函数已内置默认值）。

```
python3 scripts/feishu_task.py create --summary "完成季度报告" --description "Q1数据"
```

### task_get

获取任务详情。

```
python3 scripts/feishu_task.py get --task-id xxx
```

### task_list

获取任务列表。使用 `tenant_access_token` 时，返回该应用创建的所有任务。

```
python3 scripts/feishu_task.py list --limit 50
```

### task_complete

完成任务。

```
python3 scripts/feishu_task.py complete --task-id xxx
```

### 其他函数（通过脚本 Python API 调用）

- `task_update(task_id, fields)` — 更新任务（PATCH 语义）
- `tasklist_create(name)` — 创建任务清单（v2）
- `tasklist_list()` — 获取任务清单列表（v2）
- `tasklist_add_task(task_id, tasklist_id)` — 将任务添加到清单（v2）

## 成员角色

| 参数 | 含义 |
|------|------|
| collaborator_ids | 执行者（open_id 列表） |
| follower_ids | 关注者（open_id 列表） |

## v1 与 v2 API 选择说明

| 操作 | 使用版本 | 原因 |
|------|---------|------|
| task_create/get/list/update/complete | v1 | v1 全面支持 `tenant_access_token` |
| tasklist_create/list/add_task | v2 | v2 独有功能 |

Task v2 的 GET 类接口不支持 `tenant_access_token`，因此任务 CRUD 统一使用 v1。

## 所需权限

| 权限 | 用途 |
|------|------|
| task:task | 任务完整权限（读写） |
| task:task:readonly | 任务只读 |
| task:tasklist:read | 读取任务清单 |
| task:tasklist:write | 管理任务清单 |

## 凭据

自动读取 `~/.hiperone/config.json` 或环境变量 `NANOBOT_CHANNELS__FEISHU__APP_ID` / `NANOBOT_CHANNELS__FEISHU__APP_SECRET`，无需手动配置。
