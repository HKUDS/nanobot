# Hermes 自进化能力设计（nanobot-enhance）

> 分支：已合并至 `main`（原 `feature/hermes-self-evolution`）  
> 状态：**已实现**（E0–E4 + Phase F/G；E5 WebUI / E6 可选未做）  
> 最后更新：2026-05-26

本文档记录将 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 式自进化能力集成到 nanobot 的设计决策与实施计划。GEPA 离线优化细节见 [`.agent/gepa.md`](./gepa.md)。

---

相关：**分层记忆**（TencentDB 式 L0–L3 + Task Canvas）见 [`.agent/layered-memory/design.md`](./layered-memory/design.md) 与 [`plan.md`](./layered-memory/plan.md)。与 Evolution（Skill/trace）正交：L1 存用户事实，不写 `skills/`。

---

## 1. 背景与目标

### 1.1 nanobot 已有能力

| 能力 | 位置 | 说明 |
|------|------|------|
| Skill 体系 | `nanobot/skills/`, `workspace/skills/` | agentskills.io 标准，`SKILL.md` |
| FTS/BM25 检索 | `nanobot/agent/skill_index.py` | SQLite FTS5，渐进式 skill 加载 |
| LLM skill 选择 | `nanobot/agent/skill_selector.py` | fts / llm / hybrid / auto 模式 |
| Dream 记忆整理 | `nanobot/agent/memory.py` | 两阶段，可写 MEMORY/SOUL/USER/skills |
| GitStore 版本控制 | `nanobot/utils/gitstore.py` | Dream 变更可 `/dream-restore` |
| skill-creator | `nanobot/skills/skill-creator/` | Skill  authoring 规范 |
| AgentHook | `nanobot/agent/hook.py` | 生命周期扩展点 |

### 1.2 Hermes 自进化核心（参考）

- **Closed learning loop**：复杂任务后自动沉淀 procedural knowledge 为 Skill
- **skill_manage**：读、评、改 skill（我们拆分为 PostTask create + GEPA update）
- **GEPA 离线优化**：[hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution) — DSPy + GEPA 从 traces 进化 SKILL.md
- **约束**：conversation 中途不改 skill；变更需审核；语义不漂移

### 1.3 目标边界（已定）

**两个都要：**

1. **Learning loop MVP** — PostTask 触发，任务后自动 **create** 新 skill
2. **GEPA 离线优化** — 批量 **update** 已有 skill，measurable 质量提升

---

## 2. 已定决策

| # | 问题 | 决策 |
|---|------|------|
| 1 | auto_apply | **留开关**：默认 `false`（提案 + 审核）；个人 trusted workspace 可设 `true` 直接写入 |
| 2 | PostTask 范围 | **MVP 只允许 create**；update 全部交给 GEPA |
| 3 | Dream vs PostTask | **方案 A**：Dream Phase 2 **移除 `[SKILL]` 创建**；skill 沉淀 exclusively PostTask |
| 4 | GEPA 依赖 | **接受** `dspy` 作为 optional extra：`pip install nanobot[evolution]` |

### 2.1 设计原则（对齐 `.agent/design.md`）

- **Core stays small**：`loop.py` / `runner.py` 仅加 turn 后一行调用 + Trace 采集
- **Extend at edges**：新子系统 `nanobot/agent/evolution/`，新 tool、新 slash commands
- **Explicit config**：`EvolutionConfig` in `config/schema.py`
- **Security**：只写 `workspace/skills/`；不自动改 Python 源码或 templates
- **Turn 内只记录，Turn 外才进化** — 避免与 SkillIndex generation / prompt cache 冲突

---

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────┐
│ 每轮 Turn                                                │
│  skill 检索 (FTS+LLM) → AgentRunner → PostTask Evolver   │
└─────────────────────────────────────────────────────────┘
         ↑ consume                              ↓ produce
    SkillIndex                          skills/.proposals/ 或 skills/<name>/

┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Dream (cron) │     │ Heartbeat      │     │ GEPA (cron)  │
│ MEMORY/SOUL  │     │ （可选 nudge） │     │ skill update │
│ USER only    │     │                │     │ diff 提案    │
└──────────────┘     └──────────────┘     └──────────────┘
```

### 3.1 职责分工

| 子系统 | 触发 | 输入 | 输出 | skill 操作 |
|--------|------|------|------|------------|
| **PostTask Evolver** | turn 结束，tool_calls ≥ N | 单 turn trace | create proposal 或 auto apply | **create only** |
| **GEPA Runner** | cron / CLI | TraceStore + active skills | update proposal | **update only** |
| **Dream** | cron / `/dream` | history.jsonl 批量 | MEMORY / SOUL | **none（方案 A）**；**USER 由 Layered Memory L3 写**（`layeredMemory.persona.enable` 时 Dream 跳过 USER.md 编辑） |
| **Skill 检索** | 每 turn | user query | top-k skills 注入 prompt | consume |

### 3.2 闭环

```
retrieve → execute → trace → evolve (create/update) → re-index → retrieve
```

进化应优先优化 skill 的 **frontmatter `description`**（BM25 与 LLM 路由均依赖它）。

---

## 4. 模块规格

### 4.1 E0 — TraceRecorder（共用底座）

**挂载点**：`_run_agent_loop` 返回之后（与 `_resolve_turn_skill_entries` 对称）。

**`_run_agent_loop` 已有返回值**（`loop.py`）：

```
(final_content, tools_used, messages, stop_reason, had_injections)
```

**Trace 字段（最小集）**：

```json
{
  "trace_id": "uuid",
  "session_key": "...",
  "turn_id": "...",
  "timestamp": "ISO8601",
  "query": "用户原始意图",
  "skills_injected": ["cron", "github"],
  "tool_calls": [
    {"name": "exec", "args_summary": "...", "ok": true, "duration_ms": 120}
  ],
  "tool_call_count": 7,
  "iterations": 3,
  "stop_reason": "completed",
  "outcome": "success",
  "token_usage": {"prompt": 12000, "completion": 800}
}
```

**存储**：`{workspace}/.nanobot/traces.sqlite`（与 skill_index 同目录风格；GEPA 需检索）。

**保留策略**：默认 30 天；GEPA 跑批后可标记 `used_for_evolution=true`。

**采集方式（MVP）**：turn 结束后从 `all_msgs` 一次性解析（改动小于 Hook 逐 iteration 采集）。

---

### 4.2 E1 — PostTask Evolver（仅 create）

**触发条件（全部满足）**：

- `evolution.enable == true`
- `tool_call_count >= evolution.min_tool_calls`（默认 5）
- `stop_reason` 为成功态（如 `completed`）
- 非 subagent turn（`is_subagent=True` 跳过）
- `tools_used` 非空
- 冷却：同 session `evolution.cooldown_minutes` 内最多 1 次（默认 5）

**LLM 判定输出（严格 schema）**：

```json
{
  "action": "none" | "create_skill",
  "skill_name": "kebab-case",
  "rationale": "...",
  "confidence": 0.85
}
```

**硬规则**：

- 若模型输出 update 意图 → **强制降为 `none`**，log：`update deferred to GEPA`
- `confidence < evolution.min_confidence`（默认 0.7）→ 只记 trace，不提案
- 创建前 **dedup**：SkillIndex catalog + 待审核 proposals 同名检查
- apply 时若 `skills/<name>/` 已存在 → **拒绝**，提示「update 请等 GEPA」

**产出路径**：

| `auto_apply` | 行为 |
|--------------|------|
| `false` | `skills/.proposals/<uuid>/SKILL.md` + `meta.json` |
| `true` | 直接 `skills/<name>/SKILL.md` + EvolutionGitStore commit |

**`meta.json` 示例**：

```json
{
  "proposal_id": "uuid",
  "source": "post_task",
  "trace_id": "...",
  "skill_name": "deploy-k8s",
  "rationale": "...",
  "confidence": 0.85,
  "created_at": "ISO8601",
  "status": "pending"
}
```

**用户通知（可选）**：

- proposal：`已生成 skill 提案「deploy-k8s」，/evolve-show <id> 查看`
- auto_apply：`已自动创建 skill「deploy-k8s」`

**Skill 内容规范**：参考 `skill-creator` SKILL.md 与 Dream phase2 既有规则（frontmatter、≤2000 words、dedup、工具引用）。

---

### 4.3 E2 — 审核命令 + EvolutionGitStore

**Slash commands**（对标 Dream 的 `/dream-log`）：

| 命令 | 行为 |
|------|------|
| `/evolve-list` | 列出待审核 proposals |
| `/evolve-show <id>` | 内容 + rationale + 关联 trace 摘要 |
| `/evolve-apply <id>` | proposal → active，`SkillIndex` rebuild，Git commit |
| `/evolve-reject <id>` | 标记 rejected / 移入 `.rejected/` |
| `/evolve-log` | skill 变更 commit 历史 |
| `/evolve-restore <sha>` | 回滚某次 skill 变更 |
| `/evolve-run [skill]` | 手动触发 GEPA 离线优化（后台运行） |
| `/evolve-status` | 查看最近一次 GEPA run 状态 |

**CLI**（无需 gateway）：`nanobot evolve run [--skill NAME]`、`nanobot evolve status`

**EvolutionGitStore（独立实例，方案 A）**：

- **tracked**：`skills/**`（**排除** `.proposals/`, `.archive/`, `.rejected/`）
- **commit 前缀**：`evolve: create skill deploy-k8s` / `evolve: update skill xxx (gepa)`
- 与 Dream GitStore（MEMORY/SOUL/USER）**分离**，`/evolve-restore` 与 `/dream-restore` 互不影响

Dream 当前 tracked（`memory.py`）：

```
SOUL.md, USER.md, memory/MEMORY.md, memory/.dream_cursor
```

**apply 流程**：

1. GitStore snapshot（apply 前）
2. proposal → `skills/<name>/SKILL.md`
3. `SkillIndex.warm()` / generation 失效
4. 可选通知用户

**proposal 过期**：30 天未 apply 自动 archive（可配置，默认开）。

---

### 4.4 E3 — Dream 改造（方案 A）

**改动**：

- `templates/agent/dream_phase2.md`：删除 `[SKILL]` 条目与 skill 创建规则
- Dream Phase 2 工具集：移除对 `skills/` 的 `WriteFileTool`（或 prompt 硬禁止）
- Dream 仅维护：`MEMORY.md`, `SOUL.md`, `USER.md`

**理由**：单一 skill 生产入口；避免 batch history 与单 turn PostTask 重复创建。

---

### 4.5 E4 — GEPA 层（仅 update，offline）✅

> **实现清单与进度**：见 [`.agent/gepa.md`](./gepa.md)（Phase A–H）。

**依赖**：`pip install nanobot-ai[evolution]` → 安装 `dspy`（optional extra，未安装时 gateway 仍可启动，GEPA 运行时会提示）。

**触发**：

- Gateway cron：`evolution.gepa.enable` + `intervalHours` → 注册 `evolve-gepa` system job
- CLI：`nanobot evolve run [--skill NAME]`
- Slash：`/evolve-run [skill]`

**输入**：

- TraceStore 中 `outcome=success` 的 traces
- 已有 **active** skills（`skills/<name>/SKILL.md`）

**输出**：

- 永远是 **update proposal**（同 PostTask 审核队列）：
  - `skills/.proposals/<uuid>/SKILL.md`
  - `meta.json`：`source: "gepa"`, `base_skill`, `base_sha`, `evaluation_score`

**约束（对齐 Hermes self-evolution）**：

- 不 mid-conversation 改 skill
- description 语义不漂移（apply 前硬校验）
- 预算上限：`evolution.gepa.maxBudgetUsd`（默认 10）
- GEPA **从不 auto_apply**；一律走 proposal + `/evolve-apply`

**PostTask vs GEPA**：

| | PostTask | GEPA |
|--|----------|------|
| 时机 | 即时 | 批量 |
| 操作 | create | update |
| 产出 | 新 skill | 优化现有 skill |
| 审核 | proposal 或 auto_apply | 永远 proposal |

---

### 4.6 E5 — `skill_manage` tool（可选，E3 阶段）

Agent 侧 API，权限分级：

| action | PostTask Evolver | 主 Agent 对话 |
|--------|------------------|---------------|
| `propose` | ✅ | ✅ |
| `apply` | 仅 `auto_apply=true` | ❌（必须 slash command） |
| `list` / `read` | ✅ | ✅ |
| `deprecate` | ❌ | ❌ |

---

## 5. 配置（`EvolutionConfig`）

Schema 位于 `nanobot/config/schema.py`。嵌套结构（camelCase JSON 别名见各字段）：

```python
class EvolutionConfig(Base):
    enable: bool = True          # 总开关：trace + PostTask；GEPA 另需 gepa.enable

    trace: EvolutionTraceConfig       # retention_days
    post_task: EvolutionPostTaskConfig  # min_tool_calls, cooldown, auto_apply, ...
    gepa: EvolutionGepaConfig           # enable, interval_hours, max_budget_usd, ...
```

挂到 `AgentDefaults.evolution`。完整示例见 [Configuration → Skill Evolution](../docs/configuration.md#skill-evolution)。

**示例 — 审核模式 + 每周 GEPA（推荐）**：

```json
{
  "agents": {
    "defaults": {
      "evolution": {
        "enable": true,
        "postTask": {
          "autoApply": false,
          "minToolCalls": 3,
          "cooldownMinutes": 10
        },
        "gepa": {
          "enable": true,
          "intervalHours": 168,
          "maxBudgetUsd": 10,
          "minTraces": 3,
          "maxSkillsPerRun": 1
        }
      }
    }
  }
}
```

**示例 — trusted workspace（PostTask 自动写入）**：

```json
"evolution": { "enable": true, "postTask": { "autoApply": true } }
```

> GEPA 结果**始终**需 `/evolve-apply` 审核，不受 `postTask.autoApply` 影响。

---

## 6. 目录结构（已实现）

```
nanobot/agent/evolution/
├── trace_recorder.py          # E0
├── trace_store.py
├── post_task.py               # E1 PostTask Evolver
├── proposals.py               # E2 proposal CRUD + apply 分流
├── git_store.py               # EvolutionGitStore
├── gepa_dataset.py            # E4-D1
├── gepa_skill_module.py       # E4-D2
├── gepa_evaluator.py          # E4-D3
├── gepa_optimizer.py          # E4-D4
├── gepa_runner.py             # E4-D6/D7
├── gepa_status.py             # run 状态 + 单飞锁
└── deps.py                    # optional extra 检测

nanobot/command/evolve.py        # /evolve-* 命令
nanobot/cli/commands.py          # nanobot evolve run|status + cron
nanobot/templates/agent/
├── dream_phase2.md              # 已移除 [SKILL] 创建
├── evolution_post_task.md
└── evolution_gepa_evaluator.md

.agent/hermes-design.md          # 本文档
.agent/gepa.md                   # GEPA 分步设计与进度
.agent/plan-mode/                # Plan 模式 + 任务图（design + plan）
.agent/context-cost/             # Runtime Harness + 上下文/成本（design + plan）
```

---

## 7. 实施顺序

| 阶段 | 内容 | 状态 |
|------|------|------|
| **E0** | `EvolutionConfig` + TraceRecorder + TraceStore | ✅ |
| **E1** | PostTask Evolver（create only） | ✅ |
| **E2** | proposal 目录 + `/evolve-*` + EvolutionGitStore | ✅ |
| **E3** | Dream 去掉 `[SKILL]` | ✅ |
| **E4** | `[evolution]` extra + GEPA runner + 触发入口 | ✅ 见 [gepa.md](./gepa.md) |
| **E5** | `skill_manage` tool | 未做（可选） |
| **E6** | WebUI 审核面板 | 未做（v2）；可与 [plan-mode](./plan-mode/design.md) WebUI 共用模式 |
| **Runtime Harness** | 在线策略 + verify + checkpoint（非离线 eval） | 见 [context-cost/design.md](./context-cost/design.md) |

**MVP 交付线**：E0 → E1 → E2 → E3 — 已合并 `main`  
**完整 v1（含 GEPA）**：+ E4 — 已合并 `main`

---

## 8. 与 skill 检索（已合并 main）的关系

已实现（`feature/skills-retrive-enhance` → `main`）：

- `SkillRetrievalConfig.mode`: fts / llm / hybrid / auto
- `ContextBuilder.resolve_skill_entries()` + turn 前预解析
- BM25 / LLM 结构化日志

进化系统 **消费端** 即上述检索；**生产端** 写入 workspace skills 后需：

1. `SkillIndex.warm()` 或 rebuild
2. 优化新 skill 的 `description`（BM25 + LLM 路由关键）

未来可增强 trace：`skills_injected` vs `skills_actually_used`（若可观测 read_file 路径），供 GEPA 评估。

---

## 9. 不做的事

1. **不移植 Hermes 完整 runtime** — 复用 nanobot bus/channel/provider
2. **不让 agent 直接改 Python 源码** — 代码进化仅 GEPA + 人工 review（远期）
3. **不在 turn 中途热更新 skill**
4. **不跳过 GitStore** — 必须有 `/evolve-restore`
5. **不大改 `runner.py`** — PostTask 在 turn 边界

---

## 10. 默认行为（无需再议）

- subagent trace：记录，**不触发** PostTask
- proposal 30 天未 apply：自动 archive
- skill 命名冲突 on apply：拒绝，提示走 GEPA update
- PostTask 冷却：同 session 5 分钟内最多 1 次

---

## 11. 参考链接

- [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
- [NousResearch/hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution)
- nanobot 现有：`.agent/design.md`, `.agent/security.md`, `docs/memory.md`

---

## 12. 变更日志

| 日期 | 说明 |
|------|------|
| 2026-05-24 | 初稿：四决策定稿 + E0–E6 分期 + 架构与配置 |
| 2026-05-26 | E0–E4 实现合并 `main`；GEPA 细节链至 `gepa.md`；更新配置与命令表 |
