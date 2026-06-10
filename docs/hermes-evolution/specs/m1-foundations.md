# M1 · Foundations 设计 Spec

> **Milestone**：M1（地基层）。属于 [Hermes 风格自我进化能力路线图](../roadmap.md) 的第一阶段。
>
> **状态**：设计已锁定（2026-06-11，brainstorming 通过）。
>
> **依赖**：无（M1 为后续所有 milestone 的基础）。
>
> **下游**：M2（skill_manage）、M3（Curator）、M4（离线骨架）都依赖本 milestone 引入的 provenance / telemetry / aux provider 三件套。

## 0. 调研与决策出处

- 整体调研：[`docs/hermes-self-evolution.md`](../../hermes-self-evolution.md)
- 总路线图：[`docs/hermes-evolution/roadmap.md`](../roadmap.md)
- 本 spec 决策日志见 [§9](#9-决策日志)

## 1. 范围与非范围

### 1.1 M1 做（in-scope）

1. **目录约定**：新增 `<workspace>/skills/agent/` 子目录，专门承载 agent 自创建的 skill。
2. **SkillsLoader 三源支持**：原有 `workspace / builtin` 两源（注：`SkillsLoader.source` 字段历史命名）扩展为三源 `workspace(user) / agent / builtin`，加载优先级 user > agent > builtin，启动期对同名 collision 打 WARNING。新增 `list_skills_with_shadows()` 方法供 telemetry 使用。术语映射见 [§3.1](#31-术语映射)。
3. **Telemetry 子系统**：新增 `<workspace>/skills/.telemetry.json`、`SkillTelemetry` 辅助类、filelock + 锁内 RMW 合并（多进程安全）、内存层 `threading.Lock`、孤儿清理、view/use/patch 计数 hook（统一 `bump(name, kind)` 单入口；`patch` kind M1 不调用）。
4. **Provenance frontmatter 字段**：仅在 agent 创建 skill 时写入 `nanobot.provenance: {origin: agent, created_at: ISO8601}`，其他来源 skill 不强制。读取路径明确为 `_get_skill_meta(name).get('provenance', {})`。
5. **Auxiliary provider 配置**：在 `agents.defaults.auxiliary.modelPreset` 引入一个引用现有 `modelPresets` key 的配置项；新增 `get_auxiliary_client()` 工厂；未配置时 fallback 到主 preset。配置层校验（preset key 是否存在）下沉到 schema validator，不做运行时 smoke-test。
6. **SkillsLoader 计数挂钩**：仅在 `build_skills_summary()` 的尾部循环（每次列入摘要时）`bump(name, "view")`，仅在 `load_skills_for_context()` 真正注入 prompt 时 `bump(name, "use")`；**绝不在 `list_skills()` 内挂 hook**（防止 WebUI 列表查询等非 agent 上下文污染计数）；每个 agent turn 出口异步 `flush()`，进程退出 `atexit` 兜底。
7. **单元 + 集成测试**：覆盖并发写、孤儿清理、collision 检测、schema 解析、aux provider fallback、端到端 telemetry 落盘。

### 1.2 M1 不做（out-of-scope）

| 排除项 | 留给 |
|---|---|
| `skill_manage` 工具（create/patch/edit/delete） | M2 |
| 任何 Curator 行为或 `/curator` 命令 | M3 |
| `patches` 计数器的实际递增 | M2 的 `skill_manage` 触发 |
| LLM-as-judge / rubric 评估 | M4 |
| DSPy/GEPA/MIPROv2 离线管线 | M4 |
| Darwinian Evolver 接入 | M5 |
| user-facing slash 命令（`/skills`、`/skills-telemetry`） | M3（连同 `/curator` 一组发布） |
| 现有 user skill 数据迁移工具 | 不需要（user skill 路径不变） |

## 2. 文件系统结构

```
<workspace>/
└── skills/                          # user skills（现状，不动）
    ├── my-recipe/SKILL.md
    ├── agent/                       # NEW: agent-authored skills 隔离
    │   ├── auto-summarize/SKILL.md  # 含 nanobot.provenance frontmatter
    │   └── debug-recovery/SKILL.md
    └── .telemetry.json              # NEW: telemetry 索引（扁平 schema，全 skill）

nanobot/skills/                      # builtin（现状，不动）
└── ...
```

**关键约束**：

- `agent/` 子目录的存在不强制；启动时若不存在，`SkillsLoader` 视为空（不会自动创建，由 M2 的 `skill_manage` 在首次创建 skill 时按需 `mkdir -p`）。
- `.telemetry.json` 路径固定在 `<workspace>/skills/` 下（不在 `<workspace>/skills/agent/` 下），因为它管全部 skill 来源。
- **`.gitignore` 建议**：如果 user 把 `<workspace>` 纳入 git，建议在 `<workspace>/.gitignore` 增加：
  ```
  skills/.telemetry.json
  skills/.telemetry.json.tmp
  skills/.telemetry.json.lock
  ```
  原因：telemetry 是机器运行时计数，跨机器无意义；同时排除原子写的 `.tmp` 与 filelock 产生的 `.lock` 临时文件，防止误提交。M1 不强制改 workspace 模板，仅在文档中说明（user 自管）。

## 3. 加载优先级与 collision 处理

### 3.1 术语映射（重要）

历史代码与新设计存在术语二元性，本 spec 强制以下映射，所有新增代码与文档必须遵守：

| 概念维度 | 现有代码字段 | 取值集 | telemetry / provenance 字段 | 取值集 | 备注 |
|---|---|---|---|---|---|
| skill 的物理来源 | `SkillsLoader._skill_entries_from_dir(..., source=...)` | `"workspace"` / `"builtin"` | `entry["origin"]`（telemetry） / `metadata.nanobot.provenance.origin`（frontmatter） | `"user"` / `"agent"` / `"builtin"` | `source="workspace"` 拆成 `origin="user"` 或 `origin="agent"`，依据物理路径是否在 `<workspace>/skills/agent/` 子目录 |

**强制规则：**

- `SkillsLoader.source` 字段名因历史命名保留，**新代码一律不再向外暴露 `source` 字面值**，对外只暴露 `origin`。
- M1 新增的 `list_skills_with_shadows()` 返回值必须使用 `effective_origin / shadowed_origins` 命名（即 `origin` 命名空间），不得回写 `source`。
- Telemetry 内部仅按 `origin` 三值（`user/agent/builtin`）键存储，**不出现 `workspace` 字面量**。
- 文档与日志：面向用户与未来 agent 的所有输出（warning、CLI、注释、说明）一律用 `user/agent/builtin`。

### 3.2 优先级

`SkillsLoader.list_skills()` 按以下顺序合并三源（先入为主）：

1. `<workspace>/skills/*/SKILL.md`（user，**最高优先级**）
2. `<workspace>/skills/agent/*/SKILL.md`（agent）
3. `nanobot/skills/*/SKILL.md`（builtin，**最低优先级**）

同名 skill 仅取最高优先级源的内容；其他源被"影子"。

### 3.3 Collision 检测

启动时如检测到跨源同名：

- 用 `loguru.warning` 输出一次，格式：
  ```
  Skill name collision: 'summarize' shadowed at <workspace>/skills/summarize/SKILL.md,
    hidden at [<workspace>/skills/agent/summarize/SKILL.md,
              nanobot/skills/summarize/SKILL.md]
  ```
- **每次启动只打一次**，避免重复噪声（实现：collision 检测放在 `SkillsLoader.__init__` 而非每次 `list_skills()`）。
- 不阻塞启动；不自动重命名；user 自己决定如何处理。

### 3.4 不重命名原则

M1 不引入"自动加后缀"或"namespace 前缀"机制（即 brainstorming 排除的 C/D 方案）。user 永远拥有对名字空间的最终权力。

## 4. Telemetry 子系统

### 4.1 文件格式（schema_version = 1）

```json
{
  "schema_version": 1,
  "updated_at": "2026-06-11T03:14:15Z",
  "entries": {
    "summarize": {
      "origin": "builtin",
      "shadowed": [],
      "views": 142,
      "uses": 38,
      "patches": 0,
      "entry_created_at": "2026-05-20T10:00:00Z",
      "last_view": "2026-06-11T03:10:00Z",
      "last_use": "2026-06-11T03:08:00Z"
    },
    "auto-summarize": {
      "origin": "agent",
      "shadowed": [],
      "views": 7,
      "uses": 2,
      "patches": 1,
      "entry_created_at": "2026-06-09T14:22:00Z",
      "last_view": "2026-06-11T02:50:00Z",
      "last_use": "2026-06-10T18:00:00Z"
    }
  }
}
```

字段约定：

| 字段 | 类型 | 含义 | 缺省值 |
|---|---|---|---|
| `origin` | `"user"\|"agent"\|"builtin"` | 当前生效源（不是出生证） | 启动 reconcile 时写入 |
| `shadowed` | list of strings | 同名被影子的来源列表，便于 debug | `[]` |
| `views` | int | skill 摘要被注入到 **agent 主 prompt（`build_skills_summary()` 的 agent-context 调用方）** 的次数；WebUI / CLI 列表等非 agent 上下文不计入 | 0 |
| `uses` | int | skill 完整内容被 `load_skills_for_context()` 注入 prompt 的次数 | 0 |
| `patches` | int | M2 起由 `skill_manage` 触发 | 0 |
| `entry_created_at` | ISO8601 | telemetry **首次给该 skill 创建条目**的时间。语义为"telemetry 文件层面的出生时间"，**不等于** skill 在磁盘上的诞生时间（已存在很久的 skill 在 telemetry 首次 reconcile 时才被写入），故避免使用 `first_seen` 这种容易误读的命名 | reconcile 时写入 |
| `last_view` / `last_use` | ISO8601 \| null | 最近一次事件时间 | null |

#### Schema 演进规则（向前兼容）

`schema_version` 是写入侧的版本声明，读取侧策略如下：

- `schema_version == 1`：M1 当前版本，全功能解析。
- `schema_version > 1`：未来版本。读取侧只读已知字段，不报错；写回时**保留**未识别字段（透传），避免新版本写完老版本 truncate 的兼容地雷。
- `schema_version < 1` 或缺失：视为损坏，记 WARN 并按"新文件"重建（不抛异常）。
- `schema_version == 1` 但缺少必填字段（如 `entries` 不是 dict）：同上，重建。

变更 schema_version 必须在本 spec 与未来 milestone spec 的"决策日志"中各落一行，并提供从旧版到新版的 migration 路径。

### 4.2 `SkillTelemetry` 类（新文件 `nanobot/agent/skills_telemetry.py`）

API 表面（最小可用）：

```python
from typing import Literal, TypedDict

BumpKind = Literal["view", "use", "patch"]


class SkillEntry(TypedDict):
    name: str
    effective_origin: Literal["user", "agent", "builtin"]
    shadowed_origins: list[str]   # 若无 collision 则空
    path: str                     # effective SKILL.md 路径


class SkillTelemetry:
    def __init__(self, workspace: Path) -> None: ...

    def reconcile(self, known_skills: list[SkillEntry]) -> None:
        """启动时调用：删除孤儿条目；为新出现的 skill 写零计数初始条目；
        同时更新 entries 的 effective `origin` 与 `shadowed` 字段。

        SkillsLoader 必须提供 `list_skills_with_shadows()` 返回上述 SkillEntry 列表。

        **行为边界（不可越界）：**
        - reconcile **只**触碰 `origin`、`shadowed`、（必要时）`entry_created_at`；
          **绝不写** views/uses/patches/last_view/last_use（这些是事件流计数器，与 reconcile 无关）。
        - 这确保 reconcile 与 bump() 的 RMW 路径互不冲突，避免"reconcile 把内存里
          未 flush 的计数清零"这类竞态。
        """

    def bump(self, name: str, kind: BumpKind) -> None:
        """单一入口，统一三类事件：

        - kind="view"  → views += 1, last_view = now（M1 由 build_skills_summary 调用）
        - kind="use"   → uses  += 1, last_use  = now（M1 由 load_skills_for_context 调用）
        - kind="patch" → patches += 1（M1 不调用；预留给 M2 的 skill_manage 工具）

        **未知 name 的容忍策略：**
        - 若 `name` 不在 telemetry entries 中（例如 reconcile 还没跑、或 skill 刚被 M2 创建尚未 reconcile）：
          按"懒初始化"创建零计数条目，再做 bump；不抛异常。
        - 但 `origin` 缺失时填 `"unknown"`（而非乱猜），等下一次 reconcile 修正。

        **线程安全：** 实现内部使用 `threading.Lock` 保护内存 dict，详见 §4.3。
        """

    def snapshot(self) -> dict:
        """返回当前 telemetry 的只读深拷贝，给未来的 Curator/CLI 用。"""

    def flush(self) -> None:
        """显式触发磁盘落盘：内存 dict → filelock 持锁 RMW 合并 → 原子写。详见 §4.3。"""
```

**为什么单 `bump(name, kind)` 而非三个 `bump_views/uses/patches`：**

- 调用点统一一套加锁路径，避免三份重复实现走偏。
- 未来新增 kind（M3 可能加 `archive` 计数）只需扩 `Literal` 与 dispatch 表，不再扩 API 表面。
- 单元测试覆盖一套就够，减少漏测。

**`SkillsLoader.list_skills_with_shadows()` 实现规则：**

- 内部仍走 `_skill_entries_from_dir`，但显式把 `<workspace>/skills/agent/` 拆分成独立"agent"源，与"workspace=user"区别开（见 §3.1 术语映射）。
- **必须遵守 `disabled_skills` 过滤**：与 `list_skills()` 一致，被禁用的 skill 既不出现在结果中，也不被 reconcile 写入 telemetry（避免 user 关闭某 skill 后 telemetry 仍持续 reconcile 它）。
- **不做 frontmatter requirements 过滤**（即 `filter_unavailable=False` 语义）：reconcile 需要看到"物理上存在但运行时不可用"的 skill，否则它们会被错误清理。
- **不缓存**：每次调用都重新扫描磁盘。reconcile 一次性成本可接受；惰性读取也可在未来加缓存，不破坏接口。

### 4.3 并发与持久化

#### 两层锁模型

| 层 | 工具 | 保护对象 | 粒度 |
|---|---|---|---|
| 内存层 | `threading.Lock` | `self._entries`（内存 dict）、`self._dirty`（脏标志） | 单进程多协程/线程安全 |
| 进程间层 | `filelock.FileLock(<workspace>/skills/.telemetry.json.lock)` | 磁盘 `.telemetry.json` 的 read-modify-write 操作 | 跨进程、跨进程内多 agent loop 安全 |

> 现实约束：nanobot 在同一 workspace 下可能跑 `gateway`、`agent CLI`、子 agent（subagent.py）等多个进程；同时同一进程内既有主 agent loop 协程，也有 WebUI handler 协程。两层缺一不可。

#### 写入流程（`flush()`）

```
acquire threading.Lock                          # 单进程内排他
  if not self._dirty: return                    # 无变化直接返回
  snapshot = deep_copy(self._entries)
  self._dirty = False
release threading.Lock

acquire filelock (timeout=200ms × 3 retries)    # 跨进程排他
  on_disk = read_json('.telemetry.json')        # 可能是别的进程刚写入的最新值
  merged = rmw_merge(on_disk, snapshot)         # 详见下文
  atomic_write('.telemetry.json', merged)       # tmp + fsync + rename
release filelock
```

#### RMW 合并规则（核心反 lost-update）

合并发生在持 filelock 后、写回前。规则：

| 字段 | 合并函数 | 理由 |
|---|---|---|
| `views / uses / patches` | `on_disk.value + (snapshot.value - last_synced_value)` | 单调累计；用"自上次 flush 以来的增量"叠加磁盘已有值，**不是直接覆盖** |
| `last_view / last_use` | `max(on_disk, snapshot)`（None 视为 -∞） | 时间戳取较新者 |
| `entry_created_at` | `min(on_disk, snapshot)` | 取较早者，保留"该条目第一次出现"的真实时间 |
| `origin / shadowed` | 只由 reconcile 写；flush 不修改 | reconcile 与 bump 各管一摊（§4.2 边界规则） |
| `schema_version / updated_at` | 写入侧统一覆盖为当前进程值 | 由本进程负责 |

为支持上式"增量叠加"，内存层需追加一个不可见字段 `_last_synced_counts`，记录上次 flush 时这批 counter 的值；下次 flush 时 `(current - last_synced)` 即为本进程的真实增量，避免另一个进程的写入被覆盖。

#### bump 路径（不直接 IO）

```
def bump(name, kind):
    with self._lock:
        entry = self._entries.setdefault(name, _zero_entry())
        entry[counter_key[kind]] += 1
        entry[last_ts_key[kind]] = now_iso()
        self._dirty = True
```

bump 永远 O(1)、不触磁盘、不持 filelock；agent 主路径无 IO 阻塞。

#### flush 调度

- 每个 agent turn 结束（`runner.py` 主循环出口）触发一次 `flush()`。
- 进程退出时 `atexit` 兜底 flush。
- M1 不引入定时 flush（避免新增 background thread）；如未来需要，加在 M3 Curator 的周期任务里。

#### 失败降级

- filelock 在 200ms × 3 重试后仍失败：记 WARNING，**保留** 内存 dirty 状态（下次 flush 再合并），不丢弃 bump，不阻塞 agent。
- 原子写中途崩溃：`.tmp` 残留，无 rename，下次启动 `.telemetry.json` 仍是合法 JSON；启动期 reconcile 时若发现 `.tmp` 残留，删除即可。
- 文件损坏（JSON parse 失败）：记 WARNING + 备份到 `.telemetry.json.corrupted.<ts>` + 按"新文件"重建。

#### NFS / 容器只读层

filelock 在 NFS 上行为可疑（依赖 `flock` 语义）；本 spec 不为这些场景做特殊处理，只在 README 写明 `<workspace>` 必须本地可写。检测到锁始终拿不到：每 100 次失败合并成一次 WARN，不刷屏。

### 4.4 孤儿清理（reconcile）

启动时 `SkillsLoader` 初始化完后调用 `telemetry.reconcile(known_skills)`：

1. 已知 skill 列表来自新方法 `SkillsLoader.list_skills_with_shadows()`，返回每条 skill 的 `effective_origin` 与 `shadowed_origins`（见 §4.2 SkillEntry 定义）。
2. 遍历 telemetry `entries`：
   - 磁盘已不存在的删除；
   - 新出现的写零初值（`entry_created_at = now`，counters 全为 0）；
   - 已存在的**只**更新 `origin` 和 `shadowed`（见 §4.2 行为边界）。
3. reconcile **不**修改 views/uses/patches/last_view/last_use/entry_created_at（既有条目）——这些只由 `bump()` 路径与"新条目创建"两个时机产生。
4. 这次合并写入计入一次 flush，走与普通 flush 相同的 RMW 路径，确保即使另一进程同时启动也能 last-writer-wins 合并 origin/shadowed。

#### reconcile 与 bump 的并发约束（成文化）

| 操作 | 触碰字段 |
|---|---|
| `reconcile()` | 仅 `origin`、`shadowed`、**新条目的** `entry_created_at` |
| `bump(name, kind)` | 仅对应 counter 与 last_ts；不动 origin/shadowed |
| `flush()` RMW 合并 | counters 用增量叠加，timestamps 取 max/min，origin/shadowed 取写入侧最新值 |

> 不变量：**任何场景下，reconcile 不会让一个已经被 bump 但还没 flush 的计数器丢失。** 因为 reconcile 走的是同一个 RMW 路径，磁盘读出来的 on_disk.counter 与内存 snapshot.counter 都会保留下来。

#### bump 命中未知 name 的处理

- M1 时序：reconcile 先于第一次 bump 发生（runner 启动顺序保证），常态下不会出现"未知 name"。
- 但 M2 起 `skill_manage` 可能在 reconcile 之后创建新 skill，下一次 reconcile 之前已发生 bump。此时按 §4.2 "懒初始化"：创建 `{origin: "unknown", shadowed: [], counters: 0, entry_created_at: now}`，bump 正常生效；下次 reconcile 将 `origin` 修正为正确值。

> 注意：`list_skills_with_shadows()` 是 M1 引入的新方法，不替代现有 `list_skills()`；现有调用者不受影响。

## 5. Provenance frontmatter 字段

仅对 agent 创建的 skill 强制：

```yaml
---
name: auto-summarize
description: Summarize long web pages into 5-bullet TL;DR
metadata:
  nanobot:
    provenance:
      origin: agent
      created_at: 2026-06-09T14:22:00Z
---
```

约定：

- `origin` 当前只允许 `agent`（M1 不写入 user/builtin/hub 值）。
- `created_at` 必填 ISO8601 UTC。
- M1 仅**消费方**实现读取与展示；**生产方**（写入此字段的代码）由 M2 的 `skill_manage` 负责。
- user 若手动从 `<workspace>/skills/agent/` 移到 `<workspace>/skills/`，frontmatter 自然保留 → 形成"该 user skill 起源自 agent"的天然记录，无需额外迁移逻辑。

#### 读取路径（强制 API 形态）

消费方一律走以下规范路径，**不得**直接解析 SKILL.md：

```python
loader = SkillsLoader(workspace)
provenance = loader._get_skill_meta(name).get("provenance", {})
origin = provenance.get("origin")             # "agent" or None
created_at = provenance.get("created_at")     # ISO8601 str or None
```

理由：

- `_get_skill_meta` 已经处理了 frontmatter 解析、缓存（隐式）、`nanobot` 与 `openclaw` 命名空间兼容（见现有 `skills.py:188-205`）。
- 把读取入口压在单一函数上，未来如要加 caching 或换 frontmatter parser，只改一处。
- M1 仅这一个 reader；M2/M3 新增 reader 时同样必须经此入口（在本 spec §11 接口契约里固定）。

> 注：`_get_skill_meta` 以下划线开头属于"内部"，但在本项目当前布局下是事实上的复用入口；M1 不重构其可见性，把规范写在文档里即可。如未来要把它升为公开 API，归 M2/M3 一并处理。

## 6. Auxiliary Provider 配置

### 6.1 Schema 变更（`nanobot/config/schema.py`）

```python
class AuxiliaryConfig(Base):
    """Configuration for the auxiliary provider used by background tasks.

    M1 引入；M3 (Curator)、M4 (rubric) 实际消费。
    """
    model_preset: str | None = None  # 引用 modelPresets 中的 key；为空则 fallback 主 preset

class AgentDefaults(Base):
    ...
    auxiliary: AuxiliaryConfig = Field(default_factory=AuxiliaryConfig)
```

支持 camelCase alias（`auxiliary.modelPreset`），与项目现有约定一致。

### 6.2 工厂函数（`nanobot/providers/factory.py` 或新位置）

```python
def get_auxiliary_client(config: Config) -> ProviderClient:
    """返回辅助 provider 客户端。

    解析顺序：
    1. config.agents.defaults.auxiliary.model_preset 指向的 preset
    2. fallback：config.agents.defaults.model_preset（主 preset）

    失败行为：
    - 若 model_preset 显式配置但 modelPresets 中找不到该 key：
        raise ConfigError（这是配置错误，必须显式修）
    - 若两个 preset 都未配（极端 minimal config）：
        raise ConfigError（agent 无主模型也无 aux 模型，无法运行）
    - 正常情况：返回 ProviderClient（与主 client 同协议，可直接 send_message）
    """
```

### 6.3 配置示例

```json
{
  "modelPresets": {
    "primary": {"provider": "openrouter", "model": "anthropic/claude-opus-4.6"},
    "lite":    {"provider": "openrouter", "model": "anthropic/claude-haiku-4.5"}
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary",
      "auxiliary":   {"modelPreset": "lite"}
    }
  }
}
```

### 6.4 M1 的最小消费

M1 本身**不调用** aux client 做任何业务；配置正确性靠**纯静态校验**保证，不引入运行时 smoke-test：

- 校验下沉到 Pydantic `model_validator` 或 schema 层：加载 Config 时，若 `auxiliary.model_preset` 显式配置且其值不在 `modelPresets` keys 中，立即 `ValueError`（fail fast，与项目其他 schema 错误一致风格）。
- **不**在 gateway 启动期额外调一次 `get_auxiliary_client()` 做"探活"；这是冗余的——schema 通过即等价于"能解析 preset"。
- `get_auxiliary_client(config)` 的 runtime ConfigError 仍保留，作为 M3/M4 真正调用时的最后一道防线（例如运行时 monkey-patch 删了 preset）。
- 真正的端到端 ping（发一次最小请求）留给 M3 自己的 spec。

> 为什么不用 smoke-test：smoke-test 既不能保证后续 inference 真的能成功，也会让 gateway 启动慢于必要；schema 校验对 user 反馈更早、更准（直接指向出错字段）。

## 7. 代码改动点（文件级清单）

| 文件 | 改动 | 风险等级 |
|---|---|---|
| `nanobot/agent/skills.py` | (a) `_skill_entries_from_dir` 支持识别并跳过 `agent/` 子目录条目（避免它被当成名为 `agent` 的 skill）；(b) 新增 `_entries_from_agent_dir()`；(c) `list_skills()` 三源合并 + collision 检测 + warning（**只此函数内做 collision 检测，不挂 telemetry hook**）；(d) 在 `build_skills_summary()` 的 agent-context 调用路径 hook `bump(name, "view")`；(e) 在 `load_skills_for_context()` hook `bump(name, "use")`；(f) 新增 `list_skills_with_shadows()` 方法（见 §4.2） | 中（核心加载路径） |
| `nanobot/agent/skills_telemetry.py` *(新)* | `SkillTelemetry` 类：`reconcile / bump(name, kind) / snapshot / flush`；filelock + threading.Lock + RMW 合并 + 原子写 | 低（独立新模块） |
| `nanobot/agent/subagent.py` *(行 362 附近)* | **子 agent 也会构造 SkillsLoader**：复用主进程注入的 SkillTelemetry（通过参数传入或单例 helper），不要在 subagent 里再 new 一个 telemetry，避免 lock 双开 / 计数器分裂 | 低-中（要从 caller 传递依赖） |
| `nanobot/webui/skills_api.py` *(行 17, 32)* | WebUI 列表查询走 `SkillsLoader.list_skills()`，**绝不**触发 bump。给 SkillsLoader 增加显式构造参数 `telemetry: SkillTelemetry \| None = None`；WebUI 构造时传 `None`，agent runtime 构造时传真实 telemetry。这是"不在 list_skills 内挂 hook"的物理保证 | 中（接口收紧） |
| `nanobot/config/schema.py` | `AuxiliaryConfig` 类 + `AgentDefaults.auxiliary` 字段 + camelCase alias + `model_validator` 校验 preset key 存在 | 低 |
| `nanobot/providers/factory.py` | `get_auxiliary_client(config)` 工厂 + fallback 逻辑（factory.py 负责实例化，与现职责一致） | 低 |
| `nanobot/agent/loop.py` 或 `runner.py` | SkillsLoader 构造时注入 telemetry；主 turn 出口处调用 `telemetry.flush()`；进程退出 `atexit.register(telemetry.flush)` | 低（一行级钩入） |
| `pyproject.toml` | 无需改动（`filelock>=3.25.2` 已在依赖中） | — |
| `tests/agent/test_skills_telemetry.py` *(新)* | 并发 bump、孤儿清理、collision、原子写、锁失败降级、RMW 合并、reconcile 边界、bump 未知 name 容忍 | — |
| `tests/agent/test_skills_loader.py` 扩展 | 三源优先级、collision warning 一次性、`list_skills_with_shadows()` 形态、`disabled_skills` 过滤、`list_skills()` 不触发 bump | — |
| `tests/config/test_schema.py` 扩展 | `auxiliary.modelPreset` 解析、camelCase、fallback、preset 不存在时 schema 校验失败 | — |
| `tests/providers/test_factory.py` 扩展（或新增） | `get_auxiliary_client()` 解析 + fallback + 运行时 ConfigError | — |
| `tests/agent/test_subagent_telemetry.py` *(新)* | 子 agent 复用主 telemetry 单例；子 agent 内 bump 经一次 flush 后主磁盘可见且不分裂 | — |
| `tests/webui/test_skills_api.py` 扩展 | WebUI 调用 `list_skills()` N 次后 telemetry counter 仍为 0（物理验证 hook 没误挂） | — |

#### Hook 挂载位置硬性约束（在此固定，防止后续偏移）

| 函数 | 是否挂 bump | 原因 |
|---|---|---|
| `SkillsLoader.list_skills()` | **永不** | WebUI、CLI、subagent 列表查询都走这条；不能让"看一眼列表"也涨 view |
| `SkillsLoader.list_skills_with_shadows()` | **永不** | reconcile 专用；与 agent 上下文无关 |
| `SkillsLoader.build_skills_summary(...)` 由 **agent runtime** 调用 | bump view | 仅当 caller 是 agent 主 prompt 构建路径时；判定靠"loader 实例是否带 telemetry"（webui 构造的 loader 传 None，自然不挂） |
| `SkillsLoader.load_skills_for_context(...)` | bump use | 内容真正注入 prompt |
| `SkillsLoader.load_skill(...)` | **永不** | 独立读取入口，可能被 `_get_skill_meta` 等内部路径递归调用 |

## 8. 测试与验收标准

### 8.1 单元测试

- [ ] `SkillTelemetry.bump(name, "view"|"use"|"patch")` 三类事件分别更新对应字段，互不串
- [ ] 多线程并发 `bump()` 计数无丢失（10 线程 × 1000 次 × 3 kinds）
- [ ] **asyncio 并发**：100 个 coroutine 同时 `bump()`，串行 `flush()` 后磁盘 counter == 100（验证 threading.Lock 在 asyncio 下也安全）
- [ ] **多进程 RMW**：fork 两个进程各 bump 500 次后串行 flush，磁盘最终 counter == 1000（验证增量叠加合并，不丢失）
- [ ] 锁竞争超时后 WARN 但不抛；脏标志保留，下次 flush 仍能写入
- [ ] 原子写：mock 写入中途崩溃（rename 前 raise），下次启动文件仍可解析；`.tmp` 残留被 reconcile 清理
- [ ] 孤儿清理：磁盘删除一个 skill 后，下次 `reconcile()` 该条目消失
- [ ] 新 skill 出现时 `entry_created_at = now`，旧 skill `entry_created_at` 不变
- [ ] **reconcile 不动 counters**：手工写一个 `views=42` 的条目，跑 reconcile，磁盘 `views` 仍为 42
- [ ] **bump 未知 name 容忍**：reconcile 之前 bump 未注册 skill，懒初始化条目，`origin="unknown"`
- [ ] **`list_skills()` 不触发 bump**：构造无 telemetry 的 SkillsLoader，反复调 `list_skills()`，磁盘 telemetry 不变
- [ ] Collision 检测：三源同名 skill 启动时仅 WARN 一次（验证 caplog 行数）
- [ ] Frontmatter `nanobot.provenance` 解析正确（走 `_get_skill_meta(name).get('provenance', {})` 路径）；缺失时返回空 dict（不报错）
- [ ] `AuxiliaryConfig.model_preset` 未配置时 `get_auxiliary_client()` 返回主 preset 的 client
- [ ] `AuxiliaryConfig` camelCase alias `modelPreset` 解析正确
- [ ] **Schema 校验失败**：`auxiliary.modelPreset = "nonexistent"` 时 `Config.model_validate` raise，错误指向该字段
- [ ] **Schema_version 演进**：写 `schema_version=2` + 未知字段 `entries[x].extra="X"` 的 telemetry 文件，读取 + flush 后未知字段仍在
- [ ] **损坏文件容忍**：写一个非法 JSON 的 telemetry 文件，启动 → WARN + 备份 + 重建

### 8.2 集成测试

- [ ] 全新 workspace 启动 → mock provider 跑一轮 agent 对话 → `.telemetry.json` 出现且 `views > 0`
- [ ] 已有 workspace（有 user skills 但无 `agent/` 目录）启动 → 不报错 + telemetry 为现有 user skill 创建零计数条目
- [ ] 显式配 `auxiliary.modelPreset` 指向 `lite` preset → `get_auxiliary_client()` 返回的 client 模型字段与 `lite.model` 匹配
- [ ] **子 agent 复用主 telemetry**：mock 一个 subagent.spawn 调用，子 agent 内 `bump("foo", "use")` 后主进程 `flush()`，磁盘 `foo.uses == 1`，不出现重复条目
- [ ] **WebUI 旁路**：WebUI 调用 `list_skills()` 10 次后，与 agent runtime 在同一 workspace 共存，telemetry 仅记录 agent 真实触发的事件

### 8.3 验收门

- [ ] 全部单元 + 集成测试通过
- [ ] `ruff check nanobot/` 零 warning
- [ ] **Mock provider** 集成测试中 `.telemetry.json` 数据合理（`views ≥ uses`，`uses` 与实际触发 skill 数对得上）
- [ ] 设计 spec（本文）+ 实施 plan 都已 commit
- [ ] `roadmap.md` 中 M1 状态切换为"已完成"，并追加 200–500 字回顾笔记

### 8.4 人工验证清单（可选，落地 M1 后做一次）

> 这些验证靠真实 LLM 调用做端到端 sanity check，**不计入自动化门禁**（避免给 CI 引入 LLM 依赖与成本）。

- [ ] 在本地 `~/.nanobot/config.json` 配 primary + auxiliary（两个不同 preset）；启动 gateway，跑一段对话；观察 `.telemetry.json`：counter 单调递增、`updated_at` 刷新、原子写无 `.tmp` 残留。
- [ ] 手工把一条 telemetry entry 的 `origin` 改成 `"agent"`（用编辑器），重启进程，验证 reconcile 把它纠正回真实值。
- [ ] 同一 workspace 起两个 gateway 进程（不同端口），各自跑对话；killall 后检查 telemetry counter 总和合理。

## 9. 决策日志

| # | 日期 | 决策 | 选项 | 理由（简） |
|---|---|---|---|---|
| 1 | 2026-06-11 | agent skill 物理位置 | `<workspace>/skills/agent/` 子目录 | 物理隔离，Curator 默认只在该目录操作，user skill 永远安全 |
| 2 | 2026-06-11 | 同名加载策略 | user > agent > builtin + 启动 WARNING | 现有覆盖语义自然延伸 + 可观测性 |
| 3 | 2026-06-11 | telemetry 存储 | 独立 `.telemetry.json` + filelock | skill 文件保持干净，git diff 噪声小 |
| 4 | 2026-06-11 | provenance 字段 | 仅 agent-authored 写 frontmatter | YAGNI；二元判定零歧义；失败模式安全 |
| 5 | 2026-06-11 | aux provider 形态 | `auxiliary.modelPreset` 引用现有 preset | 复用 modelPresets，零新概念，向后兼容 |
| 6 | 2026-06-11 | telemetry schema 字段 | `origin/shadowed/views/uses/patches/first_seen/last_view/last_use` | `origin` 冗余存避免 join；`patches` M1 预留 |
| 7 | 2026-06-11 | 更新时机 | views @ summary，uses @ load_for_context | 区分"被看见"和"被使用"，给 Curator 提供两类信号 |
| 8 | 2026-06-11 | 并发策略 | filelock + 内存累积 + turn 出口 flush + atexit 兜底 | telemetry 非关键路径，可降级 |
| 9 | 2026-06-11 | 孤儿清理时机 | 启动期 reconcile，一次写入 | 简单，启动一次性成本 |
| 10 | 2026-06-11 | 重名 warning | loguru WARNING，每次启动只打一次 | 可观测但不刷屏 |
| 11 | 2026-06-11 | `/curator` 命令骨架 | M1 不含，留给 M3 | milestone 边界清晰 |
| 12 | 2026-06-11 | M1 整体取向 | Approach B（schema + 读侧最小行为） | 地基自己被踩起来，可端到端验证；不拽 command UX 进 M1 |
| 13 | 2026-06-11 | 术语二元性处理 | 现有 `source=workspace/builtin` 保留为内部历史命名；对外/telemetry/provenance 一律用 `origin=user/agent/builtin`；§3.1 强制映射表 | 不重命名现有字段避免大改；新代码统一新词汇 |
| 14 | 2026-06-11 | 并发模型 | 内存 `threading.Lock` + 进程间 `filelock` + 持锁 RMW 合并（增量叠加，非覆盖） | 单层 filelock 无法防同进程多协程；单层 threading.Lock 无法防多进程；RMW 防 lost-update |
| 15 | 2026-06-11 | bump API 形态 | `bump(name, kind)` 单入口 + `Literal["view","use","patch"]`；废弃 `bump_views/uses/patches` 三入口设计 | 统一加锁路径；新增 kind 不扩 API 表面 |
| 16 | 2026-06-11 | reconcile 与 bump 边界 | reconcile 只动 `origin/shadowed/(新条目)entry_created_at`；不动 counters/timestamps | 避免"reconcile 把未 flush 的计数清零"竞态 |
| 17 | 2026-06-11 | `first_seen` 字段命名 | 改名为 `entry_created_at` | `first_seen` 语义易误读为"skill 在磁盘上的诞生时间"；实际是"telemetry 给该条目建账的时间" |
| 18 | 2026-06-11 | `views` 计数范围 | **只**在 agent 主 prompt 构建路径上计；WebUI/CLI 列表查询不计 | WebUI 查询不代表 agent"看见"了 skill；混算会污染 Curator 决策 |
| 19 | 2026-06-11 | aux provider 校验时机 | 下沉到 Pydantic `model_validator`；移除启动期 smoke-test | schema 校验更早、更准；smoke-test 既不保证 inference 成功也拖慢启动 |
| 20 | 2026-06-11 | SkillsLoader 注入 telemetry | SkillsLoader 增加 `telemetry: SkillTelemetry \| None = None` 构造参数；WebUI 传 None | 物理上保证 list_skills 不挂 hook；hook 不靠 caller 自觉 |
| 21 | 2026-06-11 | 子 agent telemetry | subagent 复用主进程注入的 telemetry 单例，不在子 agent 里重新构造 | 避免双重 lock 与计数器分裂 |

## 10. 风险与回滚

### 10.1 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 修改 `SkillsLoader.list_skills()` 引入回归（影响现有 skill 装载） | 中 | 充分单元测试 + 集成测试；保留旧入口 `_skill_entries_from_dir` 行为不变，新功能走新方法 |
| filelock 在某些文件系统（NFS、容器只读层）行为异常 | 低-中 | 文档明确 `<workspace>` 必须可读写；锁失败降级仅 WARN，不阻断 |
| 异步 flush 队列在进程异常时丢失最近 N 次 bump | 低 | telemetry 是观察数据，少量丢失可接受；atexit 兜底；Curator (M3) 不依赖完美计数 |
| `auxiliary.modelPreset` 引用了不存在的 preset | 低 | 启动期 smoke-test 检测 + WARN；运行时调用 `get_auxiliary_client()` 时再校验一次 |
| 现有 user 已有名为 `agent` 的 skill（即 `<workspace>/skills/agent/SKILL.md` 已存在，把 agent 目录占用为一个普通 skill） | 低 | 启动期 `SkillsLoader.__init__` 检测：若该路径存在，记 ERROR 提示 user 手动迁移（建议重命名为如 `agent-helper`），并跳过将该目录作为 agent-source 收纳；user skill 本身仍可被加载，但 agent-source 视为空，直到 user 处理冲突 |
| **术语二元性引入新代码与旧代码混用 `source`/`origin` 误用** | 中 | §3.1 强制映射表 + ruff 自定义检查（如可行）+ code review checklist：新代码出现 `"workspace"` 字面量必须审视；现有 `source` 字段在 PR diff 中触碰时一并审视 |
| **多进程同时 flush 引发 lost update** | 中 | filelock + RMW 增量叠加（§4.3）；多进程并发单元测试兜底（§8.1） |
| **subagent 重复构造 SkillsLoader/SkillTelemetry 导致 lock 双开** | 中 | §7 改动表明确 subagent.py 复用注入方案；集成测试覆盖（§8.2） |

### 10.2 回滚

M1 改动全部为**新增**或**附加 hook**，无破坏性修改：

- `.telemetry.json` 文件删了重启会重建。
- `<workspace>/skills/agent/` 目录删了不影响 user/builtin skill。
- `auxiliary.modelPreset` 配置删了自动 fallback。
- 单独 revert M1 的 commit（一个分支、一次 PR）即可完全回到 M1 前状态。

## 11. 与下游 milestone 的接口契约

为减少 M2/M3/M4 启动时的耦合改动，M1 必须**对外稳定**以下接口：

| 接口 | 消费者 | 稳定形式 |
|---|---|---|
| `SkillTelemetry.bump(name, "patch")` | M2 `skill_manage` 工具 | M1 已完整实现（累加计数 + 落盘 + 懒初始化未知 name），M1 内无调用方；M2 调用同一入口，不另起 `bump_patches` |
| `SkillTelemetry.snapshot()` | M3 Curator Phase 1（确定性状态机） | 返回不可变深拷贝 dict，M3 据此做 active/stale/archive 判断；snapshot 形态遵守 §4.1 字段表 |
| `SkillsLoader.list_skills_with_shadows()` | M3 Curator（判断同名/影子情况） | 返回 `SkillEntry` TypedDict 列表；`effective_origin` / `shadowed_origins` 命名稳定 |
| `nanobot.provenance.origin == "agent"` 检测 | M3 Curator | M1 已保证字段存在与否的语义 |
| **Provenance 读取入口** `loader._get_skill_meta(name).get("provenance", {})` | M3 Curator、未来 CLI/WebUI | 任何消费方必须经此入口，**不得**直接解析 frontmatter；如未来要把 `_get_skill_meta` 升为公开 API，由 M2/M3 改动 |
| `get_auxiliary_client(config)` | M3 Curator Phase 2、M4 LLM-as-judge | M1 已提供，M3/M4 不需再做工厂；schema 校验保证 `model_preset` 可解析 |
| `<workspace>/skills/agent/` 目录可写 | M2 `skill_manage` | M1 不强制创建，但保证 SkillsLoader 容忍其存在/不存在 |
| **Telemetry schema_version 演进** | 未来所有版本 | 读取侧透传未知字段；写入侧只升不降；变更须在本 spec §9 + 新 milestone spec 决策日志各落一行 |
| **`bump()` 调用语义** | M2/M3/M4 | 调用方负责传 `Literal["view","use","patch"]` 之一；不在调用方做"先 ensure 条目再 bump"——telemetry 内部懒初始化 |

## 12. 完工后该追加到 roadmap 的内容

完成 M1 时，需在 [`docs/hermes-evolution/roadmap.md`](../roadmap.md) 做：

1. § 3 表格中 M1 状态 → "已完成"，填入 plan 路径
2. § 5 回顾段落 M1 项追加 200–500 字回顾（实际偏差、坑、对 M2/M3/M4 的影响）
3. § 7 "当前位置" 勾选第 3 项
