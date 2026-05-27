# Runtime Harness + 上下文/成本 · 实施计划

> 设计规格：[`design.md`](./design.md)  
> 最后更新：2026-05-26

**范围**：仅 **在线 Runtime Harness**（策略、verify、checkpoint 用户面、context preset）。**不含** 离线 `nanobot harness run` / YAML cases / CI eval suite。

**推荐顺序**：**R0→R1→R2** 可独立交付；**R3** 与 Plan **P2** 并行；**R4** 体验；Plan **P3** 依赖 **R2**（verify 执行器）。

与 [plan-mode/plan.md](../plan-mode/plan.md) 的 Harness case 验收已改为 **command + verify**，见 plan-mode 文档同步。

---

## Phase R0 — 配置与加载

- [ ] `HarnessConfig`、`HarnessVerifyConfig` in `nanobot/config/schema.py`
- [ ] `nanobot/agent/harness/loader.py`：读 `workspace/.nanobot/harness/policy.yaml`、`presets/<profile>.yaml`
- [ ] 缺失文件 → 空 policy；解析错误 → log + 空 policy
- [ ] `templates/harness/policy.yaml.example`（文档/复制用，onboard 不强制写盘）
- **验收**：`tests/agent/harness/test_loader.py`

---

## Phase R1 — 策略 Hook（PreTool）

- [ ] `nanobot/agent/harness/policy.py`：`evaluate(tool, args, channel) -> PolicyDecision`
- [ ] `nanobot/agent/harness/policy_hook.py`：`HarnessPolicyHook`
- [ ] `AgentLoop`：`harness.enable` 时注入 `CompositeHook`（系统 hook 在前）
- [ ] deny 路径：跳过 execute，返回带 `harness_policy` 的 tool error
- [ ] 通道覆盖：`RequestContext` / inbound channel 传入 hook
- **验收**：`tests/agent/harness/test_policy.py`、`test_policy_hook.py`（mock tool calls）

---

## Phase R2 — `verify` tool + 执行器

- [ ] `nanobot/agent/harness/verify.py`：`run_verify_command(command, cwd, timeout) -> VerifyResult`
- [ ] `nanobot/agent/tools/verify.py`：注册 tool；白名单来自 config
- [ ] `loop._register_default_tools` 注册（`harness.verify.enabled`）
- [ ] 文档：`docs/configuration.md` → **Runtime Harness** 小节（简）
- **验收**：`tests/agent/harness/test_verify.py`；tool 集成测 1 例（mock subprocess）

---

## Phase R3 — Context preset

- [ ] `presets/lean.yaml`、`quality.yaml` 示例 + 展开逻辑（启动 turn 时合并到运行时视图）
- [ ] `agents.defaults.harness.contextProfile` 接线
- [ ] 文档说明：改 compaction/retrieval 时如何用 `/status` + trace 对比（**无** 离线 suite）
- **验收**：单测 preset 展开字段；可选手工记录 baseline 表在 design 附录（非 CI）

---

## Phase R4 — Checkpoint 用户面

- [ ] `nanobot/command/harness.py` 或 `builtin`：`/rewind`、`/checkpoint`（只读摘要）
- [ ] 与现有 `_restore_runtime_checkpoint` 对齐；文档说明与 `/stop` 关系
- [ ] WebUI：撤销按钮（**可选**，可与 plan 面板同 PR 或后做）
- **验收**：`tests/` 覆盖 restore 路径（可复用 loop 已有测 + 新 command 测）

---

## Phase R5 — Plan 联动（依赖 R2）

- [ ] `plan_complete_step`：`acceptance.type=command` 调用 `verify.run_verify_command`
- [ ] 移除/勿实现 `acceptance.type=harness` + `HarnessRunner`
- [ ] `plan.requireVerifyForDone`（原 `requireHarnessForDone` 更名）配置
- [ ] `/plan-verify <step_id>` 强制跑 step 的 command
- **验收**：见 [plan-mode/plan.md](../plan-mode/plan.md) P3（mock verify pass/fail）

---

## Phase R6 — 可观测（可选）

- [ ] Trace / tool_events 附加 `harness_policy_denies`、`verify_runs` 摘要
- [ ] 结构化 log 字段稳定
- **验收**：trace 单测或 snapshot

---

## 不做清单（明确关闭）

- [ ] ~~`nanobot harness run`~~
- [ ] ~~`workspace/.nanobot/harness/cases/`~~
- [ ] ~~`HarnessRunner` / `AssertionEngine`~~
- [ ] ~~GitHub Actions harness workflow~~
- [ ] ~~`evolution.requireHarnessPass`~~
- [ ] ~~`export-trace` → case yaml~~

---

## 测试矩阵

| 场景 | 类型 | Phase |
|------|------|-------|
| policy deny exec | unit | R1 |
| channel override telegram deny exec | unit | R1 |
| verify 非白名单命令 | unit | R2 |
| verify pytest 成功/失败 mock | unit | R2 |
| preset lean 展开 maxMessages | unit | R3 |
| /rewind 恢复 checkpoint | integration | R4 |
| plan_complete_step command acceptance | integration | R5 |

---

## PR 切分建议

1. **R0+R1**：策略 + hook（用户可配 policy.yaml）
2. **R2**：verify tool（Plan 前置依赖）
3. **R3**：preset（可独立）
4. **R4**：slash rewind
5. **R5**：与 plan-mode P3 同 PR 或紧随

---

## 完成定义（v1）

- [ ] `workspace/.nanobot/harness/policy.yaml` 可限制工具；deny 在 gateway turn 生效
- [ ] 模型可调用 `verify`；白名单可配置
- [ ] `contextProfile=lean` 可切换预设
- [ ] `/rewind` 可恢复最近 checkpoint
- [ ] Plan 步骤可用 `acceptance.type=command` 验收
- [ ] 文档无离线 harness CLI 承诺
