# Hermes Agent 自我进化机制调研

> **文档性质**：外部技术调研快照（2026-06-10）。所有论断附公开来源，请以参考链接中的最新信息为准；与 nanobot 自身的对照分析见 §4。

## 0. 目标甄别

公开信息中检索 "Hermes agent self-evolution / self-improvement" 几乎全部指向同一个项目：**Nous Research 出品的 Hermes Agent**（仓库 <https://github.com/NousResearch/hermes-agent> ，文档 <https://hermes-agent.nousresearch.com/docs/> ）。它是一个开源的、自我改进的 AI agent 框架，与 Hermes 系列 LLM（同公司出品）共用品牌但相互独立——agent 本身可以接 200+ 模型（OpenRouter、Nous Portal、NVIDIA NIM 等）。

候选排序：

1. **主选**：Nous Research 的 hermes-agent（agent 框架）+ 配套独立仓库 hermes-agent-self-evolution（专门做"自进化优化管线"）。
2. **次要**：NVIDIA 在博客中介绍的 "Self-Improving AI Agent"（<https://blogs.nvidia.com/blog/rtx-ai-garage-hermes-agent-dgx-spark/> ），实际就是 Hermes Agent 的硬件优化版。
3. 排除：与 Hermes LLM 模型（Hermes 3/4）混淆——那只是模型，不是自进化 agent。

下文均指 Hermes Agent。

## 1. Hermes Agent 概述

宣传语："The self-improving AI agent built by Nous Research. The only agent with a built-in learning loop."

核心组件（来源：<https://hermes-agent.nousresearch.com/docs/developer-guide/architecture> ）：

