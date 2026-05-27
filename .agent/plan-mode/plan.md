# Plan 模式与显式任务图 · 实施计划

> 设计规格：[`design.md`](./design.md)  
> 状态：**待实现（Plan 后置；先完成 [Runtime Harness v1](../context-cost/plan.md)）**  
> 最后更新：2026-05-24

**范围**：不含 **WebUI / P4**。交付面：`plan` tool、slash、`plan_state.phase`、**Runner 工具门禁**（Claude `--plan` 式先规划后执行）、runtime 注入。

**实施顺序**：**Harness PR-1（policy）→ PR-2（verify）→ 再启动 Plan P0**。P3 依赖 Harness R2 verify 执行器；P1.5 phase 门禁与 Harness policy **叠加**，可并行设计但 **Plan 代码不在 Harness v1 内**。

每步力求 **可独立 review、可单独测**。Phase **P3** 依赖 [context-cost](../context-cost/plan.md) **R2**（verify 执行器）；P2 可先 ship `acceptance:none`。

---

## 0. 里程碑总览

| 里程碑 | 交付物 | 用户可见价值 |
|--------|--------|----------------|
| **P0** | `plan_state` + `phase` + `plan_tool_decision` | 两阶段数据模型与门禁逻辑可单测 |
| **P1** | `create/show` + `/plan` + **默认 `phase=planning`** | 终端可生成只读计划 |
| **P1.5** | Runner 接线 + `/plan-approve` `/plan-start` `/plan-revise` | **批准前无法 write/exec**（核心体验） |
| **P2** | 步骤状态机 + `start_step` / `complete_step`（仅 `executing`） | 批准后按步执行 |
| **P3** | command 验收 + verify 联动 | 可验证完成 |
| ~~**P4**~~ | ~~WebUI~~ | **不做** |
| **P5** | skill + 文档 + 硬化 | 可维护、可发布 |

> **推荐 PR 顺序**：`P0+P1` → **`P1.5`（门禁+slash 批准，不可跳过）** → `P2` → `P3` → `P5`。

---

## Phase P0 — 脚手架与配置

### P0-1 配置模型

- [ ] `PlanConfig` in `nanobot/config/schema.py`，挂 `AgentDefaults.plan`
- [ ] 字段：`enable`, `maxSteps`, `maxStepTitleChars`
- [ ] 两阶段：`requireExplicitApprove`（默认 `true`）, `autoStartAfterApprove`（默认 `false`）, `allowReviseWhileExecuting`（默认 `false`）
- [ ] 可选：`planningAllowedTools`, `planningDeniedTools`
- [ ] 原有：`requireVerifyForDone`, `blockCompleteGoalIfPlanOpen`, `allowReplaceActivePlan`, `injectRuntimeSummary`
- [ ] `docs/configuration.md` 增加 Plan 小节（含两阶段说明）
- **验收**：`load_config` 解析 camelCase；默认值与 design.md §6 一致

### P0-2 `plan_state` 模块

- [ ] 新建 `nanobot/session/plan_state.py`
- [ ] `PLAN_STATE_KEY = "plan_state"`
- [ ] `parse_plan_state`, `plan_active`, `plan_phase`, `validate_deps_acyclic`, `step_by_id`
- [ ] `plan_tool_decision(metadata, tool_name) -> allow | deny | None`（默认 denylist：write/edit/exec/spawn/verify 等）
- [ ] `can_mutate_step(plan, step_id, action)` — `executing` 时仅 `pending` 可 `update_step`
- [ ] `plan_state_runtime_lines`（含 `phase` + planning 提示行）
- **验收**：`tests/session/test_plan_state.py` 覆盖 parse、phase、deps 环、`plan_tool_decision`、runtime 行

---

## Phase P1 — 只读与创建

### P1-1 Plan tool 骨架

- [ ] `nanobot/agent/tools/plan.py`：`PlanTool` + `ContextAware` + `ToolLoader` 发现
- [ ] `enabled(ctx)` ← `config.plan.enable`
- [ ] actions：`create`, `show`（v1 先两个）
- **验收**：registry 含 `plan`；disable 时不注册

