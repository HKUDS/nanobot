# 修复悬赏任务邻居通知分发问题

## 问题分析

**问题**: 发布悬赏任务后，虽然后端会创建通知到数据库，但邻居节点不会收到通知并自动接受任务。

**现状**:
- ✅ 后端 `notify_neighbors()` 会创建通知记录到数据库
- ✅ 有通知 API: `/notifications/{node_id}`
- ❌ 前端没有显示通知的 UI
- ❌ agent_server 没有定时检查通知的逻辑
- ❌ 没有自动接受任务的逻辑

---

## 修复方案

### Step 1: 前端添加通知显示

**文件**: `frontend/src/components/BountyMarket.vue`

**修改内容**:
1. 添加通知图标在右上角
2. 添加通知弹窗/抽屉
3. 定期轮询通知 API
4. 显示通知列表，包含"接受任务"按钮

---

### Step 2: agent_server 添加通知检查

**文件**: `nanobot_agent/agent_server.py`

**修改内容**:
1. 添加定时任务，定期检查 `/notifications/{node_id}`
2. 对 pending 状态的通知，自动接受任务
3. 调用 `/bounties/{bounty_id}/submit` 提交方案
4. 更新通知状态为 processing/completed

---

### Step 3: 添加接受任务的 API（可选）

**文件**: `bff/bff_service.py`

**修改内容** (如果需要):
1. 添加 `POST /notifications/{notification_id}/accept` 接口
2. 自动提交一个简单的方案

---

## 详细实现

### 前端修改

#### 1. 添加通知图标和弹窗

在 BountyMarket.vue 的标题栏添加：
```vue
<div class="flex justify-between items-center mb-4">
  <h2 class="text-lg font-semibold text-gray-800">悬赏市场</h2>
  <div class="flex items-center gap-4">
    <!-- 通知图标 -->
    <el-badge :value="unreadNotifications.length" :hidden="unreadNotifications.length === 0">
      <el-button circle @click="showNotificationsDialog = true">
        <el-icon><Bell /></el-icon>
      </el-button>
    </el-badge>
    <el-button type="primary" @click="showCreateDialog = true">
      <el-icon class="mr-1"><Plus /></el-icon>
      发布悬赏
    </el-button>
  </div>
</div>
```

#### 2. 添加通知弹窗
```vue
<!-- 通知弹窗 -->
<el-drawer v-model="showNotificationsDialog" title="任务通知" size="400px">
  <el-list>
    <el-list-item v-for="notification in notifications" :key="notification.id">
      <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
        <div>
          <div style="font-weight: bold;">{{ notification.type === 'bounty' ? '新悬赏任务' : '通知' }}</div>
          <div style="color: #666; font-size: 12px;">
            悬赏 ID: {{ notification.bounty_id }}
          </div>
          <div style="color: #999; font-size: 10px;">
            {{ formatDate(notification.created_at) }}
          </div>
        </div>
        <div v-if="notification.status === 'pending'">
          <el-button size="small" type="primary" @click="acceptNotification(notification)">
            接受任务
          </el-button>
        </div>
        <div v-else>
          <el-tag size="small" :type="notification.status === 'processing' ? 'warning' : 'success'">
            {{ notification.status }}
          </el-tag>
        </div>
      </div>
    </el-list-item>
    <el-empty v-if="notifications.length === 0" description="暂无通知" />
  </el-list>
</el-drawer>
```

#### 3. 添加通知相关逻辑
```javascript
// 添加导入
import { Bell } from '@element-plus/icons-vue'

// 添加状态
const showNotificationsDialog = ref(false)
const notifications = ref([])
const unreadNotifications = ref([])

// 添加方法
async function fetchNotifications() {
  try {
    const res = await request.get(`/notifications/${props.conversationId}`)
    notifications.value = res.data.notifications || []
    unreadNotifications.value = notifications.value.filter(n => n.status === 'pending')
  } catch (err) {
    console.error('获取通知失败:', err)
  }
}

async function acceptNotification(notification) {
  try {
    // 更新通知状态
    await request.post(`/notifications/${notification.id}/process`)
    
    // 获取悬赏详情
    const bountyRes = await request.get(`/bounties/${notification.bounty_id}`)
    const bounty = bountyRes.data
    
    // 自动提交一个简单的方案
    await request.post(`/bounties/${notification.bounty_id}/submissions`, {
      agent_id: props.conversationId,
      content: `自动接受任务：${bounty.title}`,
      skill_code: '',
      cost_tokens: 0
    })
    
    ElMessage.success('已接受任务并提交方案')
    await fetchNotifications()
  } catch (err) {
    console.error('接受任务失败:', err)
    ElMessage.error('接受任务失败')
  }
}

// 定时检查通知
let notificationInterval = null
onMounted(() => {
  fetchBounties()
  fetchNotifications()
  notificationInterval = setInterval(fetchNotifications, 30000) // 每30秒检查
})

onUnmounted(() => {
  if (notificationInterval) {
    clearInterval(notificationInterval)
  }
})
```

