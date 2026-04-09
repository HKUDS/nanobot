# /model 命令 — 运行时模型切换

## 概述

新增 `/model` 斜杠命令，支持运行时切换 LLM 模型。Discord 端通过 slash command choices 下拉框选择模型，无需手动输入模型名。

**设计决策：**
- **全局作用域**：切换影响所有 channel/session（单用户场景）
- **裸奔模式**：手动切换后不走 fallback chain，用户明确知道自己要什么
- **Ephemeral**：重启即恢复 config 默认值，不持久化 override 状态
- **choices 来源**：启动时从 config 的 `model` + `fallbackModels` 生成静态 choices 列表

## 文件变更地图

```
nanobot/
├── agent/
│   └── loop.py              # [修改] 保存原始 provider/model，暴露切换方法
├── command/
│   ├── builtin.py            # [修改] 新增 cmd_model handler + 注册
│   └── discord_slash.py      # [修改] build_builtin_commands 加 /model 定义
├── nanobot.py                # [修改] from_config 传 config 引用给 AgentLoop
tests/
├── command/
│   └── test_model_command.py # [新建] cmd_model 单元测试
```

## Task 1: AgentLoop 保存原始状态 + 暴露切换方法

**文件：** `nanobot/agent/loop.py`

### 1.1 `__init__` 新增参数和字段

在 `__init__` 签名中新增可选参数 `config: Any = None`，用于后续 `_make_single_provider` 构建新 provider。

在 `__init__` 方法体中，`self.model = model or provider.get_default_model()` 之后，新增：

```python
self._config = config                    # 原始 Config 对象，用于构建新 provider
self._config_model = self.model          # config 中的默认 model，不可变
self._config_provider = self.provider    # config 中的默认 provider（含 fallback），不可变
```

### 1.2 新增 `switch_model` 方法

在 `AgentLoop` 类中新增方法：

```python
def switch_model(self, model: str) -> str:
    """运行时切换模型。返回实际生效的 model 名。

    构建新的单 provider（无 fallback），替换 self.provider 和 self.model。
    失败时抛出 ValueError。
    """
    from nanobot.nanobot import _make_single_provider

    new_provider = _make_single_provider(self._config, model)
    new_provider.generation = self._config_provider.generation
    self.provider = new_provider
    self.model = model
    # 同步更新 runner 的 provider 引用
    self.runner.provider = new_provider
    logger.info("Model switched to: {}", model)
    return model
```

### 1.3 新增 `reset_model` 方法

```python
def reset_model(self) -> str:
    """恢复到 config 默认 model + provider（含 fallback chain）。"""
    self.provider = self._config_provider
    self.model = self._config_model
    self.runner.provider = self._config_provider
    logger.info("Model reset to default: {}", self._config_model)
    return self._config_model
```

### 1.4 新增 `get_model_choices` 方法

供 Discord slash command 注册时获取 choices 列表：

```python
def get_model_choices(self) -> list[str]:
    """返回可切换的模型列表：config model + fallback models。"""
    if not self._config:
        return [self._config_model]
    fb = self._config.agents.defaults.fallback_models or []
    return [self._config_model] + list(fb)
```

### 1.5 验证 `runner.provider` 可写

检查 `nanobot/agent/runner.py` 中 `AgentRunner` 的 `provider` 属性。当前 `AgentRunner.__init__` 接收 `provider` 参数并存为 `self.provider`，是普通属性，可直接赋值。无需额外修改。

---

## Task 2: `from_config` 传递 config 引用

**文件：** `nanobot/nanobot.py`

在 `from_config` 方法中，构造 `AgentLoop` 时传入 `config=config`：

找到 `AgentLoop(...)` 调用（约第 80 行），在参数列表中加入 `config=config`。

同时确认 `AgentLoop.__init__` 签名中 `config` 参数的位置——放在 `hooks` 之后作为最后一个可选参数。

---

## Task 3: `cmd_model` 命令 handler

**文件：** `nanobot/command/builtin.py`

### 3.1 新增 `cmd_model` 函数

```python
async def cmd_model(ctx: CommandContext) -> OutboundMessage:
    """切换或查看当前 LLM 模型。"""
    loop = ctx.loop
    args = (ctx.args or "").strip()

    # /model（无参数）→ 显示当前状态
    if not args:
        is_override = loop.model != loop._config_model
        lines = [
            f"🧠 Current model: `{loop.model}`",
            f"📋 Config default: `{loop._config_model}`",
        ]
        if is_override:
            lines.append("⚡ Status: **overridden** (use `reset` to restore)")
        else:
            lines.append("✅ Status: using config default")

        # fallback chain 状态
        from nanobot.providers.fallback import FallbackProvider
        if isinstance(loop._config_provider, FallbackProvider):
            fb_models = [m for _, m in loop._config_provider.fallbacks]
            lines.append(f"🔄 Fallback chain: {' → '.join(fb_models)}")
            if loop._config_provider._in_cooldown():
                lines.append("⚠️ Primary in cooldown — fallback active")

        return ctx.make_response("\n".join(lines))

    # /model reset → 恢复默认
    if args.lower() == "reset":
        model = loop.reset_model()
        return ctx.make_response(f"↩️ Model reset to default: `{model}`")

    # /model <model_name> → 切换
    try:
        model = loop.switch_model(args)
        return ctx.make_response(f"✅ Model switched to: `{model}`")
    except Exception as e:
        return ctx.make_response(f"❌ Failed to switch model: {e}")
```

