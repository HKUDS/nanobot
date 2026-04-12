# 邻居节点自动接收和处理悬赏任务实现计划

## 现状分析

### 现有功能
1. **悬赏任务管理**：`BountyHub` 类负责创建、提交、评审悬赏任务
2. **节点管理**：前端通过 `convList` 管理对话节点
3. **布局显示**：使用 dagre 实现节点树的自动布局

### 缺失功能
1. **邻居节点关系**：没有邻居节点的概念和存储
2. **边权管理**：没有边权表示节点间亲密关系
3. **自动任务分发**：节点发布悬赏时，邻居节点不会自动接收
4. **自动任务处理**：邻居节点不会自动处理接收到的任务

## 实现方案

### 1. 邻居节点关系管理
- **数据库表**：创建 `node_relations` 表存储节点间关系和边权
- **API 接口**：添加获取和管理邻居关系的接口
- **前端显示**：在节点图中显示边权

### 2. 自动任务分发机制
- **修改 `create_bounty`**：当节点创建悬赏时，自动分发给邻居节点
- **任务通知**：为邻居节点创建任务通知
- **优先级排序**：根据边权排序，优先分发给亲密关系高的节点

### 3. 自动任务处理
- **Agent 自动处理**：邻居节点的 Agent 自动接收并处理任务
- **提交方案**：根据任务要求生成解决方案并提交
- **结果反馈**：处理完成后反馈结果

## 技术实现

### 1. 数据库设计

**添加 `node_relations` 表**：
```sql
CREATE TABLE IF NOT EXISTS node_relations (
    id TEXT PRIMARY KEY,
    source_node_id TEXT,
    target_node_id TEXT,
    weight INTEGER DEFAULT 1,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (source_node_id) REFERENCES wallets(conversation_id),
    FOREIGN KEY (target_node_id) REFERENCES wallets(conversation_id)
)
```

### 2. 后端实现

**增强 `BountyHub` 类**：
- 添加 `get_neighbors` 方法：获取节点的邻居列表
- 修改 `create_bounty` 方法：添加自动分发逻辑
- 添加 `notify_neighbors` 方法：通知邻居节点

**添加 `NodeRelationManager` 类**：
- 管理节点间关系
- 计算节点间亲密关系
- 提供邻居查询接口

### 3. 前端实现

**增强节点图显示**：
- 显示节点间的边权
- 高亮显示亲密关系高的边
- 显示任务分发状态

**添加邻居管理界面**：
- 查看和管理邻居关系
- 调整节点间的亲密关系

### 4. Agent 自动处理

**修改 `agent_server.py`**：
- 添加任务接收监听
- 实现自动任务处理逻辑
- 自动提交解决方案

## 实现步骤

### 步骤 1：数据库扩展
- **文件**：`bff/db.py`
- **修改**：添加 `node_relations` 表创建

### 步骤 2：节点关系管理
- **文件**：`bff/node_relation.py`（新建）
- **实现**：`NodeRelationManager` 类，管理节点间关系

### 步骤 3：悬赏任务增强
- **文件**：`bff/bounty_hub.py`
- **修改**：添加自动分发逻辑

### 步骤 4：API 接口扩展
- **文件**：`bff/bff_service.py`
- **添加**：邻居关系管理接口

### 步骤 5：前端增强
- **文件**：`frontend/src/App.vue`
- **修改**：显示边权和任务分发状态

### 步骤 6：Agent 自动处理
- **文件**：`nanobot_agent/agent_server.py`
- **修改**：添加任务接收和自动处理逻辑

## 关键功能实现

### 1. 邻居节点自动接收任务
```python
async def create_bounty(self, issuer_id: str, title: str, description: str, reward_pool: int, deadline: datetime, docker_reward: int = 0) -> str:
    # 原有逻辑
    await self.wallet.transfer(issuer_id, "system", reward_pool, "bounty_lock")
    bounty_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute("""
            INSERT INTO bounties (id, issuer_id, title, description, reward_pool, docker_reward, deadline, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
        """, (bounty_id, issuer_id, title, description, reward_pool, docker_reward, deadline, datetime.now()))
    
    # 自动分发给邻居节点
    await self.notify_neighbors(issuer_id, bounty_id)
    
    return bounty_id

async def notify_neighbors(self, issuer_id: str, bounty_id: str):
    # 获取邻居节点
    neighbors = await self.get_neighbors(issuer_id)
    
    # 按边权排序
    neighbors.sort(key=lambda x: x['weight'], reverse=True)
    
    # 通知邻居节点
    for neighbor in neighbors:
        # 创建任务通知
        notification_id = str(uuid.uuid4())
        with get_db() as conn:
            conn.execute("""
                INSERT INTO notifications (id, node_id, bounty_id, type, status, created_at)
                VALUES (?, ?, ?, 'bounty', 'pending', ?)
            """, (notification_id, neighbor['node_id'], bounty_id, datetime.now()))
```

