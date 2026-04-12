# 分布式协作悬赏系统——最终版技术设计文档（含共识驱动、社交记忆与 Token 生态）

***

## 文档版本

| 版本   | 日期         | 变更说明                                        |
| :--- | :--------- | :------------------------------------------ |
| v3.0 | 2026-04-10 | 整合评级奖励、Skill可视化、邻居网络、对比实验、共识研讨、社交记忆、Token经济 |

***

## 1. 系统总览

本系统构建了一个**去中心化 Agent 协作网络**，节点通过悬赏任务进行能力交换，并通过**共识机制**将个体经验提炼为群体技能。整个生态由 **Token 经济** 驱动，激励高质量贡献与利他行为。

核心业务闭环：

```
节点发布悬赏（消耗 Token）
      ↓
邻居节点自动接收任务（基于亲密度关系网）
      ↓
邻居执行并提交反馈
      ↓
系统自动评分 → 发布者结束悬赏 → 评级并发放 Token 奖励
      ↓
发布者可触发“群体研讨” → 裁判 Agent 评估 → 产出共识 Skill 存入公共库
      ↓
节点可基于社交记忆查询好友经验、发起求助
      ↓
调用高级 Skill 需消耗 Token
```

***

## 2. Token 激励生态设计

### 2.1 Token 定义

- **名称**：`COIN`（Collaboration Intelligence Token）
- **最小单位**：1 COIN = 100 分（整数计算，避免浮点误差）
- **用途**：
  - 发布悬赏（消耗）
  - 调用高级/共识 Skill（消耗）
  - 发起群体研讨（消耗）
  - 获取奖励（收入）
  - 转账/赠予

### 2.2 Token 账户表

```sql
CREATE TABLE token_accounts (
    node_id TEXT PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,          -- 余额，单位：分
    total_earned INTEGER DEFAULT 0,              -- 累计收入
    total_spent INTEGER DEFAULT 0,               -- 累计支出
    frozen_balance INTEGER DEFAULT 0,            -- 冻结金额（如发布悬赏抵押）
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (node_id) REFERENCES nodes(id)
);
```

### 2.3 Token 交易流水表

```sql
CREATE TABLE token_transactions (
    id TEXT PRIMARY KEY,
    from_node_id TEXT,                           -- 支出方
    to_node_id TEXT,                             -- 收入方
    amount INTEGER NOT NULL,                     -- 金额（分）
    transaction_type TEXT NOT NULL,              -- 类型见下文
    reference_id TEXT,                           -- 关联的业务 ID（如 bounty_id, skill_id）
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_node_id) REFERENCES nodes(id),
    FOREIGN KEY (to_node_id) REFERENCES nodes(id)
);
```

### 2.4 Token 获取途径（收入）

| 行为                 | 奖励规则               | 交易类型                     |
| :----------------- | :----------------- | :----------------------- |
| 提交高质量反馈（评级 S/A/B）  | 基础奖励 × 评级系数（见 1.3） | `bounty_reward`          |
| 创建的 Skill 被采纳为共识技能 | 一次性奖励 50 COIN      | `consensus_skill_author` |
| 在群体研讨中提出被采纳的草案     | 每次 10 COIN         | `consensus_contributor`  |
| 帮助他人（响应求助并解决问题）    | 求助方支付的悬赏金          | `help_reward`            |
| 节点间转账              | 自由金额               | `transfer`               |

### 2.5 Token 消耗途径（支出）

| 行为                  | 消耗规则                   | 交易类型                   |
| :------------------ | :--------------------- | :--------------------- |
| 发布悬赏                | 基础悬赏金 + 附加奖励总额（抵押）     | `bounty_create`        |
| 调用高级 Skill（非基础内置能力） | 按次计费（由 Skill 创建者定价）    | `skill_usage`          |
| 发起群体研讨              | 每次 20 COIN（用于激励裁判与参与者） | `consensus_discussion` |
| 主动求助（广播求助任务）        | 发布者设定的求助赏金             | `help_request`         |

### 2.6 悬赏结算时的 Token 流转

发布悬赏时，发布者的 Token 被**冻结**（抵押）。结算时：

1. 按评级结果计算每个邻居应得奖励。
2. 从冻结金额中扣减发放，剩余部分退回发布者账户。
3. 若冻结金额不足（极少情况），按比例分配或记录欠款。

```python
def settle_bounty_with_token(bounty_id):
    # 1. 获取悬赏信息及冻结金额
    # 2. 计算总发放奖励
    # 3. 更新各邻居账户余额，插入交易记录
    # 4. 退还剩余金额给发布者
    # 5. 标记悬赏为已结算
```

