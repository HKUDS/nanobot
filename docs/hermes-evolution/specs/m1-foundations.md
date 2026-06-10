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
2. **SkillsLoader 三源支持**：原有 `user(workspace) / builtin` 两源扩展为 `user / agent / builtin` 三源，加载优先级 user > agent > builtin，启动期对同名 collision 打 WARNING。
3. **Telemetry 子系统**：新增 `<workspace>/skills/.telemetry.json`、`SkillTelemetry` 辅助类、文件锁、孤儿清理、view/use 计数 hook（patches 计数器仅预留字段）。
4. **Provenance frontmatter 字段**：仅在 agent 创建 skill 时写入 `nanobot.provenance: {origin: agent, created_at: ISO8601}`，其他来源 skill 不强制。
5. **Auxiliary provider 配置**：在 `agents.defaults.auxiliary.modelPreset` 引入一个引用现有 `modelPresets` key 的配置项；新增 `get_auxiliary_client()` 工厂；未配置时 fallback 到主 preset。
6. **runner.py / context.py 计数 hook**：在 `build_skills_summary()` 命中时 `views += 1`，`load_skills_for_context()` 命中时 `uses += 1`；通过异步 flush 机制减少磁盘 IO 频率。
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

## 3. 加载优先级与 collision 处理

### 3.1 优先级

`SkillsLoader.list_skills()` 按以下顺序合并三源（先入为主）：

1. `<workspace>/skills/*/SKILL.md`（user，**最高优先级**）
2. `<workspace>/skills/agent/*/SKILL.md`（agent）
3. `nanobot/skills/*/SKILL.md`（builtin，**最低优先级**）

同名 skill 仅取最高优先级源的内容；其他源被"影子"。

### 3.2 Collision 检测

启动时如检测到跨源同名：

- 用 `loguru.warning` 输出一次，格式：
  ```
  Skill name collision: 'summarize' shadowed at <workspace>/skills/summarize/SKILL.md,
    hidden at [<workspace>/skills/agent/summarize/SKILL.md,
              nanobot/skills/summarize/SKILL.md]
  ```
- **每次启动只打一次**，避免重复噪声（实现：collision 检测放在 `SkillsLoader.__init__` 而非每次 `list_skills()`）。
- 不阻塞启动；不自动重命名；user 自己决定如何处理。

