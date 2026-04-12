# 修复 agent_server.py 悬赏任务处理功能

## 问题描述

agent_server.py 的悬赏任务处理代码被重置/丢失了，导致：
1. 无法自动检查和接受悬赏任务
2. 任务处理后状态一直是 processing

---

## 需要重新添加的代码

### 1. 添加 check_notifications 函数

位置：initialize_agent 函数之前

```python
async def check_notifications():
    """检查新通知"""
    bff_url = os.environ.get("BFF_URL", "http://host.docker.internal:8000")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        try:
            async with session.get(f"{bff_url}/notifications/{CONVERSATION_ID}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("notifications", [])
                else:
                    print(f"[Notifications] Failed to get notifications: {resp.status}")
        except Exception as e:
            print(f"[Notifications] Error checking notifications: {e}")
    return []
```

### 2. 添加 process_bounty_task 函数

```python
async def process_bounty_task(bounty_id: str, notification_id: str = None):
    """处理悬赏任务"""
    bff_url = os.environ.get("BFF_URL", "http://host.docker.internal:8000")
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        try:
            # 先更新状态为 processing
            if notification_id:
                async with session.post(f"{bff_url}/notifications/{notification_id}/process") as update_resp:
                    if update_resp.status == 200:
                        print(f"[Bounty] 通知状态已更新为 processing: notification_id={notification_id}")
                    else:
                        print(f"[Bounty] 更新通知状态失败: {update_resp.status}")
                        return

            async with session.get(f"{bff_url}/bounties/{bounty_id}") as resp:
                if resp.status == 200:
                    bounty = await resp.json()
                    print(f"[Bounty] Processing task: {bounty.get('title')}")

                    global agent_loop
                    if agent_loop is None:
                        print(f"[Bounty] AgentLoop 未初始化，跳过自动处理")
                        solution_content = f"自动接受任务：{bounty.get('title', '未知任务')} - AgentLoop未初始化，仅标记参与"
                    else:
                        from nanobot.bus.events import InboundMessage

                        task_content = f"请处理以下悬赏任务：\n"
                        task_content += f"标题：{bounty.get('title')}\n"
                        task_content += f"描述：{bounty.get('description')}\n"
                        task_content += f"奖励：{bounty.get('reward_pool')} Token\n"
                        task_content += f"Docker 奖励：{bounty.get('docker_reward')}\n"
                        task_content += f"截止时间：{bounty.get('deadline')}\n"
                        task_content += "请生成解决方案并提交。"

                        inbound_msg = InboundMessage(
                            channel="container",
                            chat_id=CONVERSATION_ID,
                            sender_id="system",
                            content=task_content,
                            metadata={"bounty_id": bounty_id}
                        )

                        response = await agent_loop._process_message(inbound_msg)
                        print(f"[Bounty] Task processed: {bounty_id}")
                        solution_content = response.content if response else ""

                    # 提交解决方案
                    async with session.post(f"{bff_url}/bounties/{bounty_id}/submit", json={
                        "agent_id": CONVERSATION_ID,
                        "content": solution_content,
                        "skill_code": "",
                        "cost_tokens": 0
                    }) as submit_resp:
                        if submit_resp.status == 200:
                            print(f"[Bounty] Solution submitted successfully: {bounty_id}")
                            # 更新通知状态为 completed
                            if notification_id:
                                async with session.post(f"{bff_url}/notifications/{notification_id}/complete") as complete_resp:
                                    if complete_resp.status == 200:
                                        print(f"[Bounty] 通知状态已更新为 completed: notification_id={notification_id}")
                                    else:
                                        print(f"[Bounty] 更新通知状态为 completed 失败: {complete_resp.status}")
                        else:
                            error_text = await submit_resp.text()
                            print(f"[Bounty] Failed to submit solution: {submit_resp.status}, details: {error_text}")
                else:
                    print(f"[Bounty] Failed to get task details: {resp.status}")
        except Exception as e:
            print(f"[Bounty] Error processing task: {e}")
```

### 3. 添加 check_and_process_tasks 函数

```python
async def check_and_process_tasks():
    """检查并处理新任务"""
    notifications = await check_notifications()
    for notification in notifications:
        if notification.get("type") == "bounty" and notification.get("status") == "pending":
            bounty_id = notification.get("bounty_id")
            notification_id = notification.get("id")
            if bounty_id and notification_id:
                await process_bounty_task(bounty_id, notification_id)
```

### 4. 添加 task_checker 函数

```python
async def task_checker():
    """后台任务检查器"""
    while True:
        await check_and_process_tasks()
        await asyncio.sleep(30)  # 每30秒检查一次
```

### 5. 修改 startup 函数

将：
```python
@app.on_event("startup")
async def startup():
    await initialize_agent()
```

改为：
```python
@app.on_event("startup")
async def startup():
    await initialize_agent()
    # 启动后台任务检查器
    asyncio.create_task(task_checker())
```

### 6. 添加 aiohttp 导入

确认已导入 aiohttp：
```python
import aiohttp
```

---

## 修改文件清单

| 文件 | 修改内容 |
|------|----------|
| nanobot_agent/agent_server.py | 添加 5 个函数，修改 1 个函数，添加 1 个导入 |

---

## 验证清单

修复后验证：
- [ ] 重启容器后查看日志，确认 task_checker 已启动
- [ ] 发布悬赏任务后，邻居节点收到通知
- [ ] 任务处理后状态变为 processing
- [ ] 提交成功后状态变为 completed
