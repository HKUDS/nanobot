# 终极 Skill 系统验证清单

## Phase 1: Token 经济闭环

### 数据库扩展
- [ ] token_accounts 表包含 frozen_balance 字段
- [ ] token_transactions 表创建成功

### 发布悬赏冻结
- [ ] 发布悬赏时 Token 被正确冻结
- [ ] 冻结金额 = reward_pool + docker_reward
- [ ] 交易记录类型为 `bounty_create`

### 悬赏结算
- [ ] settle_bounty() 方法存在
- [ ] 评级计算正确 (S/A/B/C/D)
- [ ] 奖励按评级系数发放
- [ ] 剩余 Token 退回发布者
- [ ] 交易记录类型为 `bounty_reward`
- [ ] 悬赏状态变为 `settled`

### 结算 API
- [ ] POST `/bounties/{id}/settle` 接口存在
- [ ] 结算返回正确结果

---

## Phase 2: 共识研讨机制

### 数据库扩展
- [ ] discussion_rooms 表创建成功
- [ ] discussion_drafts 表创建成功
- [ ] public_knowledge 表包含 skill_type 字段
- [ ] public_knowledge 表包含 discussion_room_id 字段

### 研讨 Hub
- [ ] DiscussionHub 类存在
- [ ] create_discussion_room() 方法存在
- [ ] submit_draft() 方法存在
- [ ] judge_drafts() 方法存在
- [ ] finalize_consensus_skill() 方法存在

### LLM 裁判评估
- [ ] evaluate_drafts() 方法存在
- [ ] prompt 设计合理
- [ ] JSON 解析可靠
- [ ] 支持选择单一草案
- [ ] 支持合并多个草案

### 研讨 API
- [ ] POST `/discussions` 接口存在
- [ ] POST `/discussions/{id}/drafts` 接口存在
- [ ] POST `/discussions/{id}/judge` 接口存在
- [ ] GET `/discussions/{id}` 接口存在

### 前端研讨界面
- [ ] "发起群体研讨"按钮存在
- [ ] 研讨房间 UI 正常显示
- [ ] 草案提交表单可用
- [ ] 评估结果正确展示

---

## Phase 3: 社交记忆系统

### 数据库扩展
- [ ] interaction_logs 表创建成功
- [ ] 表结构包含 actor_id, target_id, action_type, context, created_at

### 社交 Hub
- [ ] SocialMemoryHub 类存在
- [ ] log_interaction() 方法存在
- [ ] get_friend_logs() 方法存在
- [ ] update_intimacy() 方法存在

### 亲密度更新
- [ ] 协作成功增加亲密度 +0.2
- [ ] 帮助解决问题增加亲密度 +0.5
- [ ] 支持长期无交互衰减

### 社交 API
- [ ] GET `/nodes/{id}/friend-logs` 接口存在
- [ ] POST `/interactions/log` 接口存在

### 前端好友经验
- [ ] "查看好友经验"按钮存在
- [ ] 基于关键词检索功能正常
- [ ] 历史案例正确展示

---

## Phase 4: 求助系统

### 数据库扩展
- [ ] help_requests 表创建成功
- [ ] 表结构支持定向和广播求助

### 求助 Hub
- [ ] HelpHub 类存在
- [ ] create_help_request() 方法存在
- [ ] respond_to_help() 方法存在
- [ ] accept_solution() 方法存在

### 求助 API
- [ ] POST `/help/request` 接口存在
- [ ] POST `/help/{id}/respond` 接口存在
- [ ] POST `/help/{id}/accept` 接口存在

### 前端求助界面
- [ ] "发起求助"按钮存在
- [ ] 定向/广播选择可用
- [ ] 求助大厅列表正常
- [ ] 响应/采纳功能正常

---

## Phase 5: 对比实验框架

### 数据库扩展
- [ ] experiments 表创建成功

### 实验记录
- [ ] 悬赏结算时记录实验数据
- [ ] 支持生成对比报告

---

## 端到端测试

### 完整悬赏流程
- [ ] 发布悬赏 → Token 冻结
- [ ] 邻居收到通知
- [ ] 邻居提交反馈
- [ ] 发布者结束悬赏
- [ ] 结算 → Token 发放
- [ ] 排行榜显示评分

### 共识研讨流程
- [ ] 高价值悬赏 → 可发起研讨
- [ ] 多个邻居提交草案
- [ ] LLM 裁判评估
- [ ] 共识 Skill 存入公共库

### 社交记忆流程
- [ ] 协作后记录交互日志
- [ ] 亲密度正确更新
- [ ] 可查询好友经验

### 求助流程
- [ ] 发起定向/广播求助
- [ ] 被求助节点收到通知
- [ ] 提供方案被采纳
- [ ] Token 正确转移