### 3.2 注册命令

在 `register_builtin_commands` 函数中添加：

```python
router.prefix("/model ", cmd_model)
router.exact("/model", cmd_model)
```

### 3.3 更新 `/help` 输出

在 `cmd_help` 的 `lines` 列表中添加：

```python
"/model — View or switch the LLM model",
```

---

## Task 4: Discord slash command 注册

**文件：** `nanobot/command/discord_slash.py`

### 4.1 `build_builtin_commands` 新增 `/model`

在返回的列表中添加：

```python
{
    "name": "model",
    "description": "View or switch the LLM model",
    "type": 1,
    "options": [
        {
            "name": "target",
            "description": "Model to switch to, or 'reset'",
            "type": 3,  # STRING
            "required": False,
            "choices": [],  # 占位，运行时填充
        }
    ],
},
```

### 4.2 choices 动态填充

问题：`build_builtin_commands` 是静态函数，不接收 config。需要改造。

**方案：** 给 `build_builtin_commands` 加可选参数 `model_choices: list[str] | None = None`。

choices 构建逻辑：

```python
def _build_model_choices(model_choices: list[str] | None) -> list[dict]:
    """构建 /model 的 Discord choices 列表。"""
    choices = []
    if model_choices:
        for m in model_choices:
            # Discord choice name 限 100 字符，取最后一段作为显示名
            display = m.split("/")[-1] if "/" in m else m
            choices.append({"name": display, "value": m})
    choices.append({"name": "↩ reset to default", "value": "reset"})
    return choices[:25]  # Discord 限制最多 25 个 choices
```

如果 `model_choices` 为空（非 Discord 场景），`/model` 的 options 中不带 choices，用户手动输入。

### 4.3 调用链修改

`register_all_commands` 需要能拿到 model_choices。

在 `nanobot/channels/discord.py` 的 `_register_slash_commands` 调用处，从 `AgentLoop` 获取 choices 传入。

查看当前调用链：`discord.py` 的 `connect()` 方法中调用 `register_all_commands(http, token, guild_ids, skills_loader)`。

修改 `register_all_commands` 签名，新增 `model_choices: list[str] | None = None`，透传给 `build_builtin_commands`。

在 `discord.py` 中，`DiscordChannel` 需要能访问 `AgentLoop` 来调用 `get_model_choices()`。当前 `DiscordChannel` 不持有 loop 引用。

**最简方案：** 在 `DiscordChannel` 注册 slash commands 时，从 config 直接读取 model + fallbackModels，不依赖 AgentLoop。

```python
# discord.py 中注册 slash commands 的位置
from nanobot.config.loader import load_config
config = load_config()
defaults = config.agents.defaults
model_choices = [defaults.model] + list(defaults.fallback_models or [])
await register_all_commands(http, token, guild_ids, skills_loader, model_choices=model_choices)
```

这样 `DiscordChannel` 不需要持有 loop 引用，保持现有解耦。

### 4.4 `_BUILTIN_NAMES` 更新

在 `discord_slash.py` 的 `_BUILTIN_NAMES` 集合中添加 `"model"`。

---

## Task 5: 测试

**文件：** `tests/command/test_model_command.py`（新建）

### 5.1 测试 fixtures

构造 mock AgentLoop，包含：
- `model`, `_config_model`, `provider`, `_config_provider`, `_config`, `runner`
- `switch_model()`, `reset_model()` 方法

### 5.2 测试用例

```
test_model_show_status_default
  /model 无参数 → 返回当前 model + config default + "using config default"

test_model_show_status_overridden
  手动设置 loop.model != loop._config_model → 返回 "overridden"

test_model_switch_success
  /model some-model → 调用 switch_model → 返回 "switched to"

test_model_switch_failure
  switch_model 抛 ValueError → 返回 "Failed to switch"

test_model_reset
  /model reset → 调用 reset_model → 返回 "reset to default"

test_model_show_fallback_chain
  _config_provider 是 FallbackProvider → 显示 fallback chain

test_model_show_cooldown
  FallbackProvider._in_cooldown() 返回 True → 显示 cooldown 警告
```

### 5.3 Discord slash command choices 测试

验证 `build_builtin_commands(model_choices=[...])` 生成的 `/model` command 包含正确的 choices 列表。

---

## Task 6: 集成验证

1. `cd /root/git_code/nanobot && python3 -m pytest tests/ -x -q` — 全量测试通过
2. 本地启动验证：
   - `/model` → 显示当前状态
   - `/model anthropic/k2p5` → 切换成功
   - `/model` → 显示 overridden 状态
   - `/model reset` → 恢复默认
   - Discord 端 `/model` → 下拉框出现三个模型 + reset 选项

---

## 变更摘要

| 文件 | 变更类型 | 行数估算 |
|------|----------|----------|
| `agent/loop.py` | 修改 | +30 |
| `nanobot.py` | 修改 | +2 |
| `command/builtin.py` | 修改 | +40 |
| `command/discord_slash.py` | 修改 | +25 |
| `channels/discord.py` | 修改 | +5 |
| `tests/command/test_model_command.py` | 新建 | ~120 |
| **合计** | | ~220 行 |
