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
2. **SkillsLoader 三源支持**：原有 `workspace / builtin` 两源（注：`SkillsLoader.source` 字段历史命名，保留两值不变以兼容现有 WebUI 等消费方）在概念层扩展为三源 `user / agent / builtin`，加载优先级 user > agent > builtin，启动期对同名 collision 打 WARNING。新增 `list_skills_with_shadows()` 方法（M1 由 telemetry reconcile 消费；同时构成 M3 Curator 判断同名/影子的稳定接口，见 §11）。术语映射见 [§3.1](#31-术语映射)。
3. **Telemetry 子系统**：新增 `<workspace>/skills/.telemetry.json`、`SkillTelemetry` 辅助类、双层锁（内存 `threading.Lock` + 进程间 `filelock`）+ 持锁 RMW 增量叠加合并（多进程反 lost-update）、孤儿清理、view/use/patch 计数 hook（统一 `bump(name, kind)` 单入口；`patch` kind M1 不调用）。
4. **Provenance frontmatter 字段**：仅在 agent 创建 skill 时写入 `nanobot.provenance: {origin: agent, created_at: ISO8601}`，其他来源 skill 不强制。读取路径明确为 `_get_skill_meta(name).get('provenance', {})`。
5. **Auxiliary provider 配置**：在 `agents.defaults.auxiliary.modelPreset` 引入一个引用现有 `modelPresets` key 的配置项；新增 `get_auxiliary_client()` 工厂；未配置时 fallback 到主 preset。配置层校验（preset key 是否存在）下沉到 schema validator，不做运行时 smoke-test。
6. **SkillsLoader 计数挂钩**：物理位置——bump 调用**写在 `SkillsLoader.build_skills_summary()` / `load_skills_for_context()` 函数体内**（不在 runner caller 侧），统一 gated on `if self.telemetry is not None`；`SkillsLoader.__init__` 增加 `telemetry: SkillTelemetry | None = None` 参数；**WebUI 路径构造 SkillsLoader 时一律传 `telemetry=None`，agent runtime 构造时传真实 telemetry**——这是"WebUI 不污染计数"的物理保证（而非靠 caller 自觉）。`list_skills()` / `list_skills_with_shadows()` / `load_skill()` 内**永不**挂 hook（详见 §7 hook 位置硬性约束表）。每个 agent turn 出口同步 `flush()`，进程退出 `atexit` 兜底。
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

| 概念维度 | 现有代码字段（保留） | 取值集 | 新代码/对外字段 | 取值集 | 备注 |
|---|---|---|---|---|---|
| skill 的物理来源（旧） | `SkillsLoader._skill_entries_from_dir(..., source=...)` 与 `list_skills()` 返回 entry 的 `source` 键 | `"workspace"` / `"builtin"`（保持 2 值不变，**WebUI / CLI 现有消费方零兼容性破坏**） | — | — | `_entries_from_agent_dir()` 仍向 `entry["source"]` 写入 `"workspace"`（agent 子目录是 workspace 的一部分） |
| skill 的物理来源（新） | — | — | `entry["origin"]`（telemetry / `list_skills_with_shadows()` 返回的 `SkillEntry.effective_origin`） / `metadata.nanobot.provenance.origin`（frontmatter） | `"user"` / `"agent"` / `"builtin"` | 三值取值通过物理路径推断：`<workspace>/skills/agent/*` → `"agent"`；`<workspace>/skills/*`（不含 agent/）→ `"user"`；`nanobot/skills/*` → `"builtin"` |

**强制规则：**

- `SkillsLoader.source` / `_skill_entries_from_dir(source=...)` 等历史字段名因兼容性**保留 2 值不变**（防止 WebUI `nanobot/webui/skills_api.py:20,51` 等现有消费方破坏）。
- **新代码一律不写入或读取 `source` 字面值**，对外只走 `origin`。
- M1 新增的 `list_skills_with_shadows()` 返回 `SkillEntry` 必须用 `effective_origin / shadowed_origins` 命名（即 `origin` 命名空间），不得回写 `source`。
- Telemetry 内部仅按 `origin` 三值（`user/agent/builtin`）键存储，**不出现 `workspace` 字面量**。
- 文档与日志：面向用户与未来 agent 的所有输出（warning、CLI、注释、说明）一律用 `user/agent/builtin`。
- 推断器只能放一个地方：`SkillsLoader._infer_origin_from_path(path) -> Literal["user","agent","builtin"]`，所有新代码必须复用。

> 即：`SkillsLoader.source` 字段内部仍是 2 值（`workspace/builtin`），它和"3 值 origin"在内存里**并存但不混用**。`list_skills()` 返回未变（仍是 `source` 键），`list_skills_with_shadows()` 是全新方法返回 `effective_origin`。两套词汇隔离，互不污染。

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

#### 写入流程（`flush()` — 完整伪代码）

```
def flush(writer="bump"):  # writer ∈ {"bump", "reconcile"}, 决定 origin/shadowed 合并规则
    # ---- 阶段 1：内存层快照 ----
    with self._lock:
        if not self._dirty:
            return
        snapshot = deep_copy(self._entries)            # 含 origin/shadowed/counters/ts
        last_synced_snapshot = deep_copy(self._last_synced_counts)
        # 注意：此时 NOT 清 _dirty，也 NOT 改 _last_synced_counts；
        # 后续磁盘写入成功后才能"确认"，否则失败回滚时不会丢任何 bump

    # ---- 阶段 2：跨进程排他 + RMW + 原子写 ----
    try:
        with filelock.FileLock(LOCK_PATH, timeout=0.2):  # 重试见下文失败降级
            on_disk = safe_read_json(TELEMETRY_PATH)     # 损坏 → 重建空结构
            merged  = rmw_merge(on_disk, snapshot, last_synced_snapshot, writer)
            atomic_write(TELEMETRY_PATH, merged)         # tmp + fsync(tmp) + rename + fsync(dir)
    except LockTimeout:
        warn_throttled("filelock contention", ...)
        return    # 保留 _dirty=True、保留 _last_synced_counts 不变；下次 flush 再试

    # ---- 阶段 3：写盘成功后才确认（在 threading.Lock 内做差额结算）----
    with self._lock:
        # 把 snapshot 时刻已结算的计数刻入 _last_synced_counts；
        # snapshot 之后到此刻之间到达的 bump 仍在 self._entries 内，将进入下次 flush
        for name, entry in snapshot.items():
            slot = self._last_synced_counts.setdefault(name, {"views": 0, "uses": 0, "patches": 0})
            for k in ("views", "uses", "patches"):
                slot[k] = entry[k]
        # 如果阶段 1 到此刻之间没有新 bump，则 _entries 与 snapshot 等价 → 清 _dirty；
        # 否则保留 _dirty=True（已被新 bump 设回了 True）
        if self._entries == snapshot:
            self._dirty = False
```

**为什么 `_last_synced_counts` 的写在阶段 3 而不是阶段 1：**

- 若放阶段 1（snapshot 时立刻把 `_last_synced = snapshot`），filelock 拿不到导致回滚时，磁盘没写、`_last_synced` 却前进，下次 flush 算出 `current - last_synced = 0` 的负差额 → 真的丢计数。
- 阶段 3 在原子写 rename 成功 *之后* 才推进 `_last_synced`，写失败则 `_last_synced` 不变，下次 flush 重做完整差额。

#### RMW 合并规则（核心反 lost-update）

合并发生在持 filelock 后、写回前。`rmw_merge(on_disk, snapshot, last_synced, writer)` 按字段：

| 字段 | 合并函数 | 理由 |
|---|---|---|
| `views / uses / patches`（entry 在 on_disk 与 snapshot 都存在） | `on_disk.value + max(snapshot.value - last_synced.get(name, 0), 0)` | 单调累计；用"自上次 flush 以来的增量"叠加磁盘已有值。`max(.., 0)` 兜底 corruption-rebuild 后 `last_synced` 偏大导致负差额 |
| `views / uses / patches`（entry 仅在 snapshot — 已被别进程 reconcile 当孤儿删了） | **不复活**：直接跳过该 entry，相当于本进程承认 reconcile 的删除决定；同时从 `self._last_synced_counts` 移除（下次 flush 不再算差额） | 防止 flush 与 reconcile 互相抢救；reconcile 是地基层，bump 不许越权 |
| `views / uses / patches`（entry 仅在 on_disk — snapshot 没动它） | 保持 `on_disk` 原值，不写 | 别进程在管它 |
| `last_view / last_use` | `max(on_disk, snapshot)`（None 视为 -∞；未知 vs 已知，已知胜） | 时间戳取较新者 |
| `entry_created_at` | `min(on_disk, snapshot)`（None 视为 +∞） | 取较早者，保留"该条目第一次出现"的真实时间 |
| `origin / shadowed`（entry 在 on_disk 不存在） | 用 snapshot 的值；这是该 entry 首次落盘 | 新增条目必须带 origin |
| `origin / shadowed`（entry 都存在 且 `writer == "reconcile"`） | snapshot 胜（reconcile 是 origin/shadowed 的唯一权威写者） | 决策 #16 |
| `origin / shadowed`（entry 都存在 且 `writer == "bump"` 且 `snapshot.origin == "unknown"`） | 保留 on_disk（不要用"unknown"覆盖别进程刚 reconcile 出来的真实值） | 防止懒初始化覆盖正确值 |
| `origin / shadowed`（entry 都存在 且 `writer == "bump"` 且 `snapshot.origin != "unknown"`） | 保留 on_disk（bump 永不改 origin/shadowed） | 决策 #16；最严格的"flush 不动 origin"诠释 |
| `schema_version` | 写入侧统一覆盖为当前进程值（且 ≥ on_disk.schema_version） | 只升不降；§4.1 演进规则 |
| `updated_at` | 写入侧统一覆盖为当前进程 `now_iso()` | 由本进程负责 |

#### `_last_synced_counts` 字段定义与生命周期

```python
self._last_synced_counts: dict[str, dict[str, int]] = {}
# 形如 {"summarize": {"views": 142, "uses": 38, "patches": 0}, ...}
# 含义：上一次 flush 成功 rename 后，"我们这个进程"已经把这些计数贡献给磁盘的累计值
```

生命周期事件：

| 事件 | `_last_synced_counts` 变化 |
|---|---|
| `__init__` | 初始化为空 dict |
| 第一次 `flush()` 成功后（阶段 3） | 为 snapshot 中每个 entry 写入 `views/uses/patches` 三键 |
| 后续 `flush()` 成功后（阶段 3） | 同上，覆盖式更新 |
| `flush()` filelock 失败 / 写盘失败 | **不变**（关键反丢失） |
| RMW 合并发现 entry 被 reconcile 当孤儿删了（仅在 on_disk 不存在） | 该 entry 从 `_last_synced_counts` 移除 |
| 启动时检测到 `.telemetry.json` 损坏并重建 | 清空 `_last_synced_counts` 为 `{}`（与新文件起点对齐；R1 case 4） |
| `corrupted.<ts>` 备份完成后下一次 `flush()` | 阶段 3 重建 `_last_synced_counts`，全量差额一次性落盘 |

不变量：**`flush()` 成功返回前后，`_last_synced_counts[name][kind] ≤ on_disk[name][kind]`**。任何违反都意味着 RMW 合并算出负数，必须靠 `max(.., 0)` 兜底并 WARN。

#### bump 路径（不直接 IO）

```
def bump(name, kind):
    with self._lock:
        entry = self._entries.setdefault(name, _zero_entry_with_unknown_origin())
        entry[counter_key[kind]] += 1
        entry[last_ts_key[kind]] = now_iso()
        self._dirty = True             # 即使 flush 正在阶段 2 也要置 True
```

bump 永远 O(1)、不触磁盘、不持 filelock；agent 主路径无 IO 阻塞。

#### 并发 bump 与 flush 的时序保证（避坑说明）

flush 阶段 1 释放 `self._lock` 后、阶段 3 重新获取之前，可能有新的 bump 到达：

- 新 bump 在 `self._lock` 内 `_dirty = True` → 阶段 3 看到 `_entries != snapshot` → 保留 `_dirty=True`。
- 这些 bump 的计数增量将在 **下一次 flush** 落盘（延迟一个 flush 周期）；M1 接受这个延迟（telemetry 非关键路径）。
- 阶段 2 的 RMW 用阶段 1 抓的 snapshot；新 bump 不会被错误计入这次 RMW 的差额（`_last_synced_counts` 阶段 3 才推进到 snapshot 值，新 bump 高于该值，下次 flush 算差额正常 +N）。

**关键不变量**：bump 永不丢失，但**可见性最多延迟一个 flush 周期**。

#### 原子写细节

`atomic_write(path, data)` 必须按顺序：
1. 写入 `<path>.tmp`；
2. `fsync(tmp_fd)`（数据落盘）；
3. `os.rename(tmp_path, path)`（原子替换）；
4. `fsync(parent_dir_fd)`（POSIX：rename 元数据落盘）。

第 4 步是低概率掉电场景下保证 rename 持久化的必要 step；遗漏会导致掉电后 `path` 与 `<path>.tmp` 都可能消失。Windows 上 fsync 目录无操作，跳过即可（`os.fsync` on dir-fd 仅 POSIX）。

#### flush 调度

- 每个 agent turn 结束（`runner.py` 主循环出口）触发一次 `flush()`。
- 进程退出时 `atexit` 兜底 flush。
- M1 不引入定时 flush（避免新增 background thread）；如未来需要，加在 M3 Curator 的周期任务里。

#### 失败降级（统一策略）

- **filelock 超时**：200ms × 3 重试后仍失败 → WARN（按下文节流），保留 `_dirty=True` 与 `_last_synced_counts` 不变，**不丢弃 bump，不阻塞 agent**。
- **原子写中途崩溃**：`.tmp` 残留，无 rename，下次启动 `.telemetry.json` 仍是合法 JSON；启动期 reconcile 前清理 `.tmp` 残留。
- **文件损坏（JSON parse 失败）**：WARN + 备份到 `.telemetry.json.corrupted.<ts>` + 按"新文件"重建 + 清空 `_last_synced_counts`（详见 §4.3 生命周期表）。
- **WARN 节流**：所有 filelock 与原子写失败 WARN 走同一节流器——**每 100 次失败合并成一次 WARN 输出**，避免高负载下日志刷屏。该策略不仅适用于 NFS / 容器只读层，也适用于正常 contention 下的多进程争抢。

#### NFS / 容器只读层（已知限制）

filelock 在 NFS 上行为可疑（依赖 `flock` 语义）；本 spec 不为这些场景做特殊处理。要求：

- `<workspace>` 必须位于本地可写文件系统（详见项目 `README.md` 中 M1 完工后新增的 "Workspace requirements" 段，见 §12 完工清单）。
- 检测不到锁的环境（NFS、Docker readonly-rootfs）：触发上文 WARN 节流策略，agent 主流程不阻塞。

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

| 操作 | 触碰字段 | flush 时 writer 标记 |
|---|---|---|
| `reconcile()` | 仅 `origin`、`shadowed`、**新条目的** `entry_created_at` | `writer="reconcile"`（origin/shadowed 写入侧胜，见 §4.3 RMW 表） |
| `bump(name, kind)` | 仅对应 counter 与 last_ts；不动 origin/shadowed | `writer="bump"`（origin/shadowed 保留 on_disk，"unknown" 永不覆盖真实值） |
| `flush()` RMW 合并 | counters 用增量叠加，timestamps 取 max/min，origin/shadowed 按 `writer` 标记分支 | — |

> 不变量 1：**reconcile 不会让一个已经被 bump 但还没 flush 的计数器丢失**——因为 reconcile 走同一 RMW 路径，磁盘 `on_disk.counter` 与内存 `snapshot.counter` 都会以"自上次 flush 以来的增量"形式保留。
>
> 不变量 2：**bump 的懒初始化 `origin="unknown"` 永远不会覆盖磁盘上已存在的真实 origin**——因为 §4.3 RMW 表对 `writer="bump"` 分支硬性规定保留 `on_disk.origin`。
>
> 不变量 3：**reconcile 决定删除的孤儿条目，flush 不会复活**——因为 §4.3 RMW 表对"entry 仅在 snapshot"分支硬性规定跳过并从 `_last_synced_counts` 移除。

#### bump 命中未知 name 的处理

- M1 时序：reconcile 先于第一次 bump 发生（runner 启动顺序保证），常态下不会出现"未知 name"。
- 但 M2 起 `skill_manage` 可能在 reconcile 之后创建新 skill，下一次 reconcile 之前已发生 bump。此时按 §4.2 "懒初始化"：创建 `{origin: "unknown", shadowed: [], counters: 0, entry_created_at: now}`，bump 正常生效；下次 reconcile 将 `origin` 修正为正确值。

#### 与 `disabled_skills` 的交互（明确语义）

`SkillsLoader.disabled_skills` 是 user 主动关闭的 skill 集合。M1 规定：

- **disabled skill 不出现在 `list_skills_with_shadows()` 返回里**（§4.2 已规定）；
- **reconcile 不会把 disabled skill 的 telemetry entry 当孤儿删除**（即使其物理文件存在）；
- **reconcile 不会更新 disabled skill entry 的 `origin / shadowed`**（因为它没在已知列表里）；
- 即：disabled skill 的 telemetry entry 处于"**冻结**"状态——既不删、也不动 origin、bump 路径也不会主动触它（agent 不会注入 disabled skill 到 prompt，因此没有 view/use 事件）；
- 一旦 user 把 skill 从 `disabled_skills` 里拿出来，下次 reconcile 即正常恢复处理。

实现方式：reconcile 先取 `list_skills_with_shadows()` 得到"已知活跃 skill 集" `K_active`；再取 `disabled_skills` 集合 `K_disabled`；遍历 telemetry entries 时**只对 `name ∉ K_active ∪ K_disabled` 视作孤儿删除**。

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

### 6.2 工厂函数（`nanobot/providers/factory.py`）

```python
def get_auxiliary_client(config: Config) -> LLMProvider:
    """返回辅助 provider 客户端，复用现有 `make_provider(config, preset_name=...)`。

    解析顺序：
    1. config.agents.defaults.auxiliary.model_preset 指向的 preset
    2. fallback：config.agents.defaults.model_preset（主 preset）

    失败行为：
    - 若 auxiliary.model_preset 显式配置但 modelPresets 中找不到该 key：
        由 §6.1 的 Pydantic `model_validator` 在 Config 加载期 raise ValueError（fail fast）
    - 运行时调用 `get_auxiliary_client` 时如果两个 preset 都未配（极端 minimal config 或 monkey-patch）：
        raise ConfigError（agent 无主模型也无 aux 模型，无法运行）
    - 正常情况：返回 `LLMProvider`（与主 provider 完全同类型，可走相同 stream/invoke API）
    """
```

> 返回类型 `LLMProvider` 与 `factory.make_provider()` 保持一致（见 `nanobot/providers/factory.py:141`），M3/M4 消费方按 `LLMProvider` 类型注解使用，**不引入新的 ProviderClient 抽象**。

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
| `nanobot/agent/skills.py` | (a) `_skill_entries_from_dir` 支持识别并跳过 `agent/` 子目录条目（避免它被当成名为 `agent` 的 skill）；(b) 新增 `_entries_from_agent_dir()`（向 `entry["source"]` 写入 `"workspace"`，保持现有 source 字段语义，详见 §3.1）；(c) `list_skills()` 三源合并 + collision 检测 + warning（**只此函数内做 collision 检测，不挂 telemetry hook**）；(d) 在 `build_skills_summary()` 函数体循环末尾 `if self.telemetry is not None: self.telemetry.bump(name, "view")`；(e) 在 `load_skills_for_context()` 函数体每条 load 成功后 `if self.telemetry is not None: self.telemetry.bump(name, "use")`；(f) 新增 `list_skills_with_shadows()` 方法（见 §4.2）；(g) 新增 `_infer_origin_from_path(path) -> Literal["user","agent","builtin"]` 推断器（§3.1 强制规则）；(h) `__init__` 增加 `telemetry: SkillTelemetry \| None = None` 参数；(i) **保留** `_get_skill_meta(name)` 签名稳定，在源码上方添加注释：`# NOTE: M1 spec elevates this to a contract (provenance read entry); keep signature stable, see docs/hermes-evolution/specs/m1-foundations.md §5/§11` | 中（核心加载路径） |
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

| 函数 | 是否挂 bump | 物理位置 | 原因 |
|---|---|---|---|
| `SkillsLoader.list_skills()` | **永不** | — | WebUI、CLI、subagent 列表查询都走这条；不能让"看一眼列表"也涨 view |
| `SkillsLoader.list_skills_with_shadows()` | **永不** | — | reconcile 专用；与 agent 上下文无关 |
| `SkillsLoader.build_skills_summary(exclude=...)` | bump view | **函数体内**，循环末尾，`if self.telemetry is not None: self.telemetry.bump(name, "view")` | hook 在函数体内 + telemetry-None injection 物理保证：WebUI 构造 SkillsLoader 时传 `telemetry=None` → 即使 WebUI 未来误调 `build_skills_summary` 也不会污染计数 |
| `SkillsLoader.load_skills_for_context(skill_names)` | bump use | **函数体内**，循环末尾每条真正 load 成功后 `if self.telemetry is not None: self.telemetry.bump(name, "use")` | 内容真正注入 prompt |
| `SkillsLoader.load_skill(name)` | **永不** | — | 独立读取入口，可能被 `_get_skill_meta` 等内部路径递归调用 |

**当前 `build_skills_summary` 与 `load_skills_for_context` 调用现状（M1 验证基线）：**

| 调用方 | 文件:line（M1 前现状） | M1 后传 telemetry |
|---|---|---|
| Agent runtime（主 prompt 构建） | `nanobot/agent/loop.py` 或 `runner.py` 中构建 SkillsLoader 的位置 | ✓ 真实 telemetry |
| WebUI skills API | `nanobot/webui/skills_api.py:17, 32` 构造 SkillsLoader 时 | `None` |
| subagent.py | `nanobot/agent/subagent.py:362` | 复用主进程 telemetry（见上方主表 subagent 行） |

> M1 验证基线：`grep -rn "build_skills_summary\|load_skills_for_context" nanobot/ webui/` 应只命中上表三处调用方。新增 caller 必须在 PR review 阶段明确选择是否传 telemetry。

## 8. 测试与验收标准

### 8.1 单元测试

- [ ] `SkillTelemetry.bump(name, "view"|"use"|"patch")` 三类事件分别更新对应字段，互不串
- [ ] 多线程并发 `bump()` 计数无丢失（10 线程 × 1000 次 × 3 kinds）
- [ ] **asyncio 并发**：100 个 task `await asyncio.to_thread(telemetry.bump, name, kind)` 同时跑（必须用 `to_thread` 真正进入工作线程，否则纯协程是串行的，不能验证 threading.Lock 在多线程下的正确性），`gather` 后串行 `flush()`，磁盘 counter == 100
- [ ] **多进程 RMW**：用 `multiprocessing.get_context("spawn")` 起两个子进程（**不要用 `fork`**——macOS 默认 spawn，Windows 仅 spawn；worker 必须是 top-level 函数，不能是闭包/局部函数），各 bump 500 次后各自 `flush()` 退出；父进程读 `.telemetry.json` 断言 counter == 1000（验证 RMW 增量叠加，不丢失）
- [ ] **flush 失败回滚**：mock filelock 始终超时，bump 100 次 + flush()，`.telemetry.json` 不变；恢复 filelock，下次 flush() 后 counter == 100（验证 `_last_synced_counts` 未在失败路径推进）
- [ ] **bump 延迟可见**：起一个线程在 flush 阶段 2 中途 bump 10 次（用 monkey-patched `atomic_write` 注入 sleep），flush 返回后立即检查磁盘 counter == snapshot 时刻值（不含中途的 10）；下次 flush 后磁盘 counter == snapshot + 10
- [ ] **孤儿不复活**：起两个进程，A bump skill `foo` 5 次（未 flush），B reconcile 时 `foo` 物理文件被删（成孤儿）；A 随后 flush，`.telemetry.json` 里 `foo` 仍不存在
- [ ] **懒初始化 origin 不覆盖真实值**：起两个进程，A 在 reconcile 之前 bump skill `bar`（懒初始化为 `origin="unknown"`，未 flush）；B 完成 reconcile 写入 `origin="agent"`；A 随后 flush，磁盘 `bar.origin == "agent"`（不被 "unknown" 覆盖）
- [ ] 锁竞争超时后 WARN（按 100 次节流）但不抛；`_dirty` 保留，下次 flush 仍能写入
- [ ] 原子写：mock 写入中途崩溃（rename 前 raise），下次启动文件仍可解析；`.tmp` 残留被 reconcile 清理
- [ ] **fsync 目录**：mock `os.fsync` 计数，验证 atomic_write 在 POSIX 下既 fsync tmp 也 fsync parent dir
- [ ] 孤儿清理：磁盘删除一个 skill 后，下次 `reconcile()` 该条目消失（且**该条目同步从 `_last_synced_counts` 移除**）
- [ ] 新 skill 出现时 `entry_created_at = now`，旧 skill `entry_created_at` 不变
- [ ] **reconcile 不动 counters**：手工写一个 `views=42` 的条目，跑 reconcile，磁盘 `views` 仍为 42
- [ ] **bump 未知 name 容忍**：reconcile 之前 bump 未注册 skill，懒初始化条目，`origin="unknown"`
- [ ] **disabled skill telemetry 冻结**：先正常 bump skill `baz` 至 `views=7`；把 `baz` 加入 `disabled_skills`；reconcile → `.telemetry.json` 中 `baz` 条目**仍在**，`views=7` 不变，`origin` 不变；把 `baz` 从 `disabled_skills` 移除后再 reconcile → 正常更新
- [ ] **`list_skills()` 不触发 bump**：构造无 telemetry 的 SkillsLoader（`telemetry=None`），反复调 `list_skills()` 和 `build_skills_summary()`，磁盘 telemetry 不变
- [ ] **`build_skills_summary` 函数体内 hook**：构造带 telemetry 的 SkillsLoader，调一次 `build_skills_summary()`，每个返回行对应一次 `bump(name, "view")`
- [ ] Collision 检测：三源同名 skill 启动时仅 WARN 一次（验证 caplog 行数）
- [ ] Frontmatter `nanobot.provenance` 解析正确（走 `_get_skill_meta(name).get('provenance', {})` 路径）；缺失时返回空 dict（不报错）
- [ ] `AuxiliaryConfig.model_preset` 未配置时 `get_auxiliary_client()` 返回主 preset 的 client
- [ ] `AuxiliaryConfig` camelCase alias `modelPreset` 解析正确
- [ ] **Schema 校验失败**：`auxiliary.modelPreset = "nonexistent"` 时 `Config.model_validate` raise `ValueError`，错误指向该字段
- [ ] **Schema_version 演进**：写 `schema_version=2` + 未知字段 `entries[x].extra="X"` 的 telemetry 文件，读取 + flush 后未知字段仍在
- [ ] **损坏文件容忍**：写一个非法 JSON 的 telemetry 文件，启动 → WARN + 备份到 `.corrupted.<ts>` + 重建 + `_last_synced_counts` 清空

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
| 6 | 2026-06-11 | telemetry schema 字段 | `origin/shadowed/views/uses/patches/entry_created_at/last_view/last_use`（`entry_created_at` 原名 `first_seen`，见决策 #17 重命名） | `origin` 冗余存避免 join；`patches` M1 预留 |
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
| **前置条件**：`<workspace>/skills/agent/` 目录的存在性 | M2 `skill_manage` | M1 **不创建**该目录；M2 实现首次 create skill 时按需 `mkdir -p`；M1 SkillsLoader 必须容忍目录存在/不存在两种情况，行为一致 |
| **Telemetry schema_version 演进** | 未来所有版本 | 读取侧透传未知字段；写入侧只升不降；变更须在本 spec §9 + 新 milestone spec 决策日志各落一行 |
| **`bump()` 调用语义** | M2/M3/M4 | 调用方负责传 `Literal["view","use","patch"]` 之一；不在调用方做"先 ensure 条目再 bump"——telemetry 内部懒初始化 |

## 12. 完工后该追加到 roadmap 的内容

完成 M1 时，需在 [`docs/hermes-evolution/roadmap.md`](../roadmap.md) 做：

1. § 3 表格中 M1 状态 → "已完成"，填入 plan 路径
2. § 5 回顾段落 M1 项追加 200–500 字回顾（实际偏差、坑、对 M2/M3/M4 的影响）
3. § 7 "当前位置" 勾选第 3 项

并在项目根 `README.md`（或 `docs/getting-started.md`，按项目当前文档结构二选一）新增 **"Workspace requirements"** 段，明确：

- `<workspace>` 必须位于本地可读写文件系统；
- 不支持 NFS、SMB、Docker readonly-rootfs（filelock 行为不确定，telemetry 将按"WARN 节流降级"运行，但不能保证 cross-process 计数准确）；
- 推荐 `<workspace>/.gitignore` 增加 telemetry 相关条目（详见本 spec §2）。