### P1-2 `create` / `show`

- [ ] `create`：写入 `plan_state`，`status=active`，**`phase=planning`**，`steps` 可为空或初始列表
- [ ] 拒绝第二份 active plan（除非 `allowReplaceActivePlan` + 显式 `replace`）
- [ ] `show`：返回树状摘要 + **`phase`** + 下一步 slash 提示（如 `Awaiting: /plan-approve`）
- [ ] `sessions.save` 持久化
- **验收**：`tests/tools/test_plan_tools.py::test_create_defaults_planning_phase`

### P1-3 Slash `/plan`

- [ ] `nanobot/command/plan.py` 注册 `cmd_plan`
- [ ] `register_builtin_commands` 挂载
- **验收**：`tests/command/test_builtin_plan.py::test_plan_display_shows_phase`

---

## Phase P1.5 — 两阶段门禁与批准（**Claude `--plan` 核心**）

### P1.5-1 Runner 工具门禁

- [ ] `AgentRunner`（或统一 pre-execute 路径）调用 `plan_tool_decision`
- [ ] deny 返回 soft error：`plan_phase: deny` + `hint`（`/plan-approve` / `/plan-start`）
- [ ] 无 active plan 时 `None`，不干预
- [ ] 子 agent 路径同样检查（继承 session metadata）
- **验收**：`tests/agent/test_plan_phase_gate.py` — `phase=planning` 时 mock `write_file`/`exec` 被拒；`executing` 时允许

### P1.5-2 `plan` actions：`approve` / `revise` / `start_execution`

- [ ] `approve`：`planning` → `approved`（或 → `executing` 若 `autoStartAfterApprove`）；写 `approved_at` / `approved_by`
- [ ] `start_execution`：`approved` → `executing`
- [ ] `revise`：`approved` → `planning`；`executing` 仅当 `allowReviseWhileExecuting`
- [ ] 非法 phase 转换返回明确错误
- **验收**：`tests/tools/test_plan_tools.py` 覆盖 phase 转换矩阵

### P1.5-3 Slash 批准流

- [ ] `/plan-approve` → 同 `approve` action
- [ ] `/plan-start` → 同 `start_execution`
- [ ] `/plan-revise` → 同 `revise`
- [ ] 命令直接写 session，不经过 LLM
- **验收**：`tests/command/test_builtin_plan.py` — approve 后 metadata `phase` 正确；planning 下 runner deny 写工具

### P1.5-4 Runtime 注入（phase 行）

- [ ] `ContextBuilder` 调用 `plan_state_runtime_lines`（当 `injectRuntimeSummary`）
- [ ] `planning` 时注入「Planning only — no write/exec until /plan-approve」
- [ ] 与 `goal_state_runtime_lines` 顺序：Goal 在前，Plan 在后
- **验收**：`tests/agent/test_context_plan_runtime.py` snapshot

---

## Phase P2 — 状态机与步骤变更

### P2-1 步骤 CRUD

- [ ] actions：`add_steps`, `update_step`, `cancel`
- [ ] `add_steps` / `update_step`：仅 `planning`；`executing` 时仅 `pending` 步骤可 `update_step`
- [ ] `add_steps` 自动生成 `s1..sN` id
- **验收**：max_steps 拒绝；deps 环拒绝；`executing` 改 `in_progress` step 被拒绝

### P2-2 状态转换（仅 `executing`）

- [ ] `start_step`：deps 满足 → `in_progress`（**v1 单 in_progress**）
- [ ] `block_step`, `skip_step`
- [ ] `complete_step`：`acceptance.type=none` 时直接 done + evidence.note
- [ ] `phase!=executing` 时 `start_step`/`complete_step` 拒绝
- **验收**：非法转换 + 错误 phase 返回模型可读 Error

### P2-3 Slash

