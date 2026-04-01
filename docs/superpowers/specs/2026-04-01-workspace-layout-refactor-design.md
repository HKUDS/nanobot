# Workspace Layout Refactor — Design Spec

**Date:** 2026-04-01
**Author:** haibin + Evie
**Status:** Draft

---

## 1. 动机

当前 workspace 目录结构是扁平的：`sessions/`、`traces/`、`people/` 全部挂在根目录，文件名用 `discord_147xxx.jsonl` 这种 channel_type + chat_id 拼接。问题：

- **不可读**——纯数字 ID，无法一眼看出哪个频道
- **不可管理**——所有渠道混在一起，无法 per-channel 定制行为
- **不可检索**——session 文件无日期信息，`/new` 后旧对话被清空覆盖，原始记录丢失
- **不可扩展**——如果将来加 telegram/wecom 渠道，目录会更混乱

## 2. 目标结构

```
workspace/
├── SOUL.md                              # 全局 base（身份）
├── USER.md                              # 全局 base（用户画像）
├── AGENTS.md                            # 全局 base（行为准则）
├── TOOLS.md                             # 全局 base（工具备忘）
├── MEMORY.md
├── memory/
├── skills/
│
├── discord/                             # 渠道层（后续可加 telegram/, wecom/）
│   ├── people/                          # 从根目录 people/ 迁入
│   │   └── petch/
│   │       ├── SOUL.md
│   │       └── USER.md
│   │
│   ├── develop/                         # channel 目录（自动创建）
│   │   ├── AGENT.md                     # layer 补丁
│   │   ├── sessions/
│   │   │   ├── 2026-04-01_1488787095_01.jsonl
│   │   │   └── 2026-04-01_1488787095_02.jsonl   # /new 后新建
│   │   └── llm_logs/
│   │       ├── 2026-04-01_1488787095_01.jsonl    # 与 session 一一对应
│   │       └── 2026-04-01_1488787095_02.jsonl
│   │
│   ├── kids/
│   │   ├── AGENT.md
│   │   ├── sessions/
│   │   └── llm_logs/
│   │
│   └── writing/
│       ├── AGENT.md
│       ├── sessions/
│       └── llm_logs/
```

## 3. 核心设计决策

