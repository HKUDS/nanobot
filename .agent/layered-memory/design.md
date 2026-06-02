# Layered Memory（分层记忆）· 设计规格

> 参考：[Tencent/TencentDB-Agent-Memory](https://github.com/Tencent/TencentDB-Agent-Memory)（符号化短期记忆 + L0–L3 长期金字塔）  
> 状态：**设计定稿，待实现**  
> 最后更新：2026-05-28  
> 实施计划：[`plan.md`](./plan.md)

本文档定义 nanobot 的 **Layered Memory** 子系统：在不大改 `loop.py` / `runner.py` 主路径的前提下，引入 TencentDB 式 **任务画布（短期）** 与 **L0–L3 分层长期记忆（长期）**。遵守 [`.agent/design.md`](../design.md) 与 [`.agent/security.md`](../security.md)。

**不含**：嵌入 Tencent npm 插件、OpenClaw 宿主适配、message 级 aggressive 删除（Phase F 可选后置）。

---

## 1. 背景与目标

### 1.1 要解决的问题

| 问题 | 现状 | 目标 |
|------|------|------|
| 长任务 tool 输出撑爆 replay | `maybe_persist_tool_result` + Context Budget CB2 | **任务级结构**（Mermaid/节点表）+ `node_id` 按需回查全文 |
| 跨 session 用户偏好/事实难召回 | `USER.md` + Dream 批量整理 | **L1 Atom** FTS/向量检索 + turn 前 **Recall** |
| 对话证据分散 | `Session.messages`、`history.jsonl` 摘要、`traces.sqlite` | **L0** 可搜原始消息；与 trace 可关联 |
| 场景/画像扁平 | 无 L2/L3 流水线 | **L2 Scenario**（Markdown）+ **L3 Persona**（收敛到 `USER.md`） |

### 1.2 nanobot 已有能力（不重复建设）

| 能力 | 位置 | Layered Memory 关系 |
|------|------|---------------------|
| Tool 大结果落盘 | `nanobot/utils/helpers.py` `maybe_persist_tool_result` | **复用路径**；`node_id` = `tool_call_id` |
| Tool 结果过滤 | `nanobot/agent/tool_result_filter/`（CB2） | **保留**；顺序：filter → persist → 登记 node |
| 会话 token 合并 | `Consolidator`（`memory.py`） | **并存**；不替代 `last_consolidated` |
| Dream | `memory.py` `Dream` | **分工**：Dream 维护 MEMORY/SOUL；L3 主写 **USER.md**（见 §4） |
| Turn trace | `evolution/trace_store.py` | L0 可挂 `turn_id`；GEPA/PostTask **不变** |
| Skill 检索 | `skill_index.py` / `skill_selector.py` | **独立**；L1 存用户事实，不进 skill 索引 |
| Evolution | `evolution/post_task.py`、GEPA | **只产 Skill**；L1 **不写** `skills/` |
| Context Budget | `context_budget.py`、CB1–CB4 | **独立**；动态成本 vs 语义记忆 |
| Runtime Harness | `harness/` | **独立**；`read_memory_node` 受 workspace policy 约束 |
| AgentHook | `hook.py` | 扩展 `after_tools`；`LayeredMemoryHook` 进 `CompositeHook` |
| Prompt 组装 | `context.py` `build_messages` | Recall/画布经 `current_runtime_lines` 注入 |

### 1.3 参考：TencentDB 双支柱（语义对齐，实现自研）

```text
┌─────────────────────────────────────────────────────────────┐
│ 短期 · Context Offload（本设计 §5）                          │
│   refs 全文 + nodes.json 索引 + canvas.mmd 任务图            │
│   turn 前注入画布摘要；按需 read_memory_node(node_id)        │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ 长期 · TDAI 分层（本设计 §6）                                │
│   L0 对话 → L1 Atom → L2 Scenario → L3 Persona             │
│   turn 后 capture；异步 Pipeline；turn 前 recall             │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 已定决策

| # | 问题 | 决策 |
|---|------|------|
| 1 | 是否嵌 Tencent 插件 | **否**；Python 原生，`nanobot/agent/layered_memory/` |
| 2 | `node_id` | **默认 = `tool_call_id`**；与 persist 文件名一致 |
| 3 | L3 存储 | **主路径 `workspace/USER.md`**（与 bootstrap 一致）；可选 `memory/persona.md` 仅当产品要拆分 |
| 4 | L1 vs Skill | **严格分离**：L1 = 用户事实/偏好；Skill = 可执行 SOP（PostTask/GEPA） |
| 5 | L1 vs Dream | Dream **不再**承担增量 Persona；cron 仍写 MEMORY/SOUL；USER 由 L3 job 或 Dream 只读二选一（**默认 L3 pipeline 写 USER**） |
| 6 | 默认开关 | `agents.defaults.layeredMemory.enable: false` |
| 7 | MVP 裁剪 | PR-1 画布 + PR-2 L0/L1/Recall；L2 后置；不做 message 级 L3 压缩（Phase F） |
| 8 | Recall 超时 | 默认 **5s**；超时则跳过注入，不阻塞用户首 token |
| 9 | 子 agent | offload/recall 可配置关闭；默认与主 agent 同 workspace 则 **继承** |

### 2.1 设计原则

- **Core stays small**：`LayeredMemoryFacade` 对外 API；`loop.py` 仅 `recall` / `capture` / `runtime_lines` 各一行级调用。
- **低层证据、高层结构**：全文在 DB/refs；prompt 只带摘要/图谱/Top-K atoms。
- **100% 可下钻**：`node_id` → tool_results 文件；L1 → `source_message_ids` → L0。
- **Turn 外抽长期**：L1/L2/L3 在后台 `asyncio` task / `SerialQueue`，不拉长用户可见延迟。

---

## 3. 总体架构

```
                    ┌──────────────────────────────────┐
                    │         AgentLoop                │
                    └──────────────────────────────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         │                            │                            │
         ▼                            ▼                            ▼
  consolidate (现有)          LayeredMemoryFacade          skill resolve (现有)
         │                     recall / capture                      │
         │                            │                            │
         ▼                            ▼                            ▼
  get_history ──────────► build_messages ◄── skill_entries + runtime_lines
  (现有)                  (context.py)      (cli + CB1 + canvas + recall)
         │                            │
         ▼                            ▼
                    AgentRunner (+ LayeredMemoryHook.after_tools)
         │                            │
         └──────── save_turn ─────────┘
                    │
                    ├─► TraceStore / PostTask (现有)
                    └─► capture_turn → L0 + Pipeline 调度
```

### 3.1 门面：`LayeredMemoryFacade`

| 方法 | 时机 | 行为 |
|------|------|------|
| `recall(query, session_key)` | `build_messages` **之前** | L1 检索 + 读 USER(L3) + 可选 L2 导航；返回 `prepend_lines`、`append_system` |
| `capture_turn(session, new_messages)` | `_save_turn` **之后** | 写 L0；`pipeline.notify(session_key, slice)` |
| `canvas_lines(session_key)` | 组 runtime 时 | 返回任务图摘要（≤ `max_canvas_chars`） |
| `register_tool_result(...)` | runner normalize 后 | 更新 `nodes.json` |

配置：`agents.defaults.layeredMemory`（见 §8）。

---

## 4. 与相邻子系统边界

| 子系统 | 写入 | 读取 | 禁止 |
|--------|------|------|------|
| **Layered L0** | turn 后增量消息 | `conversation_search` | 替代 session 文件 |
| **Layered L1** | Pipeline LLM 抽取 | `memory_search`、recall | 写 `skills/` |
| **Layered L2** | L1 后 scene job | recall 导航 + `read_file` | 与 L1 同表混存 |
| **Layered L3** | L2 后 persona job | recall、`USER.md` bootstrap | 与 Dream 双写 USER（需锁或单一 writer） |
| **Consolidator** | `history.jsonl` 摘要 | replay 预算 | — |
| **Dream** | MEMORY、SOUL | cron | Phase E3 后 **不 create skill**（已有 hermes-design） |
| **SkillIndex** | skill 文件变更 | 每 turn skill resolve | 存 L1 atoms |
| **CB2** | session 内 tool 字符串 | runner | 替代 refs 全文 |
| **Harness** | — | policy 约束 read/exec | 关闭 memory 工具 |

---

## 5. 短期记忆：Task Canvas + node_id（Phase LM1）

### 5.1 存储布局

```text
{workspace}/.nanobot/canvas/
  {safe_session_key}/
    nodes.json          # [{ "node_id", "tool", "path", "summary", "chars", "ts" }]
    canvas.mmd          # Mermaid 流程图（可选 v1 规则生成，v2 LLM 精炼）
```

Tool 全文仍在现有目录：

```text
{workspace}/.nanobot/tool_results/{session_bucket}/{tool_call_id}.txt
```

### 5.2 流水线

1. `runner._normalize_tool_result`：`ensure_nonempty` → **CB2 filter**（若启用）→ `maybe_persist` → `NodeRegistry.upsert`。
2. `AgentHook.after_tools`（**新增 hook 点**）：本轮 tool 完成后，规则追加节点（`tool` + 一行 summary，不调 LLM）。
3. Turn 末或每 `update_canvas_every_n_tools`：合并 `canvas.mmd`（v1 规则：`n1 --> n2`）。
4. `build_messages`：`current_runtime_lines` 追加 `[Task canvas]` + 截断后的 mmd + `nodes` 索引表。

### 5.3 工具：`read_memory_node`

- 参数：`node_id`（即 `tool_call_id`）。
- 行为：解析 `nodes.json` → `read_file` 等价读 persist 路径；受 workspace + Harness 约束。
- 错误：`node_id` 不存在时返回明确 hint（含最近 N 个 node 列表）。

### 5.4 与 Tencent offload 的差异（v1 不做）

| Tencent | nanobot v1 |
|---------|------------|
| `before_prompt_build` 替换 message 内 tool 块 | **不替换** session replay；靠画布 + CB2 + consolidate |
| L1/L1.5/L2 offload 管道 | 仅 **节点登记 + 规则 mmd** |
| tiktoken 级联 aggressive 压缩 | 交给 **CB3**（若实现）与 consolidate |

---

## 6. 长期记忆：L0 → L1 → L2 → L3（Phase LM2–LM4）

### 6.1 L0 — 原始对话

- **存储**：`{workspace}/.nanobot/memory.sqlite` 表 `l0_messages`（或按日 JSONL 二选一；**默认 SQLite** 对齐 `skill_index` / `traces`）。
- **字段**：`id`, `session_key`, `turn_id?`, `role`, `content`, `timestamp_ms`, `recorded_at`。
- **触发**：`capture_turn` 在 `_save_turn` 后只写入 **本轮增量** messages。
- **Sanitize**：剥离 `[Context budget:`、`[tool output persisted]`、skill 注入块、runtime 模板行（防反馈环）。
- **Checkpoint**：`plugin_start_ts` / session cursor；冷启动不灌全量 history。

### 6.2 L1 — 原子记忆（Atom）

- **触发**（`MemoryPipelineManager`）：
  - **A**：`conversation_count >= every_n`（默认 5；warm-up：1→2→4→…）。
  - **B**：session idle `l1_idle_timeout_seconds`（默认 600）。
  - **C**：graceful shutdown flush。
- **抽取**：单 LLM 调用 → 场景分段 + atoms；`l1_dedup` 与已有 atoms FTS 冲突检测。
- **存储**：表 `l1_memories` + **FTS5**；可选 embedding 列 + hybrid RRF。
- **类型**：`preference` | `fact` | `event` | `rule`（可扩展）；带 `source_message_ids`。

### 6.3 L2 — 场景块（Scenario）

- **存储**：`{workspace}/memory/scenes/{slug}.md` + `memory/scene_index.json`。
- **触发**：L1 完成后 `l2_delay_after_l1_seconds`；per-session **只提前不推后** 定时器 + `l2_max_interval` 保底。
- **Recall**：注入 **导航目录**（标题 + 路径），不全文灌入。

### 6.4 L3 — 用户画像（Persona）

- **存储**：**`workspace/USER.md`**（与现有 bootstrap 一致）。
- **触发**：L2 完成后全局 **mutex**（并发=1）。
- **Recall**：稳定块 → `append_system` 或合并进 system bootstrap（需评估 prompt cache；**优先短摘要进 runtime，完整 USER 仍走现有 identity 加载**）。

### 6.5 Recall（turn 前）

`perform_recall` 逻辑（对标 Tencent `auto-recall.ts`）：

1. L1：`fts` | `embedding` | `hybrid`（配置默认 `hybrid`）。
2. L3：读 `USER.md` 摘要（若 enable）。
3. L2：`scene_index` 生成导航 Markdown。
4. 附 **记忆工具指南**（`memory_search` / `conversation_search` 每轮合计 ≤3 次）。

输出：

- `prepend_lines` → 并入 `current_runtime_lines`（动态，跟 user 后，与 CB1 一致）。
- `append_system` → 仅当确需稳定 system 块时使用（慎用，避免破坏 cache）。

---

## 7. Hook 与 `loop.py` 挂点

### 7.1 新增 `AgentHook.after_tools`

在 `runner.py` tool 循环结束、`_emit_checkpoint(tools_completed)` 之后调用：

```python
await hook.after_tools(context)  # context.tool_results 已填充
```

`LayeredMemoryHook` 在此批量登记 node（若 normalize 已登记则可 no-op）。

### 7.2 `AgentLoop._process_message`（示意）

```text
consolidate_by_tokens
recall = await layered_memory.recall(query, session_key)   # 新增，带 timeout
history = session.get_history(...)
skill_entries = resolve_skill_entries(...)
runtime = cli_lines + budget_lines + canvas_lines + recall.prepend_lines
messages = build_messages(..., current_runtime_lines=runtime)
... agent run ...
save_turn(...)
asyncio.create_task(layered_memory.capture_turn(...))      # 新增，不阻塞回复
consolidate_by_tokens (background)
```

子 agent：默认 `offload.enable=false`、`recall.enable=false`（可配置）。

---

## 8. 配置（`LayeredMemoryConfig` → `AgentDefaults.layeredMemory`）

```python
class LayeredMemoryConfig(Base):
    enable: bool = False

    offload: LayeredMemoryOffloadConfig      # canvas, register_nodes
    capture: LayeredMemoryCaptureConfig      # L0 on/off, retention_days
    pipeline: LayeredMemoryPipelineConfig  # every_n, idle, warmup, L2 timers
    recall: LayeredMemoryRecallConfig      # strategy, top_k, timeout_ms
    embedding: LayeredMemoryEmbeddingConfig | None  # 可选，与 L1 hybrid 共用
```

| 键 | 默认 | 说明 |
|----|------|------|
| `offload.enable` | `false` | Task canvas + node registry |
| `offload.max_canvas_chars` | `1500` | 注入 prompt 的 mmd 上限 |
| `offload.update_canvas_every_n_tools` | `0` | 0=仅 turn 末更新 mmd |
| `capture.enable` | `false` | L0 写入 |
| `capture.l0_retention_days` | `30` | 0=不清理 |
| `pipeline.every_n_conversations` | `5` | L1 阈值 |
| `pipeline.enable_warmup` | `true` | 1→2→4→… |
| `pipeline.l1_idle_timeout_seconds` | `600` | |
| `recall.enable` | `false` | turn 前注入 |
| `recall.strategy` | `hybrid` | fts / embedding / hybrid |
| `recall.top_k` | `8` | |
| `recall.timeout_ms` | `5000` | |

实现时挂 `nanobot/config/schema.py`；用户文档链到 `docs/layered-memory.md`（实现后编写）。

---

## 9. 代码布局（目标）

```text
nanobot/agent/layered_memory/
  __init__.py
  facade.py              # LayeredMemoryFacade
  config.py              # 从 schema  re-export 或纯类型
  offload/
    node_registry.py
    canvas.py
    hook.py
  l0_store.py
  l1_store.py
  l1_extractor.py
  l1_dedup.py
  pipeline.py
  recall.py
  scene/                 # LM4
    extractor.py
    index.py
  persona/               # LM4
    generator.py
  sanitize.py

nanobot/agent/tools/
  memory_node.py         # read_memory_node
  memory_search.py       # memory_search
  conversation_search.py

tests/agent/layered_memory/
docs/layered-memory.md
```

`loop.py` / `runner.py` / `hook.py`：**增量**修改 only。

---

## 10. 测试与可观测

| 信号 | 形式 |
|------|------|
| node 登记 | `layered_memory node_registered tool=… chars=…` |
| recall | `layered_memory recall strategy=… hits=… ms=…` |
| pipeline | `layered_memory l1_trigger reason=threshold|idle chunk=…` |
| 失败 | 不抛到用户；log warning；turn 继续 |

---

## 11. 非目标（v1）

- 嵌套 `@tencentdb-agent-memory/memory-tencentdb` npm 包。
- 第一版 LLM 生成 Mermaid（可用规则图代替）。
- 用 L1 替代 Consolidator 或删除 `history.jsonl`。
- PersonaMem 类 benchmark 对齐（可后置 eval）。
- WebUI 记忆面板。

---

## 12. 相关文档

| 文档 | 关系 |
|------|------|
| [`.agent/design.md`](../design.md) | 架构约束 |
| [`.agent/hermes-design.md`](../hermes-design.md) | Evolution / Skill；L1 不写 skill |
| Context Budget（`docs/context-budget.md` 若存在） | 正交；CB2 在 persist 前 |
| Runtime Harness（`.agent/context-cost` 或 harness 文档） | policy 约束 tools |

---

## 13. 完成定义（整体验收）

- [ ] `layeredMemory.enable: false` 时零行为变化。
- [ ] 长任务（10+ tool）：画布注入 + `read_memory_node` 可还原全文。
- [ ] 多轮后 L1 可 `memory_search` 命中；recall 注入不阻塞 >5s。
- [ ] L0 `conversation_search` 可查到原文。
- [ ] Dream / PostTask / SkillIndex / Harness 行为无回归（单测 + 文档边界）。
