# Layered Memory（分层记忆）· 实施计划

> 设计规格：[`design.md`](./design.md)  
> 参考：TencentDB Agent Memory（语义对齐，Python 自研实现）  
> 状态：**待实现**  
> 最后更新：2026-05-28

**范围**：

- **LM1**：Task Canvas + `node_id` + `read_memory_node`（短期）。
- **LM2**：L0 capture + L1 Pipeline + Recall + `memory_search` / `conversation_search`（长期 MVP）。
- **LM3**：L2 Scenario + L3 Persona 与 Dream 边界收敛（后置）。
- **LM4**（可选）：发 LLM 前 message 级 offload 压缩（对标 Tencent `llm-input-l3`）。

**不含**：npm 插件、OpenClaw 适配、离线 benchmark suite。

**原则**：`loop.py` / `runner.py` 薄改动；逻辑在 `nanobot/agent/layered_memory/`；默认全关。

---

## 推荐 PR 切分

| PR | Phase | 内容 | 风险 |
|----|-------|------|------|
| **LM-PR-1** | LM0 + LM1 | `after_tools` hook、`NodeRegistry`、canvas、config、`read_memory_node` | 低 |
| **LM-PR-2** | LM2 | L0 store、capture、`MemoryPipeline`、L1 抽取+FTS、recall、search tools | 中 |
| **LM-PR-3** | LM3 | L2 scene、L3 persona job、Dream/USER 单 writer 文档+锁 | 中 |
| **LM-PR-4** | LM4 | message 替换 + 紧急压缩（可选，依赖 CB3 评估） | 高 |

可与 Context Budget **CB3**、Harness 并行，但 **LM-PR-1** 应独立于 CB 新 PR 以便 review。

---

## Phase LM0 — 基础设施

### LM0-A Hook 扩展

- [x] `nanobot/agent/hook.py`：新增 `async def after_tools(self, context) -> None`（默认 pass）
- [x] `CompositeHook`：fan-out `after_tools`
- [x] `nanobot/agent/runner.py`：`tools_completed` 之后、`after_iteration` 之前 `await hook.after_tools`；tool 失败路径同样调用
- [x] `tests/agent/test_runner_hooks.py`、`test_hook_composite.py`：顺序与 fan-out、错误隔离

### LM0-B 配置 schema

- [x] `nanobot/config/schema.py`：`LayeredMemoryConfig` 及子配置（见 design §8）
- [x] `AgentDefaults.layered_memory`（JSON：`layeredMemory`）
- [x] `AgentLoop.__init__` / `from_config`：传入 `layered_memory`
- [x] `tests/config/test_layered_memory_config.py`

### LM0-C 包骨架

- [x] `nanobot/agent/layered_memory/__init__.py`
- [x] `facade.py`：`LayeredMemoryFacade` 空实现 + `enabled` 短路
- [x] `AgentLoop._layered_memory_facade`（`LayeredMemoryFacade(workspace, config)`）
- [x] `tests/agent/layered_memory/test_facade.py`
- [x] `.agent/layered-memory/plan.md`（本文档）

**验收**：`enable: false` 时 hook 新增不改变行为；pytest 通过。

---

## Phase LM1 — 短期：Task Canvas + node_id（LM-PR-1）

### LM1-A Node 登记

- [x] `offload/node_registry.py`：`upsert(node_id, tool, path, summary, chars)`
- [x] `helpers.py`：`MaybePersistOutcome` + 引用串 `node_id:` 行
- [x] `runner._normalize_tool_result`：persist 后经 `LayeredMemoryFacade.register_tool_result` 写 registry（CB2 接入后保持同顺序）
- [x] `AgentRunSpec.layered_memory_facade` + `loop` 传入
- [x] 单测：`test_node_registry.py`、runner 大结果登记

### LM1-B Canvas

- [x] `offload/canvas.py`：读写 `workspace/.nanobot/canvas/{session}/canvas.mmd`
- [x] v1 **规则更新**：`build_mermaid_from_nodes` → `graph TD` 链（按 `ts`）；`refresh_canvas` / `canvas_lines` 触发
- [x] `update_canvas_every_n_tools` > 0 时在 `register_tool_result` 周期性 refresh
- [x] `facade.canvas_lines(session_key)` → 截断至 `max_canvas_chars`
- [x] `tests/agent/layered_memory/test_canvas.py`