- [ ] `/plan-cancel`
- [ ] `/plan-signoff <step_id>`（stub，manual acceptance v1.1）
- **验收**：shortcut 不进入 LLM 历史（沿用 `_command` 标记）

---

## Phase P3 — command 验收（依赖 context-cost R2）

### P3-1 `complete_step` + verify

- [ ] `acceptance.type=command` 时调用 `run_verify_command`（仅 `executing`）
- [ ] 失败：不标 done，返回 verify 摘要
- [ ] 成功：写 `evidence.verify_exit_code`
- [ ] `requireVerifyForDone` 配置行为
- **验收**：mock verify pass/fail 各一例

### P3-2 `/plan-verify`

- [ ] 对指定 step 强制跑 acceptance command（仅 `executing`）
- **验收**：integration test with mock verify

### P3-3 `complete_goal` 联动

- [ ] open plan 且 `blockCompleteGoalIfPlanOpen` → 提示（含 `phase` 未 `completed`）
- **验收**：`tests/tools/test_plan_goal_integration.py`

---

## Phase P4 — WebUI（本仓库跳过）

不实现 WebUI Plan 面板。进度与批准：**`/plan`**、**`/plan-approve`**、**`/plan-start`**。

---

## Phase P5 — 产品化

### P5-1 内置 skill

- [ ] `nanobot/skills/plan-workflow/SKILL.md`：**先 plan 后执行**、slash 流程、何时不必 plan
- [ ] 与 `long-goal` skill 交叉引用

### P5-2 文档

- [ ] `docs/plan-mode.md`：终端 walkthrough（planning → approve → start → executing）
- [ ] README 一句 + link
- [ ] `.agent/gotchas.md`：plan phase deny、与 Harness policy 叠加

### P5-3 硬化

- [ ] 日志：`plan_tool_deny`, `phase` 转换
- [ ] 恶意超长 plan JSON 拒绝
- [ ] fuzz：deps 环检测

---

## 测试矩阵

| 场景 | 类型 | Phase |
|------|------|-------|
| create 默认 `phase=planning` | unit | P1 |
| planning 下 deny write_file/exec | unit | P1.5 |
| approve → start → executing | unit | P1.5 |
| `autoStartAfterApprove` 单步进 executing | unit | P1.5 |
| deps 环 | unit | P0 |
| executing 仅 pending 可 update_step | unit | P2 |
| 单 in_progress | unit | P2 |
| verify 验收失败不 done | unit | P3 |
| goal + open plan complete_goal block | integration | P3 |
| 并发两 turn 改 plan | integration | P2 |

---

## 风险登记

| 风险 | 缓解 |
|------|------|
| 与 long_task 文档冲突 | plan-workflow skill 写明两阶段 |
| 只做 tool 不做 Runner 门禁 | **P1.5 为必做**，与 P1 同里程碑验收 |
| verify 未就绪 blocking P3 | P2 用 `acceptance:none` |
| 模型不调用 plan | skill + runtime 提示 + deny 倒逼 |
| Plan phase vs Harness policy 重复 deny | 合并 hint；单测各测一层 |

---

## 建议 PR 顺序

1. **P0 + P1**：配置 + plan_state + create/show + `/plan`
2. **P1.5**：Runner 门禁 + approve/start/revise slash + runtime phase 行（**不可拆到 P2 之后**）
3. **P2**：步骤状态机（仅 executing）
4. **P3**（依赖 context-cost R2）：command 验收 + goal 联动
5. **P5**：文档与 skill

---

## 完成定义（Release checklist）

- [ ] 终端：用户要求「先计划再执行」→ agent 创建 plan 后 **无法** write/exec，直至 `/plan-approve`（及 `/plan-start` 若配置两步）
- [ ] `/plan` 显示 `phase` 与下一步 slash 提示
- [ ] 至少 1 个演示：approve → start → step `command` acceptance + verify 通过
- [ ] `complete_goal` 在 plan 未完成时有明确提示
- [ ] `loop.py` 新增逻辑保持薄（runtime + runner 一行调用 `plan_tool_decision`）