### 2. 边权管理
```python
class NodeRelationManager:
    def __init__(self):
        pass
    
    async def add_relation(self, source_node_id: str, target_node_id: str, weight: int = 1):
        """添加节点关系"""
        relation_id = str(uuid.uuid4())
        with get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO node_relations (id, source_node_id, target_node_id, weight, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (relation_id, source_node_id, target_node_id, weight, datetime.now(), datetime.now()))
    
    async def get_neighbors(self, node_id: str) -> List[dict]:
        """获取节点的邻居"""
        with get_db() as conn:
            rows = conn.execute("""
                SELECT target_node_id as node_id, weight
                FROM node_relations
                WHERE source_node_id = ?
                UNION
                SELECT source_node_id as node_id, weight
                FROM node_relations
                WHERE target_node_id = ?
            """, (node_id, node_id)).fetchall()
        return [dict(row) for row in rows]
```

### 3. 前端显示边权
```javascript
// 绘制边时显示边权
svgGroup.selectAll('.link')
  .data(g.edges())
  .enter()
  .append('path')
  .attr('class', 'link')
  .attr('d', d => {
    // 原有逻辑
  })
  .attr('stroke-width', d => {
    // 根据边权设置线宽
    const weight = getEdgeWeight(d.v, d.w)
    return Math.max(1, weight)
  })

// 添加边权标签
svgGroup.selectAll('.edge-label')
  .data(g.edges())
  .enter()
  .append('text')
  .attr('class', 'edge-label')
  .attr('x', d => {
    const source = g.node(d.v)
    const target = g.node(d.w)
    return (source.x + target.x) / 2
  })
  .attr('y', d => {
    const source = g.node(d.v)
    const target = g.node(d.w)
    return (source.y + target.y) / 2 - 10
  })
  .text(d => {
    const weight = getEdgeWeight(d.v, d.w)
    return weight
  })
  .attr('font-size', '10px')
  .attr('fill', '#666')
```

## 测试验证

### 测试流程
1. **创建节点**：创建多个对话节点
2. **建立关系**：设置节点间的邻居关系和边权
3. **发布悬赏**：在一个节点上发布悬赏任务
4. **验证分发**：检查邻居节点是否收到任务通知
5. **自动处理**：检查邻居节点是否自动处理任务
6. **结果验证**：检查任务处理结果和奖励分配

### 预期结果
- **任务分发**：邻居节点自动收到任务通知
- **自动处理**：邻居节点的 Agent 自动处理任务
- **边权影响**：亲密关系高的节点优先处理任务
- **显示效果**：前端显示节点间的边权

## 风险评估

- **风险**：邻居节点过多导致任务分发延迟
- **缓解**：设置最大分发节点数，优先分发给亲密关系高的节点

- **风险**：Agent 自动处理失败
- **缓解**：添加错误处理和重试机制

- **风险**：边权计算不准确
- **缓解**：基于实际交互数据动态调整边权

- **风险**：数据库性能问题
- **缓解**：添加索引，优化查询

## 执行计划

1. **数据库扩展**：添加 `node_relations` 和 `notifications` 表
2. **节点关系管理**：实现 `NodeRelationManager` 类
3. **悬赏任务增强**：修改 `BountyHub` 类，添加自动分发逻辑
4. **API 接口扩展**：添加邻居关系管理和任务通知接口
5. **前端增强**：显示边权和任务分发状态
6. **Agent 自动处理**：修改 `agent_server.py`，添加自动处理逻辑
7. **测试验证**：执行完整测试流程
8. **性能优化**：优化数据库查询和任务分发机制