### LM1-C Hook + runtime 注入

- [x] `offload/hook.py`：`LayeredMemoryHook`（`after_tools` → `sync_tool_nodes` + refresh）
- [x] `loop.py`：`_layered_memory_runtime_lines` → `canvas_lines` + `recall.prepend_lines`
- [x] `loop.py`：`_state_build` / system message / `_build_initial_messages` 注入 runtime
- [x] `loop.py`：`CompositeHook` 在 `offload.enable` 时挂 `LayeredMemoryHook`
- [x] turn 末 `_state_save` / system path：`refresh_canvas`
- [x] `tests/agent/layered_memory/test_hook_runtime.py`

### LM1-D Tool

- [x] `nanobot/agent/tools/memory_node.py`：`read_memory_node(node_id)`
- [x] `ToolContext.layered_memory` + `ToolLoader` 自动注册（仅 `core` scope，`offload.enable` 时）
- [x] 路径经 `resolve_workspace_path`（与 `read_file` / Harness 边界一致）
- [x] `tests/agent/layered_memory/test_memory_node_tool.py`

### LM1-E 文档

- [x] `docs/layered-memory.md`：LM1 配置示例、与 CB2/persist 关系
- [x] `docs/configuration.md`：链接与配置表（简短）

**验收**：

- 本地长会话：10 次大 `read_file`/`grep` 后 `/status` context 涨幅趋缓（相对无 canvas）。
- `read_memory_node` 与直接 `read_file` persist 路径一致。

---

## Phase LM2 — 长期 MVP：L0 + L1 + Recall（LM-PR-2）

### LM2-A L0 存储

- [x] `l0_store.py`：SQLite `{workspace}/.nanobot/memory.sqlite` 表 `l0_messages`
- [x] `sanitize.py`：剥注入块、短消息过滤
- [x] `capture_turn`：仅写入本轮增量；checkpoint 防冷启动全量导入
- [x] 单测：两轮 capture 行数递增；sanitize 不去掉真实用户句

### LM2-B Pipeline 骨架

- [x] `pipeline.py`：`MemoryPipelineManager`（buffer、`every_n`、idle timer、warm-up）
- [x] `SerialQueue` 或 `asyncio.Lock` 串行 L1 job
- [x] `loop.py`：`_save_turn` 后 `asyncio.create_task(facade.capture_turn(...))`
- [x] 单测：mock LLM 下 N 轮触发一次 L1

### LM2-C L1 抽取

- [x] `l1_store.py`：FTS5 `l1_memories`
- [x] `l1_extractor.py` + `templates/` 或 `prompts/l1_extraction.md`
- [x] `l1_dedup.py`：与已有 atoms 冲突合并/跳过
- [x] 单测：fixture 对话 → 抽出 ≥1 atom；重复不双写

### LM2-D Recall

- [x] `recall.py`：`perform_recall`（fts / hybrid、timeout、prepend_lines）
- [x] `loop.py`：`consolidate` 之后、`get_history` 之前 `await facade.recall`
- [x] L3 v2 简化：**只读现有 `USER.md`** 作摘要，不跑 L3 生成 job
- [x] 单测：种子 atom + query → prepend 含关键词；超时返回空

### LM2-E 搜索 Tools

- [x] `tools/memory_search.py`
- [x] `tools/conversation_search.py`
- [x] recall 注入 **工具指南**（每轮 search ≤3）
- [x] 单测：各 tool 返回格式稳定

### LM2-F 集成

- [x] `facade.py` 接通 capture/recall/canvas
- [x] 子 agent：`layered_memory` 默认子集关闭（config 或 loop 判断 `is_subagent`）
- [x] 结构化 log：`layered_memory …`（见 design §10）

**验收**：

- 5 轮对话后 `memory_search` 可命中。
- `conversation_search` 可找回 L0 原文片段。
- recall 超时 5s 不卡住 gateway。

---

## Phase LM3 — L2 Scenario + L3 Persona（LM-PR-3）

### LM3-A L2

- [ ] `scene/extractor.py`：L1 完成后 LLM 生成/更新 scene md
- [ ] `scene/index.py`：`scene_index.json`
- [ ] Pipeline：L2 定时器（delay-after-L1、maxInterval、session 冷取消）
- [ ] recall：注入场景导航（非全文）