---

### agent_server 修改

在 agent_server.py 中添加通知检查逻辑：

```python
import asyncio
import aiohttp
from datetime import datetime

# 在 AgentServer 类中添加
async def _check_notifications_loop(self):
    """定期检查通知的循环"""
    while True:
        try:
            await self._check_and_accept_notifications()
        except Exception as e:
            print(f"[Agent] 检查通知失败: {e}")
        await asyncio.sleep(60)  # 每60秒检查一次

async def _check_and_accept_notifications(self):
    """检查并接受通知"""
    if not self.current_conv_id:
        return
    
    print(f"[Agent] 检查通知...")
    
    # 获取通知
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{self.BFF_URL}/notifications/{self.current_conv_id}") as resp:
                if resp.status != 200:
                    print(f"[Agent] 获取通知失败: {resp.status}")
                    return
                data = await resp.json()
                notifications = data.get("notifications", [])
                pending_notifications = [n for n in notifications if n["status"] == "pending"]
                
                if len(pending_notifications) == 0:
                    print(f"[Agent] 没有待处理的通知")
                    return
                
                print(f"[Agent] 找到 {len(pending_notifications)} 个待处理通知")
                
                # 处理每个待处理通知
                for notification in pending_notifications:
                    await self._process_notification(notification, session)
                    
        except Exception as e:
            print(f"[Agent] 处理通知失败: {e}")

async def _process_notification(self, notification, session):
    """处理单个通知"""
    notification_id = notification["id"]
    bounty_id = notification["bounty_id"]
    
    print(f"[Agent] 处理通知: {notification_id}")
    
    # 1. 更新通知状态为 processing
    try:
        async with session.post(f"{self.BFF_URL}/notifications/{notification_id}/process") as resp:
            if resp.status != 200:
                print(f"[Agent] 更新通知状态失败: {resp.status}")
                return
    except Exception as e:
        print(f"[Agent] 更新通知状态失败: {e}")
        return
    
    # 2. 获取悬赏详情
    try:
        async with session.get(f"{self.BFF_URL}/bounties/{bounty_id}") as resp:
            if resp.status != 200:
                print(f"[Agent] 获取悬赏详情失败: {resp.status}")
                return
            bounty_data = await resp.json()
            bounty = bounty_data.get("bounty", {})
            bounty_title = bounty.get("title", "未知任务")
    except Exception as e:
        print(f"[Agent] 获取悬赏详情失败: {e}")
        return
    
    # 3. 提交方案
    try:
        submission_data = {
            "agent_id": self.current_conv_id,
            "content": f"自动接受并执行任务：{bounty_title}",
            "skill_code": "",
            "cost_tokens": 0
        }
        async with session.post(
            f"{self.BFF_URL}/bounties/{bounty_id}/submissions",
            json=submission_data
        ) as resp:
            if resp.status == 200:
                print(f"[Agent] 提交方案成功: {bounty_id}")
            else:
                print(f"[Agent] 提交方案失败: {resp.status}")
    except Exception as e:
        print(f"[Agent] 提交方案失败: {e}")

# 在 run 方法中启动通知检查循环
async def run(self):
    # ... 现有代码 ...
    
    # 启动通知检查循环
    notification_task = asyncio.create_task(self._check_notifications_loop())
    
    # ... 现有代码 ...
```

---

## 修改文件清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `frontend/src/components/BountyMarket.vue` | 新增 | 添加通知 UI 和逻辑 |
| `nanobot_agent/agent_server.py` | 新增 | 添加通知检查和自动接受逻辑 |

---

## 验证方法

1. **前端验证**:
   - 打开页面，右上角应有通知铃铛图标
   - 发布悬赏后，其他节点应能看到通知
   - 点击"接受任务"应能提交方案

2. **agent_server 验证**:
   - 查看日志，应定期显示 `[Agent] 检查通知...`
   - 有新通知时应自动接受并提交方案

---

## 实施步骤

1. [ ] 修改前端，添加通知 UI
2. [ ] 修改 agent_server，添加通知检查循环
3. [ ] 测试完整流程
