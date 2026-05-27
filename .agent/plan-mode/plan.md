# Plan 模式与显式任务图 · 实施计划

> 设计规格：[`design.md`](./design.md)  
> 状态：**待实现**  
> 最后更新：2026-05-26

**范围**：不含 **WebUI / P4**（本仓库不使用 WebUI）。交付面：`plan` tool、slash（`/plan` 等）、session 持久化、runtime 注入。

每步力求 **可独立 review、可单独测**；完成一项勾一项。Phase **P3** 依赖 [context-cost](../context-cost/plan.md) **R2**（verify 执行器）；P2 可先 ship `acceptance:none`。

---

## 0. 里程碑总览

| 里程碑 | 交付物 | 用户可见价值 |
|--------|--------|----------------|
| **P1** | `plan_state` + `plan_create/show` + `/plan` | 结构化计划可存取 |
| **P2** | 步骤状态机 + `plan_start/complete_step` | 可跟踪进度 |
| **P3** | command 验收 + verify 联动（可选） | 可验证完成 |
| ~~**P4**~~ | ~~WebUI~~ | **不做** |
| **P5** | skill + 文档 + 硬化 | 可维护、可发布 |

---

## Phase P0 — 脚手架与配置

### P0-1 配置模型

- [ ] `PlanConfig` in `nanobot/config/schema.py`，挂 `AgentDefaults.plan`
- [ ] 字段：`enable`, `maxSteps`, `maxStepTitleChars`, `requireVerifyForDone`, `blockCompleteGoalIfPlanOpen`, `allowReplaceActivePlan`, `injectRuntimeSummary`
- [ ] `docs/configuration.md` 增加 Plan 小节（简表）
- **验收**：`load_config` 解析 camelCase；默认值与 design.md 一致

### P0-2 `plan_state` 模块

- [ ] 新建 `nanobot/session/plan_state.py`
- [ ] `PLAN_STATE_KEY = "plan_state"`
- [ ] `parse_plan_state`, `plan_active`, `validate_deps_acyclic`, `step_by_id`
- [ ] `plan_state_runtime_lines`（截断策略单测）
- **验收**：`tests/session/test_plan_state.py` 覆盖 parse、deps 环检测、runtime 行

---

## Phase P1 — 只读与创建

### P1-1 Plan tool 骨架

- [ ] `nanobot/agent/tools/plan.py`：`PlanTool` + `ContextAware` + `ToolLoader` 发现
- [ ] `enabled(ctx)` ← `config.plan.enable`
- [ ] actions：`create`, `show`（v1 先两个 action）
- **验收**：registry 含 `plan`；disable 时不注册

### P1-2 `plan_create` / `plan_show`

- [ ] `create`：写入 `plan_state`，`status=active`，`steps` 可为空或初始列表
- [ ] 拒绝第二份 active plan（除非 `allowReplaceActivePlan` + 显式 `replace`）
- [ ] `show`：返回 markdown 或纯文本树（供模型与用户）
- [ ] `sessions.save` 持久化
- **验收**：`tests/tools/test_plan_tools.py::test_create_and_show`

### P1-3 Slash `/plan`

- [ ] `nanobot/command/plan.py` 注册 `cmd_plan`
- [ ] `register_builtin_commands` 挂载
- **验收**：`tests/command/test_builtin_plan.py::test_plan_display`

---

## Phase P2 — 状态机与步骤变更

### P2-1 步骤 CRUD

- [ ] actions：`add_steps`, `update_step`, `cancel`
- [ ] `add_steps` 自动生成 `s1..sN` id
- [ ] `update_step` 仅允许改 `pending` 步骤的 title/deps/acceptance
- **验收**：max_steps 拒绝；deps 环拒绝

### P2-2 状态转换

- [ ] `start_step`：deps 满足 → `in_progress`（同时可将其他 in_progress 降级为 pending，**v1 允许单 in_progress**）
- [ ] `block_step`, `skip_step`
- [ ] `complete_step`：`acceptance.type=none` 时直接 done + evidence.note
- **验收**：非法转换返回明确 Error 字符串（模型可读）