### LM3-B L3

- [ ] `persona/generator.py`：L2 后更新 `USER.md`（mutex）
- [ ] **Dream 边界**：更新 `hermes-design.md` / `gotchas.md` — USER 单 writer
- [ ] 可选：file lock `workspace/.nanobot/persona.lock`

### LM3-C 文档

- [ ] `docs/layered-memory.md` 补 L2/L3、与 Dream 对照表

**验收**：

- L1 跑批后 `memory/scenes/` 有新文件；recall 含导航。
- L3 job 后 `USER.md` 反映新偏好；Dream cron 不覆盖冲突（或显式跳过 USER phase）。

---

## Phase LM4 — 可选：Message 级 Offload（后置）

- [ ] 设计评审：与 CB3 `critical_replay_cap` 是否重复
- [ ] `runner` 或 hook：在 `before_iteration` 将旧 tool message 替换为 node 摘要
- [ ] 历史 MMD 注入（对标 `mmd-injector`）
- [ ] integration：长 session replay token 下降

**默认 v1 不做**，仅在 LM1–LM3 稳定后立项。

---

## 测试矩阵

| 场景 | 类型 | Phase |
|------|------|-------|
| `enable: false` 无 registry / 无 recall | unit | LM0 |
| `after_tools` 调用顺序 | unit | LM0 |
| persist → nodes.json | unit | LM1 |
| canvas 注入 runtime | unit | LM1 |
| `read_memory_node` | unit | LM1 |
| L0 sanitize + checkpoint | unit | LM2 |
| pipeline every_n + idle | unit | LM2 |
| L1 extract + dedup | unit | LM2 |
| recall timeout | unit | LM2 |
| memory_search / conversation_search | unit | LM2 |
| L2 scene 文件生成 | integration | LM3 |
| USER 单 writer | integration | LM3 |
| 长任务 context % vs baseline | manual | LM1 |

---

## `loop.py` / `runner.py` 改动清单（审查用）

| 文件 | 预估行数 | 内容 |
|------|----------|------|
| `hook.py` | +15 | `after_tools` |
| `runner.py` | +5 | 调用 `after_tools` |
| `runner.py` | +8 | normalize 后 registry |
| `loop.py` | +12 | recall + canvas runtime + capture task |
| `loop.py` | +5 | 注册 `LayeredMemoryHook` |
| `helpers.py` | +10 | node_id  in reference string |
| `schema.py` | +80 | config models |
| `context.py` | 0 | 不改签名，仅用 `current_runtime_lines` |

---

## 调参（实现后）

见 `docs/layered-memory.md`（LM1 完成后起草）：

- 长 SWE 任务：`offload.enable` + `readFilterLevel: aggressive`（CB2）叠加
- 多 session 用户：`recall.strategy: hybrid`、`pipeline.every_n: 3`
- 省 LLM 成本：`pipeline.enable_warmup: true`、L2 `min_interval` 调大

---

## 完成定义（v1）

- [ ] LM-PR-1 merged：canvas + node + `read_memory_node` + 文档 LM1 章
- [ ] LM-PR-2 merged：L0/L1/Recall + 两 search tools
- [ ] 默认 `enable: false`；CI `tests/agent/layered_memory/` 绿
- [ ] `.agent/layered-memory/design.md` 与实现一致（偏差在 PR 描述中说明）
- [ ] LM3 可单独 follow-up，不阻塞 v1 叙事（「短期+长期 MVP」）

---

## 依赖与顺序

```text
LM0 (hook + schema)
  → LM1 (offload)     ─┐
  → LM2 (L0/L1/recall) ├─ LM2 可与 LM1 并行开发，但 merge 建议 LM1 先
  → LM3 (L2/L3)       ─┘ 依赖 LM2 Pipeline
  → LM4 (optional)
```

**与 Hermes Evolution**：无硬依赖；TraceStore 可被 L0 引用 `turn_id`。  
**与 Context Budget**：CB2 应在 persist 前；CB1 recall 行与 layered recall 合并顺序：**cli → layered recall → CB1 budget → canvas**（实现时在 `loop.py` 固定顺序并单测快照）。
