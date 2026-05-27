# E4 — GEPA 离线 Skill 优化 · 实现清单

> 本文档是 **E4 分步实施指南**，配合 [hermes-design.md](./hermes-design.md) §4.5 使用。  
> 每步尽量 **小、可独立 review、可单独测**，完成一项勾一项。

---

## 0. 目标与边界

### 要做什么

| 项 | 说明 |
|----|------|
| **操作** | 仅 **update** 已有 active skill（`skills/<name>/SKILL.md`） |
| **引擎** | 完整 **DSPy + GEPA**（参考 [hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution) Phase 1） |
| **输入** | `TraceStore` success traces + active skills |
| **输出** | `skills/.proposals/<uuid>/` update proposal，`source: "gepa"` |
| **审核** | **永远人工** → `/evolve-show` → `/evolve-apply`（update 路径） |
| **运行方式** | **异步后台**（分钟级，不阻塞对话） |

### 不做什么

- 不在 turn 中途改 skill
- 不 auto_apply GEPA 结果
- 不 create 新 skill（create 仍归 PostTask）
- 不让 Dream 写 skills（E3 已完成）
- E4 不做 WebUI 面板（E6）

### 三种触发（已确认）

| 入口 | 行为 |
|------|------|
| **Cron** | `gepa.interval_hours` 定时，`evolve-gepa` system job |
| **CLI** | `nanobot evolve run [--skill NAME]` |
| **Slash** | `/evolve-run [skill]` 立即返回；配套 `/evolve-status` |

### 与 PostTask 分工

```
PostTask (即时)     → create proposal / auto_apply
GEPA (离线批量)    → update proposal only
/evolve-apply      → create 或 update（按 proposal 类型）
```

---

## 1. 已有基础（无需重做）

实现 E4 前，以下能力 **已存在**：

| 能力 | 位置 |
|------|------|
| Trace 写入 | `trace_recorder.py`, `loop._record_turn_trace` |
| `list_for_gepa()` / `mark_used_for_evolution()` | `trace_store.py` |
| `EvolutionGepaConfig` / `gepa_enabled()` | `config/schema.py` |
| Proposal 队列 CRUD | `proposals.py` |
| `ProposalSource = "gepa"` 类型预留 | `proposals.py` |
| Git `commit_update(..., source="gepa")` | `git_store.py` |
| `/evolve-list/show/apply/reject/log/restore` | `command/evolve.py` |
| PostTask update → deferred to GEPA | `post_task.py` |
| Dream 不再写 skills | E3 已完成 |

---

## 2. 架构总览

```mermaid
flowchart TB
    subgraph 触发
        CRON[cron: evolve-gepa]
        CLI[nanobot evolve run]
        SLASH[/evolve-run]
    end

    subgraph 异步层
        LOOP[AgentLoop._schedule_gepa]
        RUNNER[GepaRunner.run async]
        EXEC[asyncio.to_thread<br/>DSPy/GEPA 同步内核]
    end

    subgraph 状态
        STATUS[".nanobot/gepa_run.json"]
        LOCK[".nanobot/gepa_run.lock"]
    end

    subgraph 数据
        TRACE[TraceStore]
        SKILL[active skills/]
        PROP[".proposals/ source=gepa"]
    end

    subgraph 审核
        APPLY["/evolve-apply<br/>apply_update"]
        GIT[EvolutionGitStore]
        IDX[SkillIndex.warm]
    end

    CRON --> LOOP
    CLI --> RUNNER
    SLASH --> LOOP
    LOOP --> RUNNER
    RUNNER --> STATUS
    RUNNER --> LOCK
    RUNNER --> EXEC
    TRACE --> RUNNER
    SKILL --> RUNNER
    EXEC --> PROP
    PROP --> APPLY --> GIT --> IDX
```

---

## 3. 分步清单

> 格式：**ID** · 标题 · 改动 · 验收

---

### Phase A — 依赖与可选安装

#### E4-A1 · `pyproject.toml` 增加 `[evolution]` extra

- **改动**：`pyproject.toml`
  ```toml
  [project.optional-dependencies]
  evolution = [
      "dspy>=2.6.0",   # 含 GEPA；版本按 Hermes 对齐后 pin
  ]
  ```
- **验收**：`pip install -e ".[evolution]"` 成功；未安装时 `import dspy` 失败可被捕获
- **备注**：确认 GEPA 在 dspy 内置还是独立包 `gepa-ai`；与 Hermes upstream 对齐后再锁版本

#### E4-A2 · 依赖探测模块

