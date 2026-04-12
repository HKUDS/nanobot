# 节点实时显示 Reward 功能实现计划

## 问题分析

**当前状态**：
- 后端每个对话节点都有 `power` 字段（即 reward 值）
- 前端在轨迹卡片中显示了 reward，但在节点图中没有显示
- 没有实时更新机制，需要手动刷新

**用户需求**：
- 每个节点实时显示它们的 reward
- 确保 reward 变化时能实时更新

## 技术分析

### 后端
- **数据存储**：`conversations` 字典中每个对话都有 `power` 字段
- **更新机制**：通过 `update_power_with_file_monitoring` 和 `add_annotation` 函数更新
- **API 接口**：`/conversations/{conversation_id}/power` 接口获取 power 信息

### 前端
- **节点显示**：`drawGraph()` 函数绘制节点，但只显示标题
- **数据获取**：通过 `fetchConversations()` 获取对话列表，但不包含实时 power 数据
- **实时更新**：缺少 WebSocket 或轮询机制

## 实现方案

### 方案 1：增强现有 API，添加轮询机制
1. **后端**：在对话列表 API 中包含 power 字段
2. **前端**：添加定时轮询，更新节点显示

### 方案 2：实现 WebSocket 实时更新
1. **后端**：添加 WebSocket 支持，推送 power 变化
2. **前端**：建立 WebSocket 连接，接收实时更新

### 方案 3：点击节点时获取 power 信息
1. **前端**：点击节点时调用 power API 获取最新数据
2. **显示**：在节点旁显示 power 值

## 推荐方案

**方案 1**：增强现有 API + 轮询机制
- **优势**：实现简单，兼容性好
- **劣势**：有轻微延迟
- **适用**：当前系统架构

## 实现步骤

### 步骤 1：后端 API 增强
- **文件**：`bff/bff_service.py`
- **修改**：在 `api_list_conversations` 中包含每个对话的 `power` 字段

### 步骤 2：前端节点显示增强
- **文件**：`frontend/src/App.vue`
- **修改**：
  1. 在 `drawGraph()` 中为每个节点添加 power 显示
  2. 添加定时轮询机制，定期刷新对话列表
  3. 优化节点样式，显示 power 值

### 步骤 3：实时更新机制
- **文件**：`frontend/src/App.vue`
- **修改**：
  1. 添加 `setInterval` 定时调用 `fetchConversations()`
  2. 实现增量更新，只更新变化的节点
  3. 添加动画效果，增强用户体验

## 具体实现

### 后端修改
```python
@app.get("/conversations")
async def api_list_conversations():
    """获取对话列表"""
    async with conversations_lock:
        conv_list = []
        for conv_id, conv in conversations.items():
            conv_list.append({
                "conversation_id": conv_id,
                "title": conv.get("title", ""),
                "model": conv.get("model", ""),
                "status": conv.get("status", "active"),
                "parent_id": conv.get("parent_id"),
                "power": conv.get("power", 50.0)  # 新增：包含 power 字段
            })
        return {"conversations": conv_list}
```

### 前端修改
1. **增强 drawGraph 函数**：
   - 为每个节点添加 power 显示
   - 根据 power 值显示不同颜色

2. **添加轮询机制**：
   - 每 5 秒自动刷新对话列表
   - 只更新变化的节点

3. **优化用户体验**：
   - 添加 power 变化动画
   - 显示 power 趋势

## 预期结果

- **节点显示**：每个节点旁显示当前 reward 值
- **实时更新**：reward 变化时自动更新显示
- **视觉效果**：根据 reward 值显示不同颜色，增强可读性
- **性能优化**：增量更新，减少不必要的重绘

## 风险评估

- **风险**：轮询可能增加服务器负载
- **缓解**：设置合理的轮询间隔（5-10秒）

- **风险**：频繁重绘可能影响前端性能
- **缓解**：实现增量更新，只更新变化的节点

- **风险**：WebSocket 实现复杂度高
- **缓解**：先使用轮询方案，后续可升级为 WebSocket

## 执行计划

1. **修改后端 API**：在对话列表中包含 power 字段
2. **修改前端节点显示**：在 drawGraph 中添加 power 显示
3. **添加轮询机制**：实现定时刷新
4. **测试验证**：确保实时更新正常工作
5. **性能优化**：调整轮询间隔和更新策略