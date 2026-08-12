# My Tool

让 agent 感知并调整自身的运行时状态，就像询问同事“你忙吗？可以换到更大的显示器吗？”

## 为什么需要它

普通工具让 agent 能够操作外部世界（读写文件、搜索代码）。但 agent 对自身一无所知：它不知道自己正在运行哪个 model、还剩多少次迭代，或已经消耗了多少 token。

My tool 填补了这一空白。借助它，agent 可以：

- **了解自身状态**：我正在使用哪个 model？我的 workspace 在哪里？还剩多少次迭代？
- **即时调整**：任务复杂？扩大 context window。简单聊天？切换到更快的 model。
- **跨轮次记忆**：将笔记存储在 scratchpad 中，并保留到下一次 conversation turn。

## 配置

默认启用（只读模式）。agent 可以检查其状态，但不能设置状态。

```yaml
tools:
  my:
    enable: true       # default: true
    allow_set: false   # default: false (read-only)
```

若要允许 agent 设置其配置（例如切换 model、调整参数），请设置 `tools.my.allow_set: true`。

旧版 `tools.myEnabled` / `tools.mySet` 键会在加载时自动迁移，并在下次 `nanobot onboard` 刷新配置时原地重写。

大多数修改仅保存在内存中。`model_preset` 是例外：它会存储在当前 session 中，因此选择结果会在重启后保留。

---

## check — 检查“my”的当前状态

不带参数时，返回关键配置概览：

```text
my(action="check")
# → max_iterations: 40
#   context_window_tokens: 200000
#   model: 'anthropic/claude-sonnet-4-6'
#   workspace: PosixPath('/tmp/workspace')
#   provider_retry_mode: 'standard'
#   max_tool_result_chars: 16000
#   _current_iteration: 3
#   _last_usage: {'prompt_tokens': 45000, 'completion_tokens': 8000}
#   Note: prompt_tokens is cumulative across all turns, not current context window occupancy.
```

使用 key 参数可深入查看特定配置：

```text
my(action="check", key="_last_usage.prompt_tokens")
# → How many prompt tokens I've used so far

my(action="check", key="model")
# → What model I'm currently running on

my(action="check", key="web_config.enable")
# → Whether web search is enabled
```

### 可以用它做什么

| 场景 | 方法 |
|----------|-----|
| “你正在使用哪个 model？” | `check("model")` |
| “哪个 model preset 处于激活状态？” | `check("model_preset")` |
| “还可以进行多少次 tool 调用？” | `check("max_iterations")` 减去 `check("_current_iteration")` |
| “此 conversation 使用了多少 token？” | `check("_last_usage")` — 统计所有 turn 的累计值 |
| “你的工作目录在哪里？” | `check("workspace")` |
| “显示完整配置” | `check()` |
| “是否有 subagent 正在运行？” | `check("subagents")` — 显示阶段、迭代次数、已用时间和 tool 事件 |

---

## set — 运行时调优

修改无需重启。`model_preset` 会保存到当前 session，并应用于其下一次 turn；其他可写的运行时调优会立即生效。

在活跃 session 期间，直接写入 `model` 和 `context_window_tokens` 会被拒绝，因为这些 setter 会修改共享实例的默认值。应改为配置命名 preset 来更改 model 或 context window。

```text
my(action="set", key="max_iterations", value=80)
# → Bump iteration limit from 40 to 80

my(action="set", key="model_preset", value="fast")
# → Use a configured model preset for this session's next turn
```

也可以在 scratchpad 中存储自定义状态：

```text
my(action="set", key="current_project", value="nanobot")
my(action="set", key="user_style_preference", value="concise")
my(action="set", key="task_complexity", value="high")
# → These values persist into the next conversation turn
```

### 受保护的参数

这些参数具有类型和范围验证，非法值会被拒绝：