- **改动**：新建 `nanobot/agent/evolution/deps.py`
  - `evolution_extra_available() -> bool`
  - `require_evolution_extra() -> str | None`（返回缺失提示文案）
- **验收**：有/无 extra 两种环境单测通过
- **依赖**：E4-A1

---

### Phase B — 运行状态与单飞锁

#### E4-B1 · GEPA 运行状态模型

- **改动**：新建 `nanobot/agent/evolution/gepa_status.py`
  - `GepaRunPhase`：`idle | starting | selecting | optimizing | writing | completed | failed | skipped`
  - `GepaRunStatus` 字段：
    - `run_id`, `trigger`（`cron|cli|slash`）
    - `skill_name`（可选，单 skill 跑）
    - `phase`, `message`
    - `started_at`, `finished_at`
    - `proposals_created: list[str]`
    - `traces_consumed: list[str]`
    - `budget_usd_spent`, `error`
  - `GepaRunStore`：读写 `{workspace}/.nanobot/gepa_run.json`
- **验收**：round-trip JSON 读写；非法 JSON 降级为空状态
- **依赖**：无

#### E4-B2 · 跨进程单飞锁

- **改动**：`gepa_status.py` 或 `gepa_runner.py`
  - 使用已有 `filelock` + `{workspace}/.nanobot/gepa_run.lock`
  - `try_acquire_run_lock() -> bool`；拿不到锁 → `skipped: already running`
- **验收**：gateway 与 CLI 同时触发，仅一个进入 running
- **依赖**：E4-B1

#### E4-B3 · `EvolutionGepaConfig` 调度辅助

- **改动**：`config/schema.py` — `EvolutionGepaConfig` 增加：
  - `build_schedule(timezone) -> CronSchedule | None`（`interval_hours` 为 None 则返回 None）
  - `describe_schedule() -> str`
- **验收**：与 `DreamConfig.build_schedule` 行为一致；单测
- **依赖**：无

---

### Phase C — Proposal 模型扩展（GEPA update）

#### E4-C1 · 扩展 `ProposalMeta` GEPA 字段

- **改动**：`proposals.py` — `ProposalMeta` 增加可选字段：
  - `base_skill: str` — 被优化的 skill 名
  - `base_sha: str` — apply 前 active skill 的 git HEAD（8 位）
  - `evaluation_score: float | None` — GEPA 最优候选分数
  - `proposal_kind: "create" | "update"`（或从 `source`+逻辑推断）
- **验收**：`to_dict` / `from_dict` 向后兼容旧 meta；旧 proposal 仍可读
- **依赖**：无

#### E4-C2 · `write_gepa_proposal()`

- **改动**：`proposals.py`
  ```python
  write_gepa_proposal(
      skill_name, skill_md, *,
      base_sha, evaluation_score,
      trace_ids, rationale,
  ) -> str  # proposal_id
  ```
  - `source="gepa"`, `proposal_kind="update"`
  - **不**写 active skill；**拒绝**同名 pending update proposal 重复（dedup）
- **验收**：写入 `.proposals/<uuid>/`；meta 字段完整；单测
- **依赖**：E4-C1

#### E4-C3 · `apply_update()` — update 型落地

- **改动**：`proposals.py`
  - 新方法 `apply_update(proposal_id, git_store=...)`
  - 前置：meta `source==gepa` 且 active skill **必须存在**
  - 校验：`skill_name` 与 `base_skill` 一致；`name` frontmatter 不变
  - **`description` 语义不漂移**：frontmatter description 与 base 相同或编辑距离阈值内（具体规则见 E4-D5）
  - 写 `skills/<name>/SKILL.md` → `git.commit_update()` → 更新 meta `applied`
- **验收**：update proposal apply 后 active 文件更新；create proposal 仍走原 `apply()`
- **依赖**：E4-C1，已有 `git_store.commit_update`

#### E4-C4 · `/evolve-apply` 分流 create / update

- **改动**：`command/evolve.py` — `cmd_evolve_apply`
  - GEPA proposal → `apply_update()`
  - post_task proposal → `apply_and_commit()`（现有）
  - 成功后均 `warm_skill_index()`
- **验收**：两种 proposal 各测一条端到端路径
- **依赖**：E4-C2, E4-C3

#### E4-C5 · `/evolve-show` 展示 GEPA 元数据

- **改动**：`command/evolve.py`
  - 显示 `base_skill`, `base_sha`, `evaluation_score`, `proposal_kind`
  - 可选：与 base skill 的 diff 摘要
- **验收**：GEPA proposal show 输出含上述字段
- **依赖**：E4-C1

