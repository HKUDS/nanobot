# 悬赏系统功能增强实现计划

## 需求分析

用户要求实现以下功能：
1. **每个节点要能显示 docker_reward**
2. **发布节点可以随时结束这个任务，进行评审**
3. **提交方案集成大模型接口**，支持：
   - 调大模型接口填充字段后提交
   - 与大模型几轮对话的形式填充字段

## 现有代码分析

### 1. 数据库结构
- **bounties 表**：包含 `id`, `issuer_id`, `title`, `description`, `reward_pool`, `deadline`, `status`, `created_at`, `winner_ids`
- **submissions 表**：包含 `id`, `bounty_id`, `agent_id`, `content`, `skill_code`, `cost_tokens`, `created_at`, `evaluation_score`
- **wallets 表**：包含 `conversation_id`, `balance`, `updated_at`

### 2. 现有功能
- 悬赏发布（POST /bounties）
- 悬赏列表（GET /bounties）
- 方案提交（POST /bounties/{id}/submit）
- 方案列表（GET /bounties/{id}/submissions）
- 评审奖励（POST /bounties/{id}/evaluate）

### 3. 缺失功能
- **docker_reward 字段**：数据库和前端都未实现
- **任务结束接口**：发布者无法随时结束任务
- **大模型集成**：方案提交时未集成大模型接口

## 实现计划

### 第一阶段：添加 docker_reward 支持

#### 1. 数据库修改
- **文件**：`bff/db.py`
- **修改**：在 `bounties` 表中添加 `docker_reward` 字段
  ```sql
  docker_reward INTEGER DEFAULT 0,
  ```

#### 2. 前端修改
- **文件**：`frontend/src/components/BountyMarket.vue`
- **修改**：
  - 在发布悬赏表单中添加 docker_reward 输入框
  - 在悬赏列表中显示 docker_reward 字段
  - 在 `newBounty` 对象中添加 `docker_reward` 属性

#### 3. BFF 服务修改
- **文件**：`bff/bff_service.py`
- **修改**：
  - 在 `BountyCreate` 模型中添加 `docker_reward` 字段
  - 在 `create_bounty` 调用中传递 `docker_reward` 参数

- **文件**：`bff/bounty_hub.py`
- **修改**：
  - 在 `create_bounty` 方法中添加 `docker_reward` 参数
  - 在数据库插入语句中包含 `docker_reward` 字段

### 第二阶段：实现任务结束功能

#### 1. BFF 服务修改
- **文件**：`bff/bff_service.py`
- **修改**：
  - 添加 `POST /bounties/{id}/close` 接口，允许发布者随时结束任务
  - 验证请求者是否为任务发布者
  - 调用 BountyHub 的关闭任务方法

- **文件**：`bff/bounty_hub.py`
- **修改**：
  - 添加 `close_bounty` 方法，将任务状态改为 `completed`
  - 保留评审和奖励功能

#### 2. 前端修改
- **文件**：`frontend/src/components/BountyMarket.vue`
- **修改**：
  - 在悬赏列表中为发布者显示"结束任务"按钮
  - 点击后调用关闭任务接口
  - 显示确认对话框

### 第三阶段：集成大模型接口

#### 1. BFF 服务修改
- **文件**：`bff/bff_service.py`
- **修改**：
  - 添加 `POST /bounties/{id}/ai-assist` 接口，用于大模型辅助填充字段
  - 集成 OpenAI 或 DeepSeek API
  - 接收任务描述和用户输入，返回填充建议

#### 2. 前端修改
- **文件**：`frontend/src/components/BountyMarket.vue`
- **修改**：
  - 在提交方案对话框中添加"AI 辅助"按钮
  - 点击后打开 AI 辅助对话框
  - 支持与大模型的多轮对话
  - 对话结束后自动填充表单字段

## 技术实现细节

### 1. docker_reward 实现
- **数据库**：在 `bounties` 表中添加 `docker_reward INTEGER DEFAULT 0`
- **前端**：在表单中添加数字输入框，范围 0-1000
- **API**：在 `BountyCreate` 模型中添加 `docker_reward: int = 0`

### 2. 任务结束功能
- **API**：`POST /bounties/{id}/close`，需要验证 `issuer_id`
- **权限**：只有任务发布者可以结束任务
- **状态**：任务状态从 `open` 改为 `completed`

### 3. 大模型集成
- **API**：`POST /bounties/{id}/ai-assist`，接收 `user_input` 和 `conversation_history`
- **模型**：使用 DeepSeek 或 OpenAI API
- **流程**：
  1. 前端发送任务描述和用户输入
  2. BFF 调用大模型 API
  3. 大模型返回填充建议
  4. 前端显示建议并允许用户确认
  5. 确认后自动填充表单字段

## 风险评估

### 1. 数据库迁移
- **风险**：修改数据库表结构可能影响现有数据
- **缓解**：使用 `ALTER TABLE` 添加字段，设置默认值 0

### 2. 大模型 API 调用
- **风险**：API 调用失败或响应缓慢
- **缓解**：
  - 添加超时处理
  - 实现错误重试机制
  - 提供用户友好的错误提示

### 3. 权限验证
- **风险**：未正确验证任务发布者身份
- **缓解**：在关闭任务接口中严格验证 `issuer_id`

## 执行步骤

1. **第一阶段**：添加 docker_reward 支持
   - 修改数据库表结构
   - 更新前端表单和列表
   - 修改 BFF 服务和 BountyHub

2. **第二阶段**：实现任务结束功能
   - 添加关闭任务接口
   - 更新前端按钮和逻辑
   - 测试权限验证

3. **第三阶段**：集成大模型接口
   - 添加 AI 辅助接口
   - 实现前端对话界面
   - 测试大模型集成

4. **测试与验证**
   - 测试完整流程：发布 → 提交 → 结束 → 评审
   - 验证 docker_reward 显示
   - 测试大模型辅助功能

## 预期结果

- **docker_reward**：每个节点显示 docker_reward 字段
- **任务结束**：发布者可以随时结束任务并进行评审
- **大模型集成**：提交方案时可以通过大模型辅助填充字段

## 依赖项

- **数据库**：SQLite（现有）
- **大模型 API**：DeepSeek API（现有）或 OpenAI API
- **前端**：Element Plus（现有）
- **后端**：FastAPI（现有）
