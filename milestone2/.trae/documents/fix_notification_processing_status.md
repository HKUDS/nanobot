# 悬赏任务处理问题分析与修复计划

## 问题描述

**问题 1**: 通知状态一直是 `processing`，没有变成 `completed`

**问题 2**: 任务没有发送到 Docker 容器运行（AgentLoop 可能未初始化）

---

## 根本原因分析

### 原因 1: 提交成功后没有更新通知状态

**位置**: `agent_server.py` 第 188-198 行

```python
# 提交解决方案
async with session.post(f"{bff_url}/bounties/{bounty_id}/submit", json={...}) as submit_resp:
    if submit_resp.status == 200:
        print(f"[Bounty] Solution submitted successfully: {bounty_id}")
        # ❌ 缺少：没有更新通知状态为 completed！
    else:
        print(f"[Bounty] Failed to submit solution...")
```

**影响**: 通知状态一直是 `processing`

---

### 原因 2: AgentLoop 未初始化导致任务未真正执行

**位置**: `agent_server.py` 第 157-159 行

```python
if agent_loop is None:
    print(f"[Bounty] AgentLoop 未初始化，跳过自动处理")
    solution_content = f"自动接受任务：{bounty.get('title', '未知任务')} - AgentLoop未初始化，仅标记参与"
```

**原因**: CONVERSATION_ID 环境变量可能是 "unknown"

**位置**: `agent_server.py` 第 84 行

```python
CONVERSATION_ID = os.environ.get("CONVERSATION_ID", "unknown")
```

**影响**: 如果 CONVERSATION_ID 是 "unknown"，说明容器没有正确获取到环境变量

---

## 修复方案

### Step 1: 添加通知状态更新 API

**文件**: `bff/bff_service.py`

添加新 API 端点：
```python
@app.post("/notifications/{notification_id}/complete")
async def api_complete_notification(notification_id: str):
    """将通知状态更新为 completed"""
    try:
        print(f"[Notification] 更新状态为 completed: {notification_id}")
        with get_db() as conn:
            conn.execute("""
                UPDATE notifications SET status = 'completed' WHERE id = ?
            """, (notification_id,))
        return {"status": "ok"}
    except Exception as e:
        print(f"[Notification] 更新状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to complete notification: {str(e)}")
```

---

### Step 2: 修复 agent_server 提交后更新状态

**文件**: `nanobot_agent/agent_server.py`

修改 `process_bounty_task` 函数，在提交成功后调用状态更新 API：

```python
async with session.post(f"{bff_url}/bounties/{bounty_id}/submit", json={...}) as submit_resp:
    if submit_resp.status == 200:
        print(f"[Bounty] Solution submitted successfully: {bounty_id}")
        # ✅ 添加：更新通知状态为 completed
        if notification_id:
            async with session.post(f"{bff_url}/notifications/{notification_id}/complete") as complete_resp:
                if complete_resp.status == 200:
                    print(f"[Bounty] 通知状态已更新为 completed: notification_id={notification_id}")
                else:
                    print(f"[Bounty] 更新通知状态为 completed 失败: {complete_resp.status}")
    else:
        error_text = await submit_resp.text()
        print(f"[Bounty] Failed to submit solution: {submit_resp.status}, details: {error_text}")
```

---

### Step 3: 检查环境变量配置（可选）

确保容器启动时正确传递 CONVERSATION_ID 环境变量。

---

## 修改文件清单

| 文件 | 修改内容 |
|------|----------|
| `bff/bff_service.py` | 添加 `/notifications/{id}/complete` API |
| `nanobot_agent/agent_server.py` | 提交成功后调用 complete API |

---

## 验证清单

修复后验证：
- [ ] 悬赏任务发布后，邻居节点收到通知（状态 pending）
- [ ] 邻居节点处理后，状态变为 processing
- [ ] 提交方案后，状态变为 completed
- [ ] 查看数据库确认状态正确