---

### Phase D — GEPA 核心（DSPy + SkillModule）

> 参考 Hermes Phase 1；**必须**避免 Issue #38「ghost improvements」（GEPA 改 wrapper 而非 SKILL.md 正文）。

#### E4-D1 · Eval 数据集构建

- **改动**：新建 `nanobot/agent/evolution/gepa_dataset.py`
  - 从 `TraceStore.list_for_gepa()` 构造 eval examples
  - 过滤：与目标 skill 相关（`skills_injected` 含 skill 名，或 tool_calls 模式匹配）
  - 输出：`list[GepaEvalExample]`（query, tool_calls, outcome, …）
  - 最小样本数门控（如 ≥3，可配置）
- **验收**：给定 fixture traces，数据集条数与内容符合预期
- **依赖**：已有 `trace_store.list_for_gepa`

#### E4-D2 · SkillModule（可优化 SKILL.md 正文）

- **改动**：新建 `nanobot/agent/evolution/gepa_skill_module.py`
  - 将 **SKILL.md 正文** 映射为 DSPy 可 mutate 的 instruction（非 wrapper docstring）
  - 读取/写回时保留 YAML frontmatter；**`name` / `description` 冻结**
  - 参考 Hermes #38 fix：从 predictor docstring / 专用 field 提取 evolved body
- **验收**：GEPA 跑完后 body 变化、frontmatter 不变；单测 round-trip
- **依赖**：E4-A2

#### E4-D3 · Evaluator（batch 评估）

- **改动**：新建 `nanobot/agent/evolution/gepa_evaluator.py`
  - 给定 skill 候选 + eval example，调用 LLM/agent 回放或轻量打分
  - 返回 score + trace（供 GEPA reflective 分析）
  - 并发上限、超时、`max_budget_usd` 累计
- **验收**：mock provider 下 evaluator 可重复；超预算 abort
- **依赖**：E4-D1, config `gepa.max_budget_usd`

#### E4-D4 · GEPA Optimizer 封装

- **改动**：新建 `nanobot/agent/evolution/gepa_optimizer.py`
  - 封装 `dspy.GEPA(...)` 配置（model、reflection、population 等）
  - `optimize(skill_module, trainset, valset) -> GepaOptimizeResult`
  - 同步 API；由 runner 在 `asyncio.to_thread` 中调用
- **验收**：小 fixture 上跑通 1 轮（可 mock LLM）；产出候选 skill_md + score
- **依赖**：E4-D2, E4-D3, E4-A2

#### E4-D5 · Description 不漂移校验

- **改动**：`proposals.validate_skill_md` 或新函数 `validate_gepa_update()`
  - update proposal：`name` 必须与 `base_skill` 一致
  - `description` 字段不允许改（或允许 typo-fix 阈值，默认 **完全相等**）
  - body 词数 ≤ 2000
- **验收**：改 description 的 proposal 被拒绝；单测
- **依赖**：E4-C2

#### E4-D6 · `GepaRunner` 主编排

- **改动**：新建 `nanobot/agent/evolution/gepa_runner.py`
  - `async def run(*, skill_name=None, trigger="manual") -> GepaRunResult`
  - 流程：
    1. 门控：`gepa_enabled()`、extra 可用、拿锁
    2. 枚举 active skills（或单个 `skill_name`）
    3. 每个 skill：build dataset → optimize → validate → `write_gepa_proposal`
    4. `mark_used_for_evolution(trace_ids)`
    5. 更新 `gepa_run.json` phase / 结果
  - 同步重活：`await asyncio.to_thread(...)`
- **验收**：integration test（mock optimizer）产出 proposal；状态文件 phase 正确
- **依赖**：E4-B1, E4-B2, E4-C2, E4-D1–D5

#### E4-D7 · 记录 `base_sha`

- **改动**：`gepa_runner` 在 optimize 前读 `EvolutionGitStore.head_sha()` 或 skill 专属 snapshot
- **验收**：GEPA proposal meta 含正确 `base_sha`
- **依赖**：E4-D6, `git_store`

---

### Phase E — 触发入口

#### E4-E1 · AgentLoop 挂载

- **改动**：`agent/loop.py`
  - `_gepa_runner: GepaRunner | None`
  - `_get_gepa_runner()`, `_schedule_gepa_run(skill_name?, trigger)`
  - `_run_gepa()` → 内部 `await runner.run(...)`
  - 使用现有 `_schedule_background()`（与 PostTask 同模式）
- **验收**：slash/内部调用不阻塞 `process_direct` 返回
- **依赖**：E4-D6