- **AIAgent Loop**（`run_agent.py`）：同步编排引擎，处理 provider 选择、prompt 拼装、工具执行、重试/回退、压缩、持久化。
- **Terminal Backends**：Local / Docker / SSH / Singularity / Modal / Daytona，多种沙箱后端。
- **Gateway Process**：把 Telegram、Discord、Slack、WhatsApp、Signal、Email 等通道统一接进来。
- **Skill System**：过程性记忆（procedural memory）；skill 文件 `SKILL.md` 放在 `~/.hermes/skills/`，遵循 [agentskills.io](https://agentskills.io) 标准。
- **Memory Subsystem**：SQLite + FTS5 全文搜索；跨 session 检索；集成 Honcho 做 dialectic 用户建模。
- **Tool Framework**：70+ 工具，28 个工具集；插件来源三处（用户目录、项目目录、pip entry points）。

设计原则（关键差异化）：

- **学习回路是一等架构对象**——不是事后 plugin。
- **Prompt 三层稳定性**：stable（identity/tools/skills）→ context（项目文件）→ volatile（memory/profile/timestamp），目的是不打破 prompt cache。
- 平台无关核心：同一个 AIAgent 同时服务 CLI、Gateway、ACP、batch、HTTP API。

## 2. 自我进化机制（核心）

Hermes 的"自进化"分**两层**，理解时必须把它们分开：

| 层 | 仓库/位置 | 触发方 | 评估方 | 持久化 |
|---|---|---|---|---|
| **运行时学习回路**（轻量、在线） | hermes-agent 主仓库 | agent 自己（任务结束、错误恢复） | 真实使用计数 + 周期性 LLM 审议 | `~/.hermes/skills/`、SessionDB |
| **离线进化优化**（重量、人审） | hermes-agent-self-evolution（独立仓） | 工程师 / CI | LLM-as-judge + benchmark gate | git PR |

### 2.1 架构总览

```
┌──────────────────── 运行时学习回路 ────────────────────┐
│                                                        │
│   AIAgent Loop                                         │
│      │                                                 │
│      ├── 任务完成 (≥5 工具调用 / 用户纠正 / 错误恢复)   │
│      │      └─→ skill_manage create/patch/edit         │
│      │                                                 │
│      ├── 每 15 个任务 → 自我表现评估 (success/failure) │
│      │                                                 │
│      └── Curator (周期 7 天，幂等)                     │
│             ├─ Phase 1 确定性状态机                    │
│             │     active → stale (30d) → archive (90d) │
│             └─ Phase 2 aux-model 复审 (max_iter=8)     │
│                   keep / patch / consolidate / archive │
│                                                        │
│   存储：~/.hermes/skills/、~/.hermes/logs/curator/     │
└────────────────────────────────────────────────────────┘

┌──────────────────── 离线进化管线 ──────────────────────┐
│                                                        │
│   hermes-agent-self-evolution (独立仓)                 │
│      │                                                 │
│      ├── DSPy + GEPA      → skills / 提示 / 工具描述   │
│      ├── DSPy MIPROv2     → few-shot / 指令文本        │
│      └── Darwinian Evolver → 实现代码（外部 CLI、AGPL）│
│                                                        │
│   读取 hermes-agent 制品 → 评估 → 变异 → benchmark 闸  │
│   → 生成 PR（人工 review 合并）                        │
└────────────────────────────────────────────────────────┘
```

### 2.2 进化触发与回路

**Skill 的诞生（运行时）**：以下场景自动调用 `skill_manage`：

- 复杂任务成功完成（>=5 次工具调用）
- 经过若干次错误后找到可行解
- 用户给出明确纠正
- 识别出可重用工作流

**Skill 的精炼（运行时）**：在使用过程中通过 `patch`（小改）或 `edit`（重写）原地更新；这是 agent **直接改自己的指令**而不需要人介入。

**周期性自评估**：每 15 个任务，agent 复盘整体表现，分析 success/failure（来源：<https://lushbinary.com/blog/hermes-agent-developer-guide-setup-skills-self-improving-ai/> ）。

**Curator（默认 7 天 + 至少 idle 2 小时）**——这是 Hermes 的核心创新：把"删旧 skill / 合并相似 skill / 修补漂移"做成一个独立的周期性后台 agent，而不是塞进每次任务里。其两阶段设计：

1. **Phase 1（确定性、无 LLM）**：纯基于 telemetry（view_count / use_count / patch_count）做状态机：active → stale (30d) → archive (90d)。
2. **Phase 2（aux-model 单遍审议，max_iterations=8）**：用一个**辅助模型**（不是主对话模型）跑一次，每个 skill 决策一种动作：**keep / patch / consolidate / archive**。Aux 客户端独立于主 session，**不污染主 prompt cache**。

**离线进化（hermes-agent-self-evolution）**：人工触发或 CI 调度。GEPA（Genetic-Pareto Prompt Evolution，集成在 DSPy 里）从执行轨迹读出"为什么失败"，提出靶向变异；3 个样例就能起步；只动文本/代码，不训权重。

### 2.3 评估与验证

**运行时层（Curator）**：用真实 telemetry——views、uses、patches——而不是模型猜测。

**离线层（GEPA / MIPROv2）**：

- **数据来源 4 种分级**：A 合成（强模型读目标后造样例）、B SessionDB 挖掘（用 LLM-as-judge 给真实对话打分）、C 手工 golden set、D 任务自评测（如埋 bug 跑 debug skill 看是否修复）。
- **Fitness**：LLM-as-judge + 评分细则（rubric），常见维度：是否遵循流程 (0-1) / 输出是否正确 (0-1) / 是否在 token 预算内简洁 (0-1)。
- **5 道闸门约束**：
  1. 全测试套件通过（100%）
  2. 大小限制（skill ≤15KB；tool description ≤500 字符 / 每参数 ≤200 字符）
  3. Prompt cache 兼容
  4. 语义保真
  5. 必须经 PR 人审，**永不自动合并**

每阶段成功门槛是量化的：例如 Phase 1（skill 进化）要求 ≥1 个 skill 提升 ≥10%、benchmark 不退化；Phase 3（system prompt 进化）对 benchmark 退化是**零容忍**。

### 2.4 持久化与版本管理

- Skill：`~/.hermes/skills/<name>/SKILL.md`，YAML frontmatter（name/description/version/platform/requires_toolsets）。
- 归档：`~/.hermes/skills/.archive/`，可通过 `hermes curator restore` 恢复。
- Bundled skills 用 content hash（`.bundled_manifest`）跟踪——用户改过的不会被升级覆盖。
- 离线进化产物：git 分支 + PR + 指标对比报告（before/after），出问题 `git revert`。
- 审计：每次 Curator run 写两份产物——`run.json`（机读）+ `REPORT.md`（人读），含状态转换 + LLM 决策；当发生 consolidation 时附 rename-map（旧名→新名）。

### 2.5 安全约束（防进化失控）

Hermes 把 Curator 的"删/改自由度"卡得很紧（<https://hermes-agent.nousresearch.com/docs/user-guide/features/curator> ）：

- **永不触碰**：Hub 装的 skills（来自 agentskills.io，因为做过安全扫描，包括数据外泄/prompt injection）、bundled 内置 skills 默认仅按 idle 归档不重写（`curator.prune_builtins: false` 完全豁免）。
- **硬编码白名单**：少数 load-bearing skill（例如 `plan` 支撑 `/plan` 斜杠命令）永不可归档/合并，被排除在候选列表外，避免"静默失效"。
- **Pin 锁定**：只有 agent 创建的 skill 能被 pin；pin 后跳过自动状态转移。
- **Dry-run**：`hermes curator run --dry-run` 出报告但不动文件。
- **Aux client**：审议用辅助 provider，主对话 prompt cache 不被破坏。
- **离线进化 PR-only**：从来不直接 push 到 main。

仍存在争议：v2026.4.30 升级后曾出现升级即自动跑 Curator 把用户自建 workflow skill 一并归档的事故（<https://github.com/NousResearch/hermes-agent/issues/18373> ），社区在推动"首次运行强制 dry-run + 用户/代理来源单独标注 + 提案与执行分离"。这值得任何打算复制此机制的项目引以为戒。

## 3. 与同类工作的对比

| 体系 | 进化对象 | 评估 | 与 Hermes 关系 |
|---|---|---|---|
| **Voyager (NeurIPS'23)** | Minecraft 技能库 (JS 函数) | 任务完成度 + GPT 反思 | 同源思想：技能即程序+终身学习；Hermes 把它工程化到 LLM agent 的真实工作流 |
| **Reflexion / Self-Refine** | 对话内即时反思 | 自评分 | Hermes 的运行时回路是它的"持久化升级版"——反思结果落到 SKILL.md 而不是只活一回合 |
| **AutoGPT / BabyAGI** | 任务分解 | 无系统 fitness | 没有学习回路，与 Hermes 形成强对比 |
| **Imbue Darwinian Evolver** | 代码（git organisms） | 测试 + LLM-judge | Hermes 直接借用其思想；Phase 4 用其 CLI |
| **Promptbreeder (DeepMind)** | Prompt + mutation prompts 自指演化 | 任务准确率 | GEPA 路线的精神先驱 |
| **AlphaEvolve (DeepMind, 2025)** | 算法/代码 | 程序化 verifier | 给 Hermes 的"代码层进化"做了可行性背书 |
| **Darwin Gödel Machine** | 自我修改的 agent 程序 | 元学习 | 理论上限；Hermes 是其一个工程切片 |
| **AgentEvolver / SE-Agent (2024-2025)** | 多 agent 群体进化 | 任务奖励 | Hermes 选择"单 agent + skill 库进化"而非"agent 群体进化"，更适合个人/团队部署 |

来源：hermes-agent-self-evolution 的 PLAN.md（<https://github.com/NousResearch/hermes-agent-self-evolution/blob/main/PLAN.md> ）和 issue #337（<https://github.com/NousResearch/hermes-agent/issues/337> ）。

## 4. 对 nanobot 的可借鉴点

把 Hermes 机制映射到 nanobot 现有架构：

| Hermes 机制 | nanobot 当前对应物 | 可借鉴改造点 |
|---|---|---|
| Skill 库（`~/.hermes/skills/SKILL.md`） | `nanobot/skills/`（已有内置 skill） | **新增 "agent-authored skills"** 目录（如 `~/.nanobot/skills/agent/`），与 bundled 严格分目录、分 provenance 标签 |
| `skill_manage` 工具 | 暂无（仅有手动 `skill-creator` skill） | 给 `agent/tools/` 加一个 `skill_manage` 工具，支持 create/patch/edit/delete，触发条件套用 Hermes 经验：≥5 次 tool call / 错误恢复 / 用户纠正 |
| 每 15 任务自评估 | `memory.py` 的 Dream 二阶段巩固 | **Dream 已经是雏形**——把"15 任务"作为 Dream 的触发器之一，让 Dream 在巩固时顺便提取可复用流程到 skill |
| Curator（确定性 + aux-model 两阶段） | 暂无 | 加一个独立后台 task（用 `tools/long_task.py` / `cron.py` 调度），周期 7d，最低 idle 阈值；用**单独 provider key**做 aux 审议，不污染主 cache |
| Skill 三层渐进披露 | 当前 skill 全量加载 | 改 skill loader：先列表（标题+description），按需 expand；可显著降低 token |
| Aux client 隔离 | provider 抽象已具备 | 在 `config/schema.py` 加 `auxiliary.provider/model` 字段，curator/dream 走 aux |
| Telemetry（views/uses/patches） | session 历史 | 在 skill 文件头加计数字段，在 runner.py 命中时累加；持久化到 `~/.nanobot/skills/.telemetry.json` |
| 离线 GEPA/DSPy 管线 | 无 | **不建议第一阶段引入**——它依赖大量 benchmark 和真实评测数据，先把运行时回路打牢 |
| 安全：bundled 不可改 / hub 永不动 / 硬编码 never-archive | 无 | **必须在引入 Curator 前同时引入**：provenance 字段 (user/agent/bundled/hub)、pin/unpin、dry-run、`/curator` 命令、protect-list（保护 nanobot 的核心 skill 如 long-goal、cron） |
| LLM-as-judge with rubric | 无 | 给 Dream 巩固阶段加一个简单 rubric 评估器，作为 skill 提交前的 gate |
| PR-only 部署 | 不适用（运行时无 PR） | 离线层未来引入时再考虑；运行时层用 `--dry-run` 替代 |

> **注**：nanobot 已有的、可作为切入面的现存能力：`nanobot/agent/memory.py`（Dream 二阶段记忆 + GitStore 版本化）、`nanobot/skills/skill-creator`（手动技能创建模板）、`nanobot/skills/clawhub`（外部技能市场）、`nanobot/agent/tools/self.py`（运行时自省）、`nanobot/agent/tools/spawn.py`（subagent 派生）、`nanobot/session/goal_state.py`（持续目标）。

**最高 ROI 的三件事**（按落地难度排序）：

1. **Skill 作者来源（provenance）+ pin 机制**：哪怕暂不做 Curator，也先把"agent 写的"和"项目内置/用户写的"严格区隔。这是 Hermes 事故的根本教训。
2. **`skill_manage` 工具 + Dream 触发的 skill 提取**：把 nanobot 现有 Dream 二阶段记忆扩展为"也能产出 skill"，复用现有触发框架。
3. **Aux provider 隔离 + 周期性 Curator**：先实现 Phase 1（纯确定性，按 use_count + idle 时长归档），观察一段时间再加 LLM 审议；Curator 必须默认 dry-run 一周。

## 5. 未解疑问 / 需要进一步澄清的点

1. **目标确认**：希望参考的"Hermes 自我进化"是指**运行时学习回路**（skill 自创建/自精炼/Curator）还是**离线进化管线**（GEPA/DSPy/Darwinian Evolver）？前者是 nanobot 现实可借鉴的方向；后者门槛高（需要 benchmark + 评测数据）。
2. **借鉴深度**：是仅做知识沉淀文档，还是要直接进入 brainstorming/planning 流程，产出 nanobot 的改造提案？
3. **是否兼容 Hermes Hub 模式**：Hermes 的 skill 与 [agentskills.io](https://agentskills.io) 共享格式可发布。nanobot 是否要兼容这个开放标准（这会影响 SKILL.md 的字段设计）？
4. **离线进化数据从哪来**：如果未来引入 GEPA 路线，nanobot 的 SessionDB（即 `nanobot/session/manager.py` 的历史）是否允许被作为评测样本？需要明确隐私边界。

## 参考文献

- Hermes Agent 主仓库：<https://github.com/NousResearch/hermes-agent>
- Hermes Agent 文档站：<https://hermes-agent.nousresearch.com/docs/>
- 架构页：<https://hermes-agent.nousresearch.com/docs/developer-guide/architecture>
- Skill 系统：<https://hermes-agent.nousresearch.com/docs/user-guide/features/skills>
- Curator：<https://hermes-agent.nousresearch.com/docs/user-guide/features/curator>
- 自进化独立仓：<https://github.com/NousResearch/hermes-agent-self-evolution>
- 自进化 PLAN.md：<https://github.com/NousResearch/hermes-agent-self-evolution/blob/main/PLAN.md>
- Issue #337（Evolutionary Self-Improvement 提案）：<https://github.com/NousResearch/hermes-agent/issues/337>
- Curator 安全事故 Issue：<https://github.com/NousResearch/hermes-agent/issues/18373>
- Curator RFC：<https://github.com/NousResearch/hermes-agent/issues/16077>
- NVIDIA 博客：<https://blogs.nvidia.com/blog/rtx-ai-garage-hermes-agent-dgx-spark/>
- Lushbinary 开发者指南：<https://lushbinary.com/blog/hermes-agent-developer-guide-setup-skills-self-improving-ai/>
- SSOJet 8 个自演化 skill：<https://ssojet.com/blog/hermes-agent-self-evolving-skills>
- Efficient Coder Curator 深读：<https://www.xugj520.cn/en/archives/ai-agent-skill-library-hermes-curator.html>
- DEV 评测：<https://dev.to/tokenmixai/hermes-agent-review-956k-stars-self-improving-ai-agent-april-2026-11le>
- Avi Chawla Masterclass：<https://blog.dailydoseofds.com/p/hermes-agent-masterclass>
- 同类对比文献：Voyager (<https://arxiv.org/abs/2305.16291>) / Reflexion (<https://arxiv.org/abs/2303.11366>) / Promptbreeder (<https://arxiv.org/abs/2309.16797>) / AlphaEvolve (DeepMind 2025)