***

## 3. 共识驱动的技能演化

### 3.1 触发条件

群体研讨可由以下事件触发（满足任一）：

- **高价值任务**：发布者设置的悬赏金额 ≥ 阈值（如 100 COIN）。
- **普遍失败**：多个邻居提交的评分均低于 40 分，且发布者点击“求助研讨”。
- **手动触发**：发布者在结算后认为有必要提炼共识时，可手动发起研讨。

### 3.2 研讨参与者

- **提议者**：参与过该悬赏的邻居节点（至少提交过内容）。
- **裁判 Agent**：由系统指定的中立评估节点（可以是特殊的高信誉节点或 LLM 服务）。

### 3.3 研讨流程

```
发布者触发“发起群体研讨”
      ↓
系统创建研讨房间（discussion_room），通知所有提议者
      ↓
提议者提交 Skill 草案（名称、能力描述、使用方法）
      ↓
收集时间截止后，裁判 Agent 对所有草案进行评估：
   - 可执行性
   - 通用性
   - 与任务相关性
      ↓
裁判输出“最佳草案”或“合并草案”作为共识技能
      ↓
将共识技能存入公共知识库，标记为 `consensus` 类型
      ↓
奖励提议者：被采纳草案的作者获得主要奖励，其他参与者获参与奖励
      ↓
记录研讨日志，更新相关节点的“社交记忆”
```

### 3.4 研讨数据库表

```sql
CREATE TABLE discussion_rooms (
    id TEXT PRIMARY KEY,
    bounty_id TEXT NOT NULL,
    initiator_id TEXT NOT NULL,
    status TEXT CHECK(status IN ('open', 'closed', 'completed')) DEFAULT 'open',
    judge_type TEXT DEFAULT 'llm',              -- llm 或 high_rep_node
    judge_id TEXT,                              -- 裁判节点 ID
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP,
    consensus_skill_id TEXT,
    FOREIGN KEY (bounty_id) REFERENCES bounties(id)
);

CREATE TABLE discussion_drafts (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    proposer_id TEXT NOT NULL,
    draft_name TEXT NOT NULL,
    draft_capability TEXT NOT NULL,
    draft_usage TEXT,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_selected BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (room_id) REFERENCES discussion_rooms(id)
);
```

### 3.5 裁判评估逻辑（LLM 模式）

```python
async def evaluate_drafts(drafts: List[dict], task_description: str):
    prompt = f"""
    任务描述：{task_description}
    
    以下是多个 Agent 提出的 Skill 草案：
    {format_drafts(drafts)}
    
    请选出最优草案，或基于它们整合出一个共识草案，以 JSON 返回：
    {{
        "selected_draft_id": "xxx",  // 若直接选用某一草案
        "merged_skill": {{           // 若合并，则填写此字段
            "name": "...",
            "capability": "...",
            "usage": "..."
        }},
        "reason": "选择理由"
    }}
    """
    # 调用 LLM 并解析结果
```

### 3.6 共识技能入库标记

在 `public_knowledge` 表中增加字段区分来源：

```sql
ALTER TABLE public_knowledge ADD COLUMN skill_type TEXT DEFAULT 'manual';
-- 可选值：'manual'（人工总结）、'consensus'（共识研讨产出）
ALTER TABLE public_knowledge ADD COLUMN discussion_room_id TEXT;
```

***

## 4. 社交记忆与选择性求助

### 4.1 好友关系图谱（基于交互日志）

在原有的静态边关系基础上，增加**动态亲密度**计算，基于以下行为自动更新：

- 成功协作完成悬赏（双方评级均≥B） → 亲密度 +0.2
- 一方帮助另一方解决问题 → 亲密度 +0.5
- 长期无交互 → 亲密度随时间衰减（每月 -0.1）

亲密度取值范围 0\~10。

### 4.2 交互日志表

```sql
CREATE TABLE interaction_logs (
    id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    action_type TEXT NOT NULL,   -- 'collaborate', 'help', 'discuss', 'query_log'
    context JSON,                -- 存储任务描述、结果等
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

每次悬赏结算、研讨参与、求助响应均记录日志。

### 4.3 回放好友处理日志

当节点遇到新任务时，可查询好友在类似任务上的历史提交内容。

```python
@app.get("/nodes/{node_id}/friend-logs")
async def get_friend_logs(node_id: str, task_keywords: str):
    """基于任务关键词检索好友的相关交互日志"""
    # 1. 获取该节点的所有好友（亲密度>0的邻居）
    # 2. 搜索好友的 submission 内容中包含关键词的记录
    # 3. 返回结构化摘要
