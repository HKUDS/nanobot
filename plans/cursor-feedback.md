已在仓库中读完所有计划文件（路径为 `PyNanoBot/plans/*.md`）。下面是**整体审阅**和**建议实施顺序**，便于你从 `plan1-mem.md` 开始逐步落地。

---

## 四份计划概览

### `plan1-mem.md` — 增强记忆（基础层）

- **目标**：用更接近 Claude Code 的思路升级 `MemoryStore`（主题文件、`MEMORY.md` 作索引、四类标签、可选的「dream」整理、全局 `~/.nanobot/memory` + 工作区记忆）。
- **交付物**：主要替换/扩展 `nanobot/agent/memory.py`（文档里给了接近完整实现）。
- **兼容性**：保留 `get_today_file` / `read_today` / `append_today` 等旧 API。
- **注意**：后续若按 plan4 示例调用 `memory.stats()`，当前 plan1 草稿里**没有** `stats()`，集成时要么补方法，要么改示例。

---

### `plan2-context-compact.md` — 多层上下文压缩

- **目标**：在 token 预算压力下做 L0→L1→L2→L3 级联压缩；L3 通过 `memory.remember()` 落到持久记忆。
- **交付物**：新增 `nanobot/agent/compactor.py`，依赖 **plan1 的 `MemoryStore`**（`read_index`、`remember` 等）。
- **特点**： summarizer 可注入 LLM，否则用抽取式 fallback；与「按时间轮询」无关，**由预算驱动**。

---

### `plan3-sub-agent.md` — 子代理编排

- **目标**：父代理分解任务、隔离上下文、按 wave 并行子任务、合并结果。
- **交付物**：`nanobot/agent/subagent.py`，依赖 **plan2 的 `ContextCompactor`**（以及 plan1 的 memory 间接通过 compactor）。
- **注意**：文档中的 `plan_delegation` / `_parse_plan_response` 大量是**结构示例**，真正上线需要接 LLM 解析或更稳的启发式；`SubagentRunner` 假设存在 `llm.agentic_complete` 等接口，需与**当前 nanobot 真实 LLM/工具层**对齐。

---

### `plan4-reminder-hook.md` — 防漂移提醒 + 生命周期 Hooks

- **内容分两块**：
  1. **`ReminderEngine`**：周期性 + 漂移检测 + 预算压力等触发，返回待注入的短 system 文案。
  2. **`HookManager`**：会话/轮次/工具前后/读写文件等钩子；可选从 `.nanobot/hooks.json` 加载 shell 命令。
- **集成示例**：文末 `AgentRunner` 把 memory、compactor、reminders、hooks 串在一起；其中 `shutdown` 里调用了 **`memory.stats()`**，与 plan1 草稿不一致，实现时要统一。

---

## 依赖关系（为什么顺序是 1→2→3→4）

| 计划 | 强依赖 |
|------|--------|
| Plan1 | 无（先打地基） |
| Plan2 | Plan1（`MemoryStore`） |
| Plan3 | Plan2（`ContextCompactor`） |
| Plan4 | 可与 2/3 并行设计，但**示例 runner** 假设已有 compactor + memory；Hooks 应在 agent 主循环里接线 |

从 **`plans/plan1-mem.md`** 开始是合理顺序；2、3 顺序不能颠倒；4 可在 2 完成后就与主循环一起接，不必等子代理，但文档里的「全家桶」示例自然放在较后阶段最顺。

---

## 实施前建议对齐的几点

1. **与现有代码对齐**：计划里的 API（如 `agentic_complete`、工具名）可能和本仓库克隆的 nanobot 不一致，需要以**当前** `nanobot/agent/` 为准做适配层，而不是原样粘贴。
2. **`stats()`**：若采用 plan4 的 shutdown 示例，给 `MemoryStore` 增加轻量 `stats()`，或改掉示例中的调用。
3. **安全**：plan4 里 shell hook 的 `condition` 使用受限 `eval`，若开放给用户配置，要评估是否改为白名单表达式或预定义字段。

如果你下一步希望**直接开始实现 plan1**，可以说一声，我可以在当前仓库里对照真实的 `memory.py` 和调用方，按 plan1 落地并跑通最小测试路径。
