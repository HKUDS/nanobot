# 节点显示 Token 钱包值功能实现计划

## 需求分析

**用户需求**：
- 每个节点旁显示当前 token 钱包的值
- reward 的值保持原来的显示方式，不用在节点旁显示
- 实现实时更新

## 技术分析

### 后端
- **钱包系统**：`token_wallet` 管理每个对话的 token 余额
- **API 接口**：`/wallet/{conv_id}/balance` 接口获取余额
- **数据存储**：余额存储在 `wallets` 表中

### 前端
- **节点显示**：`drawGraph()` 函数绘制节点，目前只显示标题
- **数据获取**：通过 `fetchConversations()` 获取对话列表
- **实时更新**：缺少自动更新机制

## 实现方案

### 方案 1：增强对话列表 API，包含钱包余额
1. **后端**：修改 `api_list_conversations`，为每个对话添加 `balance` 字段
2. **前端**：在 `drawGraph()` 中显示余额
3. **更新机制**：添加定时轮询，定期刷新对话列表

### 方案 2：单独获取每个节点的余额
1. **前端**：点击节点时调用余额 API 获取数据
2. **显示**：在节点旁显示余额
3. **缓存**：缓存余额数据，减少 API 调用

## 推荐方案

**方案 1**：增强对话列表 API + 轮询机制
- **优势**：实现简单，一次性获取所有节点余额
- **劣势**：可能增加 API 响应大小
- **适用**：当前系统架构

## 实现步骤

### 步骤 1：后端 API 增强
- **文件**：`bff/bff_service.py`
- **修改**：在 `api_list_conversations` 中为每个对话添加 `balance` 字段

### 步骤 2：前端节点显示增强
- **文件**：`frontend/src/App.vue`
- **修改**：
  1. 在 `drawGraph()` 中为每个节点添加余额显示
  2. 优化节点样式，显示余额值
  3. 根据余额大小显示不同颜色

### 步骤 3：实时更新机制
- **文件**：`frontend/src/App.vue`
- **修改**：
  1. 添加 `setInterval` 定时调用 `fetchConversations()`
  2. 实现增量更新，只更新变化的节点
  3. 添加余额变化动画效果

## 具体实现

### 后端修改
```python
@app.get("/conversations")
async def api_list_conversations():
    """获取对话列表"""
    async with conversations_lock:
        conv_list = []
        for conv_id, conv in conversations.items():
            # 获取钱包余额
            try:
                balance = await token_wallet.get_balance(conv_id)
            except:
                balance = 0
            
            conv_list.append({
                "conversation_id": conv_id,
                "title": conv.get("title", ""),
                "model": conv.get("model", ""),
                "status": conv.get("status", "active"),
                "parent_id": conv.get("parent_id"),
                "balance": balance  # 新增：包含钱包余额
            })
        return {"conversations": conv_list}
```

### 前端修改
1. **增强 drawGraph 函数**：
   - 为每个节点添加余额显示
   - 根据余额大小显示不同颜色

2. **添加轮询机制**：
   - 每 5 秒自动刷新对话列表
   - 只更新变化的节点

3. **优化用户体验**：
   - 添加余额变化动画
   - 显示余额格式优化

## 预期结果

- **节点显示**：每个节点旁显示当前 token 钱包值
- **实时更新**：余额变化时自动更新显示
- **视觉效果**：根据余额大小显示不同颜色，增强可读性
- **性能优化**：增量更新，减少不必要的重绘

## 风险评估

- **风险**：轮询可能增加服务器负载
- **缓解**：设置合理的轮询间隔（5-10秒）

- **风险**：频繁重绘可能影响前端性能
- **缓解**：实现增量更新，只更新变化的节点

- **风险**：API 响应时间增加
- **缓解**：余额查询使用缓存，减少数据库查询

## 执行计划

1. **修改后端 API**：在对话列表中包含余额字段
2. **修改前端节点显示**：在 drawGraph 中添加余额显示
3. **添加轮询机制**：实现定时刷新
4. **测试验证**：确保实时更新正常工作
5. **性能优化**：调整轮询间隔和更新策略