```

前端在任务执行界面提供“查看好友经验”按钮，展示相关案例。

### 4.4 主动求助机制

节点在执行任务遇到困难时，可发起**定向求助**或**广播求助**：

- **定向求助**：选择特定好友，发送求助请求（附上问题描述和悬赏金额）。
- **广播求助**：向所有邻居（或亲密度超过阈值的邻居）广播求助任务。

求助任务本质上是一个**小型悬赏**，回答被采纳后求助者支付 Token。

```python
@app.post("/help/request")
async def create_help_request(req: HelpRequest):
    # 创建求助记录，若定向则通知指定节点，否则广播
    # 冻结求助者 Token 作为赏金
```

***

## 5. 整合后的业务流程全景图

### 5.1 悬赏生命周期

```
[发布者] 创建悬赏 → 消耗 Token（冻结）
        ↓
[系统] 自动分发给所有邻居（基于边关系）
        ↓
[邻居] 执行任务，提交反馈
        ↓
[系统] 自动评分（LLM 或规则）
        ↓
[发布者] 查看反馈排行榜，可结束悬赏
        ↓
[系统] 结算：评级、发放 Token、更新亲密度
        ↓
[发布者] 可选操作：
   ├─ 手动整理 Skill → 存入公共库（manual 类型）
   ├─ 发起群体研讨 → 产出共识 Skill（consensus 类型）
   └─ 查看实验对比数据（单任务 vs 群体智能）
```

### 5.2 求助与经验回放流程

```
[节点A] 执行任务中遇到困难
        ↓
[节点A] 查询好友经验 → 参考类似案例日志
        ↓
若仍未解决 → 发起求助（定向/广播）
        ↓
[节点B] 收到求助，提供解决方案
        ↓
[节点A] 采纳方案 → 支付 Token 给 B → 更新亲密度
```

***

## 6. 最终数据模型总览

### 6.1 核心表关系

```
nodes
  ├─ token_accounts (1:1)
  ├─ node_edges (多对多，存储亲密度)
  └─ interaction_logs (1:N)

bounties
  ├─ submissions (1:N) + score, final_grade, reward_amount
  ├─ reward_transactions (1:N)
  └─ discussion_rooms (1:1)

discussion_rooms
  └─ discussion_drafts (1:N)

public_knowledge
  ├─ skill_type, discussion_room_id (用于共识技能)

help_requests (新表，用于求助)
  ├─ requester_id
  ├─ target_id (可选，为空表示广播)
  ├─ bounty_amount
  └─ status

experiments (对比实验记录)
```

***

## 7. 实施优先级建议

| 阶段   | 功能模块                   | 优先级 |
| :--- | :--------------------- | :-- |
| 第一阶段 | 评级与 Token 奖励发放（基础经济闭环） | 高   |
| 第一阶段 | Skill 可视化编辑与预览（文件名、预览） | 高   |
| 第二阶段 | 邻居关系网络（静态边、序号）、任务自动分发  | 高   |
| 第三阶段 | 社交记忆：交互日志、亲密度动态更新      | 中   |
| 第四阶段 | 共识研讨：房间、草案、裁判评估        | 中   |
| 第五阶段 | 求助系统、好友经验回放            | 中   |
| 第六阶段 | 对比实验框架                 | 低   |

***

## 8. 附录：关键 API 列表

| 方法   | 路径                            | 描述              |
| :--- | :---------------------------- | :-------------- |
| POST | `/bounties`                   | 创建悬赏（冻结 Token）  |
| POST | `/bounties/{id}/settle`       | 结算悬赏，发放奖励       |
| POST | `/bounties/{id}/curate-skill` | 手动整理 Skill      |
| POST | `/bounties/{id}/discussion`   | 发起群体研讨          |
| GET  | `/discussions/{id}/drafts`    | 获取研讨草案          |
| POST | `/discussions/{id}/judge`     | 触发裁判评估（通常自动）    |
| POST | `/help/request`               | 发起求助            |
| GET  | `/nodes/{id}/friend-logs`     | 查询好友经验          |
| GET  | `/public-skills`              | 获取公共技能库（支持类型筛选） |
| POST | `/nodes/friend`               | 手动建立好友关系        |

***

这份最终版文档将您提出的所有理念——自动评分、评级奖励、Skill 可视化、邻居网络、对比实验、共识研讨、社交记忆、Token 生态——有机融合，形成一个自洽、可落地的技术方案。如有任何部分需要进一步展开代码实现细节，请随时告知。