#### E4-E2 · Cron system job

- **改动**：`cli/commands.py`（gateway 启动段）
  - `on_cron_job` 增加 `job.name == "evolve-gepa"` 分支 → `_schedule_gepa` 或 `await runner.run(trigger="cron")`
  - `gepa_enabled()` 且 `interval_hours` 非空时：
    ```python
    cron.register_system_job(CronJob(
        id="evolve-gepa", name="evolve-gepa",
        schedule=gepa_cfg.build_schedule(timezone),
        payload=CronPayload(kind="system_event"),
    ))
    ```
  - 启动日志：`✓ GEPA: every 168h`
- **验收**：gateway 启动注册 job；cron 触发后 status 变为 running
- **依赖**：E4-B3, E4-E1

#### E4-E3 · CLI `nanobot evolve run`

- **改动**：`cli/commands.py`
  - `evolve_app = typer.Typer()` → `app.add_typer(evolve_app, name="evolve")`
  - `evolve run [--skill NAME] [--workspace] [--config]`
  - `evolve status` — 打印 `gepa_run.json`
  - 无 gateway 时 CLI 直接 `asyncio.run(GepaRunner(...).run(trigger="cli"))`
- **验收**：CLI 可独立触发；与 gateway 并发时单飞锁生效
- **依赖**：E4-D6, E4-B2

#### E4-E4 · Slash `/evolve-run`

- **改动**：`command/evolve.py`
  - `cmd_evolve_run`：解析可选 skill 名 → `ctx.loop._schedule_gepa_run(..., trigger="slash")`
  - 立即回复：`GEPA run started. Check /evolve-status.`
  - 若已在跑：提示 already running
- **改动**：`command/builtin.py` — 注册 + `BUILTIN_COMMAND_SPECS` + Telegram 别名 `evolve_run`
- **验收**：聊天触发后 status 更新；不阻塞 turn
- **依赖**：E4-E1

#### E4-E5 · Slash `/evolve-status`

- **改动**：`command/evolve.py`
  - 读 `GepaRunStore`，格式化 phase、skill、耗时、proposal_ids、error
- **验收**：idle/running/completed/failed 四种状态展示正确
- **依赖**：E4-B1

---

### Phase F — 可观测性与通知

#### E4-F1 · 结构化日志

- **改动**：`gepa_runner.py` 各 phase 打 loguru info/debug
  - 例：`GEPA [start] skill=foo traces=12`、`GEPA [done] proposals=1 budget=$1.23`
- **验收**：本地跑一轮日志可追踪
- **依赖**：E4-D6

#### E4-F2 · 完成后用户通知（可选）

- **改动**：`gepa_runner` 或 `loop._run_gepa` 完成回调
  - 若 `proposals_created` 非空 → `bus.publish_outbound` 摘要
  - Cron 触发时可配置是否通知（默认 **仅 log**，slash 触发 **通知**）
- **验收**：slash 触发完成后用户收到「1 GEPA proposal ready: …」
- **依赖**：E4-E1, E4-D6

#### E4-F3 · 配置项补充（可选）

- **改动**：`EvolutionGepaConfig` 可增加：
  - `min_traces: int = 3`
  - `notify_on_complete: bool = False`
  - `max_skills_per_run: int = 1`（防止一次跑太久）
- **验收**：schema 测试更新
- **依赖**：无

---

### Phase G — 测试

#### E4-G1 · 单元测试

| 文件 | 覆盖 |
|------|------|
| `tests/agent/evolution/test_gepa_status.py` | store、lock |
| `tests/agent/evolution/test_gepa_dataset.py` | eval 构造 |
| `tests/agent/evolution/test_gepa_proposals.py` | write_gepa / apply_update / description 校验 |
| `tests/agent/evolution/test_gepa_runner.py` | 门控、mock optimizer、状态流转 |

#### E4-G2 · 命令测试

| 文件 | 覆盖 |
|------|------|
| `tests/command/test_builtin_evolve_gepa.py` | `/evolve-run`, `/evolve-status` |

#### E4-G3 · 集成测试（可选，需 evolution extra）

- 小 skill + 合成 traces 跑 mock GEPA 一轮 → proposal → `apply_update` → git log 含 `evolve: update`

---

### Phase H — 文档与发布

#### E4-H1 · 更新 `hermes-design.md`

- E4 节链到本文档；实施顺序表标记进度

#### E4-H2 · 用户配置示例

- `~/.nanobot/config.json` 片段：
  ```json
  "evolution": {
    "enable": true,
    "gepa": {
      "enable": true,
      "intervalHours": 168,
      "maxBudgetUsd": 10
    }
  }
  ```