| # | 决策 | 选项 | 选定 |
|---|------|------|------|
| 1 | 根目录 people/ | 保留 / 移入渠道 | **移入 discord/people/** |
| 2 | channel 目录命名 | 手动映射 / API 自动 | **Discord API 自动** |
| 3 | AGENT.md 继承模型 | Override / Layer / Scope | **Layer（root + append）** |
| 4 | session 文件命名 | 纯 ID / 日期+ID / 日期+ID+序号 | **{date}\_{chat\_id}\_{seq}.jsonl** |
| 5 | /new 行为 | 覆盖写 / 保留旧文件新建 | **保留旧文件，新建下一序号** |
| 6 | traces 目录 | traces / llm_logs | **llm_logs，文件名与 session 一致** |
| 7 | thread 存放位置 | 独立子目录 / 父 channel 下 | **父 channel 下（chat_id 天然区分）** |

## 4. 架构：WorkspaceLayout

引入 `WorkspaceLayout` 数据类，统一所有路径计算。消灭路径逻辑散弹枪问题。

```python
# nanobot/workspace/layout.py

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    """统一计算 workspace 下所有路径。

    所有消费方（SessionManager、TraceHook、ContextBuilder）
    只问 layout，不自己拼路径。改目录结构只改这里。
    """

    workspace: Path
    channel: str          # "discord", "telegram", ...
    channel_name: str     # "develop", "kids", ...
    chat_id: str          # Discord channel/thread ID

    # --- 目录 ---

    @property
    def channel_dir(self) -> Path:
        """渠道根目录：workspace/discord/"""
        return self.workspace / self.channel

    @property
    def scope_dir(self) -> Path:
        """频道作用域目录：workspace/discord/develop/"""
        return self.channel_dir / self.channel_name

    @property
    def sessions_dir(self) -> Path:
        return self.scope_dir / "sessions"

    @property
    def llm_logs_dir(self) -> Path:
        return self.scope_dir / "llm_logs"

    @property
    def people_dir(self) -> Path:
        """渠道级 people：workspace/discord/people/"""
        return self.channel_dir / "people"

    # --- 文件 ---

    @property
    def agent_md(self) -> Path:
        """Per-channel AGENT.md：workspace/discord/develop/AGENT.md"""
        return self.scope_dir / "AGENT.md"

    def session_path(self, date: str, seq: int) -> Path:
        """Session 文件：sessions/2026-04-01_147xxx_01.jsonl"""
        return self.sessions_dir / f"{date}_{self.chat_id}_{seq:02d}.jsonl"

    def llm_log_path(self, date: str, seq: int) -> Path:
        """LLM log 文件，与 session 一一对应。"""
        return self.llm_logs_dir / f"{date}_{self.chat_id}_{seq:02d}.jsonl"

    def next_session_seq(self, date: str) -> int:
        """扫描 sessions_dir，返回当天下一个可用序号。"""
        if not self.sessions_dir.exists():
            return 1
        prefix = f"{date}_{self.chat_id}_"
        existing = [
            int(p.stem.rsplit("_", 1)[-1])
            for p in self.sessions_dir.glob(f"{prefix}*.jsonl")
        ]
        return max(existing, default=0) + 1

    def ensure_dirs(self) -> None:
        """首次使用时创建必要目录。"""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.llm_logs_dir.mkdir(parents=True, exist_ok=True)


# --- 工厂：非渠道消息的 fallback ---

def make_layout(
    workspace: Path,
    channel: str,
    channel_name: str | None,
    chat_id: str,
) -> WorkspaceLayout:
    """构造 layout。channel_name 未知时 fallback 到 chat_id。"""
    name = channel_name or chat_id
    return WorkspaceLayout(
        workspace=workspace,
        channel=channel,
        channel_name=name,
        chat_id=chat_id,
    )
```

### 4.1 职责边界

| 组件 | 改动 | 依赖 layout |
|------|------|-------------|
| `WorkspaceLayout` | **新增** | — |
| `SessionManager` | 路径计算委托给 layout；`/new` 改为新建文件 | `layout.session_path()`, `layout.next_session_seq()` |
| `TraceHook` | traces_dir 改从 layout 取 | `layout.llm_logs_dir`, `layout.llm_log_path()` |
| `ContextBuilder._resolve_bootstrap_path` | people 路径从 layout 取 | `layout.people_dir` |
| `ContextBuilder._load_bootstrap_files` | 加载 root 后 append channel AGENT.md | `layout.agent_md` |
| `AgentLoop._process_message` | 入口处构造 layout，传给下游 | `make_layout()` |
| Discord channel adapter | 确保 channel_name 在 InboundMessage.metadata 里 | 无（已有数据，只需传递） |

## 5. Session 生命周期（改动后）

### 5.1 正常消息处理

```
消息到达
  → AgentLoop 构造 WorkspaceLayout(channel, channel_name, chat_id)
  → SessionManager.get_or_create(layout)
    → 查找 layout.sessions_dir 下当天最大序号的文件
    → 加载该文件到内存
  → 处理对话
  → SessionManager.save(session)  写回同一个文件
```

### 5.2 /new 命令

```
/new
  → 旧 session 文件原封不动，不清空不删除
  → session.clear() 清空内存对象
  → SessionManager 计算 next_session_seq(today) → 新序号
  → 新建空文件，后续消息写入新文件
  → 旧的未 consolidate 消息照常 archive 到 HISTORY.md
```

### 5.3 文件命名示例

同一频道 `develop`（chat_id: `1488787095`），同一天 3 次 `/new`：
```
sessions/
├── 2026-04-01_1488787095_01.jsonl    # 第一段对话
├── 2026-04-01_1488787095_02.jsonl    # /new 后第二段
└── 2026-04-01_1488787095_03.jsonl    # /new 后第三段（当前活跃）
```

## 6. Context 加载链（改动后）

```
1. Root base layer:
   workspace/SOUL.md
   workspace/USER.md
   workspace/AGENTS.md
   workspace/TOOLS.md

2. Per-sender override（layer 覆盖）:
   workspace/discord/people/{sender}/SOUL.md    ← 替换 root SOUL.md
   workspace/discord/people/{sender}/USER.md    ← 替换 root USER.md

3. Per-channel append（layer 追加）:
   workspace/discord/develop/AGENT.md           ← append 到 root AGENTS.md 之后
```

**加载优先级：** root 文件先加载 → per-sender 同名文件 override 对应 root 文件 → per-channel AGENT.md 作为补丁追加到系统 prompt 末尾。

## 7. channel_name 解析

**职责归属：Discord channel adapter（不是 SessionManager）。**

Discord adapter 在 `on_message` 事件中已能拿到 `channel.name`。流程：

1. Discord event 到达 → adapter 从 event 对象读取 `channel.name`
2. Thread 消息：读取 `thread.parent.name` 作为 channel_name
3. 写入 `InboundMessage.metadata["channel_name"]`
4. AgentLoop 从 metadata 取出，构造 WorkspaceLayout
5. SessionManager 和 TraceHook 使用 layout，**不做任何 API 调用**

**Fallback：** 如果 channel_name 不可用（极端情况），用 chat_id 作为目录名。

## 8. 迁移方案

一次性迁移脚本 `scripts/migrate_workspace_layout.py`：

### 8.1 步骤

1. 从 Discord API 批量拉取 guild 的所有 channel，建立 `chat_id → channel_name` 映射表
2. 创建 `workspace/discord/people/` 目录
3. `mv workspace/people/* workspace/discord/people/`
4. 对每个 `workspace/sessions/discord_{chat_id}.jsonl`：
   - 查映射表得到 channel_name
   - 创建 `workspace/discord/{channel_name}/sessions/`
   - 移动文件，重命名为 `{created_date}_{chat_id}_01.jsonl`（created_date 从 JSONL metadata 行读取）
5. 对每个 `workspace/traces/discord_{chat_id}.jsonl`：
   - 同上逻辑移到 `workspace/discord/{channel_name}/llm_logs/`
6. 清理空的旧目录 `workspace/sessions/`、`workspace/traces/`、`workspace/people/`

### 8.2 安全措施

- 迁移前 snapshot 整个 workspace（`tar czf workspace_backup.tar.gz workspace/`）
- 映射表找不到的 chat_id 保留在旧位置，打 warning log
- 干跑模式（`--dry-run`）先预览不执行

## 9. 影响范围

### 改动文件（预估）

| 文件 | 改动类型 | 预估行数 |
|------|---------|---------|
| `nanobot/workspace/__init__.py` | **新增** | ~5 |
| `nanobot/workspace/layout.py` | **新增** | ~80 |
| `nanobot/session/manager.py` | 重构路径逻辑 + /new 行为 | ~60 改动 |
| `nanobot/agent/trace.py` | 改用 layout | ~15 改动 |
| `nanobot/agent/context.py` | people 路径 + AGENT.md 加载 | ~30 改动 |
| `nanobot/agent/loop.py` | 构造 layout 传给下游 | ~20 改动 |
| `nanobot/channels/discord.py` | 确保传递 channel_name | ~5 改动 |
| `nanobot/command/builtin.py` | /new 改为新建文件 | ~15 改动 |
| `scripts/migrate_workspace_layout.py` | **新增** | ~120 |
| tests/ | 新增 + 适配 | ~150 |

**总预估：~500 行改动/新增**

### 不改动

- `nanobot/agent/runner.py` — 不涉及路径
- `nanobot/agent/memory.py` — MEMORY.md/HISTORY.md 路径不变（仍在 workspace 根）
- `nanobot/providers/*` — 完全不涉及
- `nanobot/config/*` — 不需要新 config 字段
- `nanobot/bus/*` — 不涉及

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Discord channel rename 导致目录名变化 | 低 | 新目录自动创建，旧目录成孤儿 | 可加 channel_id→name 的持久映射文件，rename 时做 mv |
| 迁移脚本遗漏部分文件 | 低 | 部分 session 找不到 | dry-run 预览 + 备份 + fallback 到旧路径 |
| thread 的 parent channel 可能已删除 | 极低 | channel_name 拿不到 | fallback 到 chat_id 作目录名 |
| 序号竞态（并发 /new） | 极低 | 重复序号 | 已有 session_lock 保护 |

## 11. 待定项

- [ ] channel rename 后的目录迁移策略：自动 rename 还是保持旧名？
- [ ] CLI 模式（非 Discord）的 layout fallback 策略确认
- [ ] 是否需要一个 `workspace/discord/channels.json` 持久化 id→name 映射
