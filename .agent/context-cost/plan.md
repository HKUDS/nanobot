# Runtime Harness + 上下文/成本 · 实施计划

> 设计规格：[`design.md`](./design.md)  
> 状态：**范围已确认，待实现**  
> 最后更新：2026-05-24

**范围**：仅 **在线 Runtime Harness**（策略、verify、checkpoint 用户面、context preset）。**不含** 离线 `nanobot harness run` / YAML cases / CI eval suite。**不含 Plan 模式**（Plan 见 [plan-mode/plan.md](../plan-mode/plan.md)，R5 仅预留 verify 给 Plan P3）。

**推荐顺序**：**PR-1（R0+R1）→ PR-2（R2）→ PR-3（R3∥R4 可选拆分）**。Plan **P1.5** phase 门禁与 Harness R1 可并行，但 **不在本 Harness v1 必做范围**。

---

## v1 十项交付（已确认）

与 [design.md §1.5](./design.md#15-v1-交付范围已确认2026-05-24) 对齐；实现时按此验收。

| # | 交付项 | Phase | PR |
|---|--------|-------|-----|
| 1 | PreTool：`policy.yaml` + `HarnessPolicyHook` + deny soft error | R0+R1 | PR-1 |
| 2 | 通道覆盖 + `defaults.on_unknown_tool` | R1 | PR-1 |
| 3 | `exec`：`deny_patterns` + 可选 `allow_patterns`（收编 ExecTool） | R1 | PR-1 |
| 4 | `write_file` / `edit_*`：`paths_allow` / `paths_deny` | R1 | PR-1 |
| 5 | deny 结构化 log + escalation（对齐 workspace_violation） | R1 | PR-1 |
| 6 | 子 agent（spawn）继承同一 policy | R1 | PR-1 |
| 7 | MCP 工具按 tool 名纳入 `tools.<name>` policy | R1.5 | PR-1 或 PR-1 小 follow-up |
| 8 | `verify` tool + 白名单执行器 | R2 | PR-2 |
| 9 | `contextProfile=lean` preset | R3 | PR-3 |
| 10 | `/rewind`（+ 可选 `/checkpoint` 摘要） | R4 | PR-3 |

**v1 不做**：`require_approval` UI、Plan phase 门禁、profiles 语法糖、turn USD 预算、PII 扫描、WebUI、离线 eval。

---

## Phase R0 — 配置与加载

- [ ] `HarnessConfig`、`HarnessVerifyConfig` in `nanobot/config/schema.py`，挂 `AgentDefaults.harness`
- [ ] `nanobot/agent/harness/loader.py`：读 `workspace/.nanobot/harness/policy.yaml`、`presets/<profile>.yaml`
- [ ] 缺失文件 → 空 policy（**等价 allow-all**，不改变现有行为）；解析错误 → log + 空 policy
- [ ] `templates/harness/policy.yaml.example`（含 exec/write/channel 完整示例）
- **验收**：`tests/agent/harness/test_loader.py`

---

## Phase R1 — 策略 Hook（PreTool）· PR-1 核心

### R1-A 骨架

- [ ] `nanobot/agent/harness/policy.py`：`evaluate(tool, args, channel) -> PolicyDecision`
- [ ] `nanobot/agent/harness/policy_hook.py`：`HarnessPolicyHook`
- [ ] `AgentLoop`：`harness.enable` 时注入 `CompositeHook`（**系统 hook 在最前**）
- [ ] `AgentRunner._execute_tools`：deny 跳过 execute，返回 `harness_policy: deny` + `rule_id` + hint
- [ ] 通道：`RequestContext` / inbound `channel` 传入 `evaluate`

### R1-B 策略语义（十项 #2–#6）

- [ ] 匹配顺序：`channels.<name>.tools.<tool>` > `tools.<tool>` > `defaults.on_unknown_tool`
- [ ] **`exec`**：`constraints.deny_patterns`；可选 `allow_patterns`（若配置则命令须匹配 allow）
- [ ] **`write_file` / `edit_file` / `apply_patch`**（写路径类）：`paths_allow` / `paths_deny` glob
- [ ] **结构化 log**：`harness policy deny tool=… rule=… channel=…`
- [ ] **escalation**：重复 deny 累计 hint（复用 runner `_classify_violation` / `workspace_violation_counts` 模式）
- [ ] **子 agent**：spawn 子 runner 同 workspace policy（#6）

### R1-C MCP（十项 #7，可 PR-1 末尾）

- [ ] MCP 注册后的 tool 名（如 `mcp_*`）走同一 `tools.<name>` 规则
- [ ] 单测：policy deny 某 MCP tool 名

### R1 与 ExecTool 收编（十项 #3）

- [ ] 文档：`policy.yaml` **优先**于 `tools.exec.denyPatterns`；实现时 policy evaluate 在 PreTool，ExecTool 内 guard 保留作第二层
- [ ] 单测：policy deny 时 **不**进入 ExecTool

- **验收**：`tests/agent/harness/test_policy.py`、`test_policy_hook.py`；矩阵见下表 R1 行

---

## Phase R2 — `verify` tool + 执行器 · PR-2（十项 #8）

- [ ] `nanobot/agent/harness/verify.py`：`run_verify_command(command, cwd, timeout) -> VerifyResult`
- [ ] `nanobot/agent/tools/verify.py`：注册 tool；白名单来自 `harness.verify.allowCommands`
- [ ] `loop._register_default_tools`（`harness.verify.enabled`）
- [ ] `docs/configuration.md` → **Runtime Harness** 小节（简）
- **验收**：`tests/agent/harness/test_verify.py`；mock subprocess 各一例

---

## Phase R3 — Context preset · PR-3（十项 #9）

- [ ] `presets/lean.yaml`（+ 可选 `quality.yaml` 占位）+ turn 开始浅合并运行时 config
- [ ] `agents.defaults.harness.contextProfile` 接线
- [ ] 文档：`/status` 对比 token（**无**离线 suite）
- **验收**：单测 preset 展开 `maxMessages` 等字段

---

## Phase R4 — Checkpoint 用户面 · PR-3（十项 #10）

- [ ] `nanobot/command/harness.py` 或 `builtin`：`/rewind`
- [ ] 可选：`/checkpoint` 只读摘要
- [ ] 与 `_restore_runtime_checkpoint` 对齐；文档与 `/stop` 关系
- [ ] ~~WebUI 撤销按钮~~ — **不做**
- **验收**：command 测 + 复用 loop checkpoint 测

---

## Phase R5 — Plan 联动（**非 Harness v1 必做**；依赖 R2）

> Plan 子项目 [plan-mode/plan.md](../plan-mode/plan.md) P3；Harness 仅保证 verify 执行器可用。

- [ ] `plan_complete_step` + `acceptance.type=command` → `run_verify_command`
- [ ] `/plan-verify <step_id>`
- **验收**：Plan P3 mock verify

---

## Phase R6 — 可观测增强（可选，v1 可仅做 R1-B log）

- [ ] Trace 附加 `harness_policy_denies`、`verify_runs` 摘要
- [ ] 字段稳定、单测 snapshot

---

## 不做清单（明确关闭）

- [ ] ~~`nanobot harness run`~~
- [ ] ~~`workspace/.nanobot/harness/cases/`~~
- [ ] ~~`HarnessRunner` / `AssertionEngine`~~
- [ ] ~~GitHub Actions harness workflow~~
- [ ] ~~`evolution.requireHarnessPass`~~
- [ ] ~~`export-trace` → case yaml~~
- [ ] ~~Harness WebUI~~
- [ ] ~~Plan phase 门禁~~（Plan 项目，非本线）

---

## 测试矩阵

| 场景 | 类型 | Phase | 十项 # |
|------|------|-------|--------|
| policy deny exec | unit | R1 | 1,3 |
| channel override telegram deny exec | unit | R1 | 2 |
| write_file paths_deny `.env` | unit | R1 | 4 |
| deny 重复 escalation hint | unit | R1 | 5 |
| spawn 子 agent 同 policy deny exec | unit | R1 | 6 |
| MCP tool 名 deny | unit | R1.5 | 7 |
| verify 非白名单命令 | unit | R2 | 8 |
| verify pytest mock pass/fail | unit | R2 | 8 |
| preset lean 展开 maxMessages | unit | R3 | 9 |
| /rewind 恢复 checkpoint | integration | R4 | 10 |

---

## PR 切分（已确认）

| PR | 内容 | 十项 |
|----|------|------|
| **PR-1** | R0 + R1（#1–#6，尽量含 #7） | 策略 MVP，可演示 Telegram deny exec |
| **PR-2** | R2 | verify |
| **PR-3** | R3 + R4 | lean preset + `/rewind` |

Plan R5、R6、profiles、`require_approval` → **Harness v1 之后**。

---

## 完成定义（v1）

- [ ] #1–#6：gateway/CLI turn 上 `policy.yaml` deny 生效；子 agent 同 policy
- [ ] #7：至少一个 MCP tool 名可被 policy deny（若 PR-1 未含则 follow-up）
- [ ] #8：模型可 `verify`；白名单可配置
- [ ] #9：`contextProfile=lean` 可切换
- [ ] #10：`/rewind` 可恢复最近 checkpoint
- [ ] `loop.py` / `runner.py` 主路径增量保持薄（hook 注册 + deny 查表）
- [ ] 文档无离线 harness CLI 承诺；`policy.yaml.example` 可复制