| 参数 | 类型 | 范围 | 用途 |
|-----------|------|-------|---------|
| `max_iterations` | int | 1–100 | 每个 conversation turn 的最大 tool 调用次数 |
| `context_window_tokens` | int | 4,096–1,000,000 | 实例默认值；在 session 期间通过 preset 选择 |
| `model` | str | 非空 | 实例默认值；在 session 期间通过 preset 选择 |
| `model_preset` | str | 已配置的 preset 名称 | 当前 session 在下一次 turn 使用的 preset |

其他参数（例如 `workspace`、`provider_retry_mode`、`max_tool_result_chars`）可以自由设置，只要值符合 JSON 安全要求。

---

## 实际场景

### “这个任务很复杂，我需要更多空间”

```text
Agent: This codebase is large, let me switch this session to the configured deep preset.
→ my(action="set", key="model_preset", value="deep")
```

### “简单问题，不要浪费计算资源”

```text
Agent: This is a straightforward question, let me switch to the fast preset.
→ my(action="set", key="model_preset", value="fast")
```

### “跨 turn 记住用户偏好”

```text
Turn 1: my(action="set", key="user_prefers_concise", value=True)
Turn 2: my(action="check", key="user_prefers_concise")
# → True (still remembers the user likes concise replies)
```

### “自我诊断”

```text
User: "Why aren't you searching the web?"
Agent: Let me check my web config.
→ my(action="check", key="web_config.enable")
# → False
Agent: Web search is disabled — please set web.enable: true in your config.
```

### “Token 预算管理”

```text
Agent: Let me check how much budget I have left.
→ my(action="check", key="_last_usage")
# → {"prompt_tokens": 45000, "completion_tokens": 8000}
Agent: I've used ~53k tokens total so far. I'll keep my remaining replies concise.
```

### “Subagent 监控”

```text
Agent: Let me check on the background tasks.
→ my(action="check", key="subagents")
# → 2 subagent(s):
#   [task-1] 'Code review'
#     phase: running, iteration: 5, elapsed: 12.3s
#     tools: read(✓), grep(✓)
#     usage: {'prompt_tokens': 8000, 'completion_tokens': 1200}
#   [task-2] 'Write tests'
#     phase: pending, iteration: 0, elapsed: 0.2s
#     tools: none
Agent: The code review is progressing well. The test task hasn't started yet.
```

---

## 安全机制

核心设计原则：**该 tool 不会重写 `config.json`。** 实例范围的修改仅保存在内存中，而 `model_preset` 只会作为当前 session 的选择器持久化。

### 禁止访问（BLOCKED）

无法检查或修改，完全隐藏：

| 类别 | 属性 | 原因 |
|----------|-----------|--------|
| 核心基础设施 | `bus`、`provider`、`_running` | 修改会导致系统崩溃 |
| Tool 注册表 | `tools` | 不得移除自身的 tools |
| 子系统 | `runner`、`sessions`、`consolidator` 等 | 会影响其他用户/session |
| 敏感数据 | `_mcp_servers`、`_pending_queues` 等 | 包含凭据和消息路由信息 |
| 安全边界 | `restrict_to_workspace`、`channels_config` | 绕过会违反隔离要求 |
| Python 内部机制 | `__class__`、`__dict__` 等 | 防止逃逸 sandbox |

### 只读（仅可 check）

可以检查但不能设置：

| 类别 | 属性 | 原因 |
|----------|-----------|--------|
| Subagent 管理器 | `subagents` | 可观察，但替换会破坏系统 |
| 执行配置 | `exec_config` | 可以检查 sandbox/enable 状态，但不能更改 |
| Web 配置 | `web_config` | 可以检查 enable 状态，但不能更改 |
| 迭代计数器 | `_current_iteration` | 仅由 runner 更新 |

### 敏感字段保护

与敏感名称（`api_key`、`password`、`secret`、`token` 等）匹配的子字段，无论其父路径是什么，都会被禁止 check 和 set。这可以防止通过点路径遍历泄露凭据（例如 `web_config.search.api_key`）。