#### E4-H3 · README / CONTRIBUTING 提及 `pip install nanobot-ai[evolution]`

- **依赖**：E4-A1

---

## 4. 推荐实施顺序（PR 切分建议）

| PR | 包含步骤 | 说明 |
|----|----------|------|
| **PR-1** | A1–A2, B1–B3 | 依赖 + 状态 + 锁 + config schedule |
| **PR-2** | C1–C5 | Proposal update 模型 + apply 分流 |
| **PR-3** | D1–D7 | GEPA 核心（最大 PR，可再拆 D2–D4 / D6–D7） |
| **PR-4** | E1–E5 | 三种触发 + status 命令 |
| **PR-5** | F1–F3, G1–G3, H1–H3 | 可观测、测试、文档 |

---

## 5. 关键风险与对策

| 风险 | 对策 |
|------|------|
| GEPA 改 wrapper 不改 SKILL.md（Hermes #38） | E4-D2 SkillModule 专门处理；单测 assert body 变、frontmatter 不变 |
| 运行 3–8 分钟阻塞 gateway | E4-D6 `to_thread` + E4-E1 background；Cron/CLI 同锁 |
| description 漂移导致检索错乱 | E4-D5 硬校验；GEPA prompt 冻结 frontmatter |
| 预算失控 | E4-D3 evaluator 累计 cost；达 `max_budget_usd` abort |
| 无 evolution extra 时 import 崩溃 | E4-A2 懒 import；gateway 启动不失败 |
| create/update apply 混用 | E4-C3/C4 分流；integration test 覆盖 |

---

## 6. 完成定义（Definition of Done）

- [x] `pip install nanobot-ai[evolution]` 后，完整 GEPA 路径可跑通
- [x] Cron / CLI / `/evolve-run` 均可触发，且 **单飞**
- [x] 产出 `source=gepa` proposal，含 `base_skill` / `base_sha` / `evaluation_score`
- [x] `/evolve-apply` 对 GEPA proposal 走 **update**，git 有 `evolve: update skill … (gepa)`
- [x] **从不** auto_apply GEPA 结果
- [x] 测试覆盖 status、proposal、命令、runner 门控（optimizer 可 mock）
- [x] `.agent/gepa.md` 全部步骤勾选完成

> **待定（非 GEPA 核心）**：金标准任务集 + 进化效果客观评估（见对话记录，后续单独做）。

---

## 7. 进度追踪

> 实现时在对应项前打 `[x]`。

### Phase A
- [x] E4-A1 pyproject evolution extra
- [x] E4-A2 deps.py

### Phase B
- [x] E4-B1 gepa_status.py
- [x] E4-B2 单飞锁
- [x] E4-B3 config schedule helpers

### Phase C
- [x] E4-C1 ProposalMeta 扩展
- [x] E4-C2 write_gepa_proposal
- [x] E4-C3 apply_update
- [x] E4-C4 /evolve-apply 分流
- [x] E4-C5 /evolve-show GEPA 字段

### Phase D
- [x] E4-D1 gepa_dataset.py
- [x] E4-D2 gepa_skill_module.py
- [x] E4-D3 gepa_evaluator.py
- [x] E4-D4 gepa_optimizer.py
- [x] E4-D5 description 校验
- [x] E4-D6 gepa_runner.py
- [x] E4-D7 base_sha 记录

### Phase E
- [x] E4-E1 loop 挂载
- [x] E4-E2 cron job
- [x] E4-E3 CLI evolve run/status
- [x] E4-E4 /evolve-run
- [x] E4-E5 /evolve-status

### Phase F
- [x] E4-F1 结构化日志
- [x] E4-F2 完成通知
- [x] E4-F3 可选配置项

### Phase G
- [x] E4-G1 单元测试
- [x] E4-G2 命令测试
- [x] E4-G3 集成测试

### Phase H
- [x] E4-H1 更新 hermes-design
- [x] E4-H2 配置示例
- [x] E4-H3 README evolution extra

---

## 8. 参考

- [hermes-design.md](./hermes-design.md) §4.5, §7
- [hermes-agent-self-evolution PLAN.md](https://github.com/NousResearch/hermes-agent-self-evolution/blob/main/PLAN.md)
- [Hermes Issue #38 — SkillModule / ghost improvements](https://github.com/NousResearch/hermes-agent-self-evolution/issues/38)
- 现有代码：`trace_store.py`, `proposals.py`, `git_store.py`, `command/evolve.py`