### P2-3 Runtime 注入

- [ ] `ContextBuilder` 或现有 runtime 块调用 `plan_state_runtime_lines`（当 `injectRuntimeSummary`）
- [ ] 与 `goal_state_runtime_lines` 顺序：Goal 在前，Plan 在后
- **验收**：`tests/agent/test_context_plan_runtime.py` snapshot 关键行

### P2-4 Slash

- [ ] `/plan-cancel`
- [ ] `/plan-approve`（stub，供 manual acceptance 后续）
- **验收**：shortcut 命令不进入 LLM 历史（沿用 `_command` 标记）

---

## Phase P3 — command 验收（依赖 context-cost R2）

### P3-1 `complete_step` + verify

- [ ] `acceptance.type=command` 时调用 `run_verify_command`
- [ ] 失败：不标 done，返回 verify 摘要（stdout 尾、exit code）
- [ ] 成功：写 `evidence.verify_exit_code`
- [ ] `requireVerifyForDone` 配置行为
- **验收**：mock verify pass/fail 各一例

### P3-2 `/plan-verify`

- [ ] 对用户指定的 step 强制跑 acceptance command
- **验收**：integration test with mock verify

### P3-3 `complete_goal` 联动

- [ ] `complete_goal` 或 loop 层检查：open plan 且 `blockCompleteGoalIfPlanOpen` → 返回提示
- [ ] 配置 `warnOnly` 时仅 log warning
- **验收**：`tests/tools/test_plan_goal_integration.py`

---

## Phase P4 — WebUI（本仓库跳过）

不实现 `plan_state_ws_blob`、`_plan_state_sync`、`webui/` Plan 面板。进度查看：**`/plan`**、**`plan` tool `show`**。

---

## Phase P5 — 产品化

### P5-1 内置 skill

- [ ] `nanobot/skills/plan-workflow/SKILL.md`：何时 plan、何时 long_task、何时 spawn
- [ ] 与 `long-goal` skill 交叉引用，避免矛盾

### P5-2 文档

- [ ] `docs/plan-mode.md` 用户指南
- [ ] README 一句 + link
- [ ] `.agent/gotchas.md` 追加 plan 相关 2～3 条

### P5-3 硬化

- [ ] 日志字段统一
- [ ] 恶意超长 plan JSON 拒绝
- [ ] fuzz：deps 随机图环检测

---

## 测试矩阵

| 场景 | 类型 | Phase |
|------|------|-------|
| 创建 / 显示 plan | unit | P1 |
| deps 环 | unit | P0 |
| 单 in_progress | unit | P2 |
| verify 验收失败不 done | unit | P3 |
| goal + plan 同时 complete_goal | integration | P3 |
| 并发两 turn 改 plan | integration | P2 |

---

## 风险登记

| 风险 | 缓解 | 负责人 |
|------|------|--------|
| 与 long_task 文档冲突 | 更新 long-goal + plan-workflow skills | P5 |
| verify 未就绪 blocking P3 | P2 可先 ship `acceptance:none` | PM |
| WebUI | 本仓库不做了 | — |
| 模型不调用 plan tool | skill + 可选 slash「请先生成计划」 | P5 |

---

## 建议 PR 顺序

1. `P0 + P1` 单 PR：配置 + plan_state + create/show + `/plan`
2. `P2` 单 PR：状态机 + runtime
3. `P3` 单 PR（可选，依赖 context-cost R2）：验收 + goal 联动
4. `P5` 文档与 skill（无 WebUI PR）

---

## 完成定义（Release checklist）

- [ ] 用户可在 CLI/Telegram（等通道）让 agent `plan_create` 并 `/plan` 查看
- [ ] 至少 1 个 plan 演示：step 带 `command` acceptance + verify 通过
- [ ] `complete_goal` 在 plan 未完成时有明确提示
- [ ] 无 `loop.py` 超过 ~50 行的新增逻辑（runtime 注入除外）
