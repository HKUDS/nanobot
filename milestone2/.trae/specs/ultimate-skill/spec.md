# 终极 Skill 系统技术规格书

## Why

当前系统已实现基础的悬赏任务、邻居发现、Token 钱包和 Skill 可视化功能。但还需要完善：
1. **共识研讨机制** - 将个体经验提炼为群体技能
2. **社交记忆系统** - 记录交互历史，支持经验回放
3. **求助系统** - 节点间互助
4. **Token 经济闭环** - 冻结/结算/奖励分发
5. **对比实验框架** - 评估群体智能效果

---

## 当前实现状态

### ✅ 已完成
| 功能 | 文件 | 状态 |
|------|------|------|
| 悬赏 CRUD | bounty_hub.py | ✅ 完成 |
| LLM 自动评分 | evaluator.py | ✅ 完成 |
| Skill 可视化 | SkillEditor.vue | ✅ 完成 |
| 邻居发现 | bff_service.py | ✅ 双向关系 |
| Token 钱包 | token_wallet.py | ✅ 基础功能 |
| 悬赏分发 | notify_neighbors() | ✅ 完成 |

### ❌ 未完成
| 功能 | 优先级 | 难度 |
|------|--------|------|
| 共识研讨 | 中 | 高 |
| 社交记忆 | 中 | 中 |
| 求助系统 | 中 | 中 |
| Token 冻结/结算 | 高 | 中 |
| 对比实验 | 低 | 中 |

---

## What Changes

### Phase 1: Token 经济闭环 (高优先级)

#### 1.1 悬赏冻结机制
- 发布悬赏时冻结 Token (reward_pool + docker_reward)
- 结算时从冻结金额发放奖励
- 剩余退回发布者

#### 1.2 奖励分发规则
| 评级 | 奖励系数 | 说明 |
|------|----------|------|
| S | 1.5x | 极优秀 |
| A | 1.2x | 优秀 |
| B | 1.0x | 达标 |
| C | 0.5x | 勉强 |
| D | 0x | 不达标 |

#### 1.3 Token 交易流水
记录所有 Token 流转，用于审计和追溯

---

### Phase 2: 共识研讨机制 (中优先级)

#### 2.1 触发条件
- 高价值任务：悬赏金额 ≥ 100 COIN
- 普遍失败：多个邻居评分 < 40
- 手动触发：发布者主动发起

#### 2.2 研讨流程
```
发布者触发"发起群体研讨"
      ↓
系统创建研讨房间 (discussion_room)
      ↓
通知所有提议者
      ↓
提议者提交 Skill 草案
      ↓
裁判 Agent 评估草案
      ↓
产出共识 Skill 存入公共库
      ↓
奖励提议者
```

#### 2.3 裁判评估
- LLM 模式：调用 LLM 评估
- 高信誉节点模式：指定节点评估

---

### Phase 3: 社交记忆系统 (中优先级)

#### 3.1 交互日志
记录所有节点间交互：
- `collaborate`: 协作完成悬赏
- `help`: 帮助解决问题
- `discuss`: 参与研讨
- `query_log`: 查询经验

#### 3.2 亲密度动态更新
| 行为 | 亲密度变化 |
|------|-----------|
| 协作成功 (评级≥B) | +0.2 |
| 帮助解决问题 | +0.5 |
| 长期无交互 | -0.1/月 |

#### 3.3 好友经验回放
查询好友在类似任务上的历史处理经验

---

### Phase 4: 求助系统 (中优先级)

#### 4.1 求助类型
- **定向求助**: 选择特定好友发送求助
- **广播求助**: 向所有邻居或高亲密度邻居广播

#### 4.2 求助流程
```
节点遇到困难
      ↓
查询好友经验（参考）
      ↓
若未解决 → 发起求助
      ↓
收到求助的节点提供方案
      ↓
求助者采纳 → 支付 Token → 更新亲密度
```

---

### Phase 5: 对比实验框架 (低优先级)

记录单任务 vs 群体智能的效果对比数据

---

## Impact

### Affected Code
| 模块 | 文件 | 改动量 |
|------|------|--------|
| 数据库 | db.py | 中 |
| Token 经济 | token_wallet.py | 中 |
| 悬赏结算 | bounty_hub.py | 大 |
| 共识研讨 | discussion_hub.py (新) | 大 |
| 社交记忆 | social_memory.py (新) | 中 |
| 前端 | BountyMarket.vue | 中 |

### 新增 API
| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/bounties/{id}/settle` | 结算悬赏 |
| POST | `/discussions` | 创建研讨房间 |
| POST | `/discussions/{id}/drafts` | 提交草案 |
| POST | `/discussions/{id}/judge` | 裁判评估 |
| GET | `/nodes/{id}/friend-logs` | 查询好友经验 |
| POST | `/help/request` | 发起求助 |

---

## 数据库变更

### 新增表

```sql
-- 研讨房间
CREATE TABLE discussion_rooms (
    id TEXT PRIMARY KEY,
    bounty_id TEXT NOT NULL,
    initiator_id TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    judge_type TEXT DEFAULT 'llm',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 研讨草案
CREATE TABLE discussion_drafts (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    proposer_id TEXT NOT NULL,
    draft_name TEXT NOT NULL,
    draft_capability TEXT NOT NULL,
    is_selected BOOLEAN DEFAULT FALSE
);

-- 交互日志
CREATE TABLE interaction_logs (
    id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    context JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 求助请求
CREATE TABLE help_requests (
    id TEXT PRIMARY KEY,
    requester_id TEXT NOT NULL,
    target_id TEXT,
    description TEXT NOT NULL,
    bounty INTEGER NOT NULL,
    status TEXT DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 新增字段

```sql
-- public_knowledge 表
ALTER TABLE public_knowledge ADD COLUMN skill_type TEXT DEFAULT 'manual';
ALTER TABLE public_knowledge ADD COLUMN discussion_room_id TEXT;

-- token_accounts 表 (已有部分字段)
ALTER TABLE token_accounts ADD COLUMN frozen_balance INTEGER DEFAULT 0;
```

---

## 实施优先级

| 阶段 | 功能 | 优先级 | 工作量 |
|------|------|--------|--------|
| Phase 1 | Token 结算闭环 | 高 | 中 |
| Phase 2 | 共识研讨 | 中 | 大 |
| Phase 3 | 社交记忆 | 中 | 中 |
| Phase 4 | 求助系统 | 中 | 中 |
| Phase 5 | 对比实验 | 低 | 小 |

---

## 风险与挑战

1. **LLM 裁判评估的不确定性** - 需要设计可靠的 prompt
2. **亲密度计算的公平性** - 需要防止刷亲密度的行为
3. **求助系统的滥用** - 需要设计惩罚机制
4. **Token 经济平衡** - 需要防止通货膨胀
