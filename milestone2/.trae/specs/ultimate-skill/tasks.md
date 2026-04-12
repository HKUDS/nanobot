# 终极 Skill 系统实施任务清单

## Phase 1: Token 经济闭环

### Task 1.1: 数据库扩展 - Token 冻结
- [ ] 在 token_accounts 表添加 frozen_balance 字段
- [ ] 添加 token_transactions 表
- [ ] 更新 db.py 的表结构

### Task 1.2: 修改发布悬赏逻辑
- [ ] create_bounty 时冻结 Token
- [ ] 计算冻结金额 = reward_pool + docker_reward
- [ ] 记录交易类型 `bounty_create`

### Task 1.3: 实现悬赏结算
- [ ] 创建 settle_bounty() 方法
- [ ] 计算评级奖励
- [ ] 从冻结金额发放奖励
- [ ] 退还剩余金额
- [ ] 记录交易类型 `bounty_reward`
- [ ] 标记悬赏为 settled

### Task 1.4: 添加结算 API
- [ ] POST `/bounties/{id}/settle` 接口
- [ ] 调用 settle_bounty() 方法
- [ ] 返回结算结果

---

## Phase 2: 共识研讨机制

### Task 2.1: 数据库扩展 - 研讨表
- [ ] 创建 discussion_rooms 表
- [ ] 创建 discussion_drafts 表
- [ ] 更新 public_knowledge 表添加 skill_type, discussion_room_id

### Task 2.2: 实现研讨 Hub
- [ ] 创建 DiscussionHub 类
- [ ] create_discussion_room() 方法
- [ ] submit_draft() 方法
- [ ] judge_drafts() 方法 (LLM 评估)
- [ ] finalize_consensus_skill() 方法

### Task 2.3: LLM 裁判评估
- [ ] 设计评估 prompt
- [ ] 实现 evaluate_drafts() 方法
- [ ] 处理选择/合并草案逻辑

### Task 2.4: 添加研讨 API
- [ ] POST `/discussions` 创建研讨房间
- [ ] POST `/discussions/{id}/drafts` 提交草案
- [ ] POST `/discussions/{id}/judge` 裁判评估
- [ ] GET `/discussions/{id}` 获取研讨详情

### Task 2.5: 前端研讨界面
- [ ] 显示"发起群体研讨"按钮
- [ ] 研讨房间 UI
- [ ] 草案提交表单
- [ ] 裁判评估结果展示

---

## Phase 3: 社交记忆系统

### Task 3.1: 数据库扩展 - 交互日志
- [ ] 创建 interaction_logs 表
- [ ] 记录协作、帮助、研讨等行为

### Task 3.2: 实现社交记忆 Hub
- [ ] 创建 SocialMemoryHub 类
- [ ] log_interaction() 方法
- [ ] get_friend_logs() 方法
- [ ] update_intimacy() 方法 (动态更新亲密度)

### Task 3.3: 亲密度更新逻辑
- [ ] 协作成功 +0.2
- [ ] 帮助解决问题 +0.5
- [ ] 长期无交互衰减

### Task 3.4: 添加社交记忆 API
- [ ] GET `/nodes/{id}/friend-logs` 查询好友经验
- [ ] POST `/interactions/log` 记录交互

### Task 3.5: 前端好友经验界面
- [ ] 显示"查看好友经验"按钮
- [ ] 基于关键词检索好友相关日志
- [ ] 展示历史处理案例

---

## Phase 4: 求助系统

### Task 4.1: 数据库扩展 - 求助表
- [ ] 创建 help_requests 表
- [ ] 支持定向和广播求助

### Task 4.2: 实现求助 Hub
- [ ] 创建 HelpHub 类
- [ ] create_help_request() 方法
- [ ] respond_to_help() 方法
- [ ] accept_solution() 方法

### Task 4.3: 添加求助 API
- [ ] POST `/help/request` 发起求助
- [ ] POST `/help/{id}/respond` 响应求助
- [ ] POST `/help/{id}/accept` 采纳方案

### Task 4.4: 前端求助界面
- [ ] 显示"发起求助"按钮
- [ ] 定向/广播求助选择
- [ ] 求助大厅列表
- [ ] 响应/采纳功能

---

## Phase 5: 对比实验框架

### Task 5.1: 数据库扩展 - 实验表
- [ ] 创建 experiments 表
- [ ] 记录单任务 vs 群体智能效果

### Task 5.2: 实验记录
- [ ] 记录每次悬赏的结算结果
- [ ] 记录研讨前后的效果对比
- [ ] 生成对比报告

---

## Task Dependencies

```
Phase 1 (Token 结算)
├── Task 1.1 (DB扩展)
├── Task 1.2 (修改发布逻辑)
├── Task 1.3 (结算方法)
└── Task 1.4 (结算API)

Phase 2 (共识研讨) - 依赖 Phase 1
├── Task 2.1 (DB扩展)
├── Task 2.2 (研讨Hub)
├── Task 2.3 (LLM评估)
├── Task 2.4 (研讨API)
└── Task 2.5 (前端界面)

Phase 3 (社交记忆) - 可独立
├── Task 3.1 (DB扩展)
├── Task 3.2 (社交Hub)
├── Task 3.3 (亲密度逻辑)
├── Task 3.4 (API)
└── Task 3.5 (前端)

Phase 4 (求助系统) - 可独立
├── Task 4.1 (DB扩展)
├── Task 4.2 (求助Hub)
├── Task 4.3 (API)
└── Task 4.4 (前端)

Phase 5 (对比实验) - 可独立
├── Task 5.1 (DB扩展)
└── Task 5.2 (实验记录)
```

---

## 关键技术点

| Phase | 技术点 | 说明 |
|-------|--------|------|
| 1 | 事务处理 | Token 冻结/解冻需要事务保证一致性 |
| 2 | LLM Prompt | 裁判评估需要设计高质量 prompt |
| 2 | JSON 解析 | LLM 返回需要可靠解析 |
| 3 | JSON 存储 | interaction_logs 使用 JSON 存储上下文 |
| 4 | 消息通知 | 求助需要实时通知被求助方 |