### 3.3 不重命名原则

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
      "first_seen": "2026-05-20T10:00:00Z",
      "last_view": "2026-06-11T03:10:00Z",
      "last_use": "2026-06-11T03:08:00Z"
    },
    "auto-summarize": {
      "origin": "agent",
      "shadowed": [],
      "views": 7,
      "uses": 2,
      "patches": 1,
      "first_seen": "2026-06-09T14:22:00Z",
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
| `views` | int | 出现在 `build_skills_summary()` 的次数 | 0 |
| `uses` | int | 内容被注入 prompt 的次数 | 0 |
| `patches` | int | M2 起由 `skill_manage` 触发 | 0 |
| `first_seen` | ISO8601 | telemetry 首次见到该 skill 的时间 | reconcile 时写入 |
| `last_view` / `last_use` | ISO8601 \| null | 最近一次事件时间 | null |

### 4.2 `SkillTelemetry` 类（新文件 `nanobot/agent/skills_telemetry.py`）

API 表面（最小可用）：

```python
class SkillTelemetry:
    def __init__(self, workspace: Path) -> None: ...

    def reconcile(self, known_skills: list[SkillEntry]) -> None:
        """启动时调用：删除孤儿条目；为新出现的 skill 写零计数初始条目；
        同时更新 entries 的 effective `origin` 与 `shadowed` 字段。

        `SkillEntry` 是一个 dict（或 TypedDict / dataclass）：
          {
            "name": str,
            "effective_origin": "user" | "agent" | "builtin",
            "shadowed_origins": list[str],   # 若无 collision 则空
            "path": str,                     # effective SKILL.md 路径
          }
        SkillsLoader 需提供 `list_skills_with_shadows()` 返回该形态。
        """

    def bump_views(self, name: str) -> None:
        """实现完整：累加 views += 1 并更新 last_view。M1 由 build_skills_summary 调用。"""

    def bump_uses(self, name: str) -> None:
        """实现完整：累加 uses += 1 并更新 last_use。M1 由 load_skills_for_context 调用。"""

    def bump_patches(self, name: str) -> None:
        """实现完整：累加 patches += 1。M1 不调用；预留给 M2 的 skill_manage 工具。"""

    def snapshot(self) -> dict:
        """返回当前 telemetry 的只读视图，给未来的 Curator/CLI 用。"""

    def flush(self) -> None:
        """显式触发磁盘落盘（异步 flush 队列里的累积 bump）。"""
```

### 4.3 并发与持久化

- 使用 [`filelock`](https://pypi.org/project/filelock/) 库（已在 `pyproject.toml` 依赖 `filelock>=3.25.2`，无需新增）。
- 写入策略：内存累积 + 异步 flush。每次 `bump_*` 只更新内存 dict；每个 agent turn 结束时（在 `runner.py` 主循环出口）触发一次 `flush()`；进程退出时 `atexit` 兜底 flush。
- 锁失败 ≤200ms 重试 3 次，再失败：日志 WARNING，丢弃这次 bump（**不阻塞 agent 主流程**——telemetry 是观察数据，不是关键路径）。
- 原子写：`tmp file → fsync → rename`，保证文件永远是完整 JSON（不会出现半写）。

### 4.4 孤儿清理（reconcile）

启动时 `SkillsLoader` 初始化完后调用 `telemetry.reconcile(known_skills)`：

1. 已知 skill 列表来自新方法 `SkillsLoader.list_skills_with_shadows()`，返回每条 skill 的 `effective_origin` 与 `shadowed_origins`（见 §4.2 SkillEntry 定义）。
2. 遍历 telemetry `entries`：磁盘已不存在的删除；新出现的写零初值（`first_seen = now`）。
3. 同时刷新 `origin` 和 `shadowed` 字段（如 user 删了同名 skill，agent 的"上位"为 effective origin；shadow 列表也相应缩短）。
4. 这次合并写入计入一次 flush。

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

M1 本身**不调用** aux client 做任何业务；但提供一个 smoke-test：

- 启动 gateway 时（或 CLI agent 初始化时），如果 `auxiliary.model_preset` 显式配了，调用 `get_auxiliary_client(config)` 一次做"模型注册查询"（不真正发 inference 请求，只验证 preset 存在且 provider 可解析）。
- smoke-test 失败：**降级为 WARNING 而不抛 ConfigError**，理由是 M1 阶段尚无消费者，不应该因为一个未使用的配置项阻断 gateway 启动。M3/M4 启动它们各自的消费路径时才让 `get_auxiliary_client()` 的 `ConfigError` 阻断。
- 真正的端到端 ping（发一次最小请求）留给 M3 自己的 spec。

## 7. 代码改动点（文件级清单）

| 文件 | 改动 | 风险等级 |
|---|---|---|
| `nanobot/agent/skills.py` | (a) `_skill_entries_from_dir` 支持识别并跳过 `agent/` 子目录条目（避免它被当成名为 `agent` 的 skill）；(b) 新增 `_entries_from_agent_dir()`；(c) `list_skills()` 三源合并 + collision 检测 + warning；(d) 在 `build_skills_summary()` 和 `load_skills_for_context()` 内挂 telemetry hook | 中（核心加载路径） |
| `nanobot/agent/skills_telemetry.py` *(新)* | `SkillTelemetry` 类：`reconcile/bump_*/snapshot/flush`；filelock + 原子写 + 异步 flush 队列 | 低（独立新模块） |
| `nanobot/config/schema.py` | `AuxiliaryConfig` 类 + `AgentDefaults.auxiliary` 字段 + camelCase alias | 低 |
| `nanobot/providers/factory.py` | `get_auxiliary_client(config)` 工厂 + fallback 逻辑（factory.py 负责实例化，与现职责一致） | 低 |
| `nanobot/agent/loop.py` 或 `runner.py` | SkillsLoader 构造时注入 telemetry；主 turn 出口处调用 `telemetry.flush()`；gateway 启动期 aux provider smoke-test 调用 | 低（一行级钩入） |
| `pyproject.toml` | 无需改动（`filelock>=3.25.2` 已在依赖中） | — |
| `tests/agent/test_skills_telemetry.py` *(新)* | 并发 bump、孤儿清理、collision、原子写、锁失败降级 | — |
| `tests/agent/test_skills_loader.py` 扩展 | 三源优先级、collision warning 一次性 | — |
| `tests/config/test_schema.py` 扩展 | `auxiliary.modelPreset` 解析、camelCase、fallback | — |
| `tests/providers/test_factory.py` 扩展（或新增） | `get_auxiliary_client()` 解析 + fallback | — |

## 8. 测试与验收标准

### 8.1 单元测试

- [ ] `SkillTelemetry` 多线程并发 `bump_views/uses` 计数无丢失（10 线程 × 1000 次）
- [ ] 锁竞争超时后 WARN 但不抛
- [ ] 原子写：mock 写入中途崩溃，下次启动文件仍可解析
- [ ] 孤儿清理：磁盘删除一个 skill 后，下次 `reconcile()` 该条目消失
- [ ] 新 skill 出现时 `first_seen = now`，旧 skill `first_seen` 不变
- [ ] Collision 检测：三源同名 skill 启动时仅 WARN 一次（验证 caplog 行数）
- [ ] Frontmatter `nanobot.provenance` 解析正确；缺失时 origin 由目录推断
- [ ] `AuxiliaryConfig.model_preset` 未配置时 `get_auxiliary_client()` 返回主 preset 的 client
- [ ] `AuxiliaryConfig` camelCase alias `modelPreset` 解析正确

### 8.2 集成测试

- [ ] 全新 workspace 启动 → 跑一轮 agent 对话 → `.telemetry.json` 出现且 `views > 0`
- [ ] 已有 workspace（有 user skills 但无 `agent/` 目录）启动 → 不报错 + telemetry 为现有 user skill 创建零计数条目
- [ ] 显式配 `auxiliary.modelPreset` 指向 `lite` preset → `get_auxiliary_client()` 返回的 client 模型字段与 `lite.model` 匹配

### 8.3 验收门

- [ ] 全部单元 + 集成测试通过
- [ ] `ruff check nanobot/` 零 warning
- [ ] 本地真实跑 ≥10 轮对话，`.telemetry.json` 数据合理（`views ≥ uses`，`uses` 与实际触发 skill 数对得上）
- [ ] 设计 spec（本文）+ 实施 plan 都已 commit
- [ ] `roadmap.md` 中 M1 状态切换为"已完成"，并追加 200–500 字回顾笔记

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

## 10. 风险与回滚

### 10.1 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 修改 `SkillsLoader.list_skills()` 引入回归（影响现有 skill 装载） | 中 | 充分单元测试 + 集成测试；保留旧入口 `_skill_entries_from_dir` 行为不变，新功能走新方法 |
| filelock 在某些文件系统（NFS、容器只读层）行为异常 | 低-中 | 文档明确 `<workspace>` 必须可读写；锁失败降级仅 WARN，不阻断 |
| 异步 flush 队列在进程异常时丢失最近 N 次 bump | 低 | telemetry 是观察数据，少量丢失可接受；atexit 兜底；Curator (M3) 不依赖完美计数 |
| `auxiliary.modelPreset` 引用了不存在的 preset | 低 | 启动期 smoke-test 检测 + WARN；运行时调用 `get_auxiliary_client()` 时再校验一次 |
| 现有 user 已有名为 `agent` 的目录条目 → 与新约定冲突 | 低 | 启动期检测：若 `<workspace>/skills/agent/SKILL.md` 存在（即把 agent 当成一个普通 skill），打 ERROR 提示 user 手动迁移，不强行接管 |

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
| `SkillTelemetry.bump_patches(name)` | M2 `skill_manage` 工具 | M1 已完整实现（累加计数 + 落盘），M1 内无调用方；M2 直接调用 |
| `SkillTelemetry.snapshot()` | M3 Curator Phase 1（确定性状态机） | 返回不可变 dict，M3 据此做 active/stale/archive 判断 |
| `nanobot.provenance.origin == "agent"` 检测 | M3 Curator | M1 已保证字段存在与否的语义 |
| `get_auxiliary_client(config)` | M3 Curator Phase 2、M4 LLM-as-judge | M1 已提供，M3/M4 不需再做工厂 |
| `<workspace>/skills/agent/` 目录可写 | M2 `skill_manage` | M1 不强制创建，但保证 SkillsLoader 容忍其存在/不存在 |

## 12. 完工后该追加到 roadmap 的内容

完成 M1 时，需在 [`docs/hermes-evolution/roadmap.md`](../roadmap.md) 做：

1. § 3 表格中 M1 状态 → "已完成"，填入 plan 路径
2. § 5 回顾段落 M1 项追加 200–500 字回顾（实际偏差、坑、对 M2/M3/M4 的影响）
3. § 7 "当前位置" 勾选第 3 项
