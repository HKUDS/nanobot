# Implementation Plan: Discord Slash Commands

> Spec: https://ai-html.haibingpt.work/nanobot-discord-slash-command-spec.html
> Date: 2026-04-01
> Status: Draft

---

## Overview

为 nanobot 接入 Discord Application Commands（slash commands），分两个 phase 实现。Phase 1 覆盖 builtin commands，Phase 2 扩展到 skills。

所有 task 标注依赖关系，无依赖的 task 可并行执行。

---

## Phase 1: Builtin Slash Commands

### Task 1: CommandContext 扩展
**文件**: `nanobot/command/router.py`
**依赖**: 无
**改动量**: ~5 行

在 `CommandContext` dataclass 中新增两个可选字段：

```python
interaction_id: str | None = None
interaction_token: str | None = None
```

这两个字段由 discord interaction handler 填充，其余入口保持 None。handler 返回的 `OutboundMessage` 需将这两个值透传到 `metadata` 中。

**验证**: 现有 builtin command 测试不受影响（字段有默认值）。

---

### Task 2: DiscordConfig 扩展
**文件**: `nanobot/channels/discord.py` (DiscordConfig class, line 25-34)
**依赖**: 无
**改动量**: ~3 行

在 `DiscordConfig` 中新增：

```python
slash_commands: bool = True  # 是否注册 slash commands
```

**验证**: 默认值 True，现有 config 无需修改即可启用。

---

### Task 3: 命令注册模块
**文件**: `nanobot/command/discord_slash.py` (**新增**)
**依赖**: 无
**改动量**: ~80 行

**职责**: 构造命令定义 + 调 Discord API 注册

核心函数：

1. `extract_app_id(token: str) -> str`
   - 从 bot token 第一段 base64 decode 得到 application_id
   - 纯计算，无 IO

2. `build_builtin_commands() -> list[dict]`
   - 返回 builtin commands 的 Discord command payload 列表
   - 硬编码 5 个命令：status, new, stop, help, tts
   - tts 带一个 `mode` string choice 参数 (on/off)

3. `async register_guild_commands(http, app_id, guild_id, token, commands) -> None`
   - `PUT /applications/{app_id}/guilds/{guild_id}/commands`
   - 批量覆盖，幂等
   - 失败 log warning，不 raise

4. `async register_all_commands(http, token, guild_ids) -> None`
   - 组合函数：extract_app_id → build_builtin_commands → 对每个 guild 注册
   - guild_ids 来自调用方

**文件结构**:

```python
"""Discord slash command registration."""

import base64
from dataclasses import dataclass, field
import httpx
from loguru import logger

DISCORD_API_BASE = "https://discord.com/api/v10"


def extract_app_id(token: str) -> str:
    """从 bot token 解码 application id。"""
    ...

def build_builtin_commands() -> list[dict]:
    """构造 builtin commands 的 Discord API payload。"""
    ...

async def register_guild_commands(...) -> None:
    """批量覆盖 guild slash commands。"""
    ...

async def register_all_commands(...) -> None:
    """注册所有命令到所有已知 guild。"""
    ...
```

**验证**: 单元测试 `extract_app_id` 和 `build_builtin_commands`（纯函数）。

---

### Task 4: Interaction 处理 — 接收层
**文件**: `nanobot/channels/discord.py`
**依赖**: Task 1, Task 2
**改动量**: ~45 行

四处改动：

**4a. 新增实例变量** (在 `__init__` 中, line ~58)

```python
self._app_id: str | None = None
```

**4b. Gateway loop 新增分支** (在 `_gateway_loop` 中, line ~260 之后)

```python
elif op == 0 and event_type == "INTERACTION_CREATE":
    await self._handle_interaction(payload)
```

**4c. READY 事件中提取 guild ids + 注册命令** (line ~253)

```python
# 在 READY handler 中
self._app_id = extract_app_id(self.config.token)
if self.config.slash_commands:
    guild_ids = [g["id"] for g in payload.get("guilds", [])]
    asyncio.create_task(register_all_commands(
        self._http, self.config.token, guild_ids
    ))
```

**4d. 新增 `_handle_interaction` 方法**

```python
async def _handle_interaction(self, payload: dict) -> None:
    """处理 INTERACTION_CREATE 事件。"""
    # 1. 只处理 type=2 (APPLICATION_COMMAND)
    # 2. 提取 sender info, channel_id, guild_id
    # 3. 权限检查 (is_allowed)，未授权直接 type=4 回复
    # 4. 发 deferred ack (type=5)
    # 5. 从 data.name + data.options 构造 "/{name} {args}" 文本
    # 6. 构造 metadata（含 interaction_id, interaction_token）
    # 7. 调 self._handle_message() 推入 bus
```

**关键设计**: 还原为文本命令格式入 bus，AgentLoop 零感知。

**验证**: 在 Discord 中输入 `/status`，观察 deferred → followup 流程。

---

### Task 5: Interaction 处理 — 响应层
**文件**: `nanobot/channels/discord.py`
**依赖**: Task 1, Task 4
**改动量**: ~30 行

两处改动：

**5a. `send()` 方法入口分流** (line ~101)

在 `send()` 方法开头，检测 metadata 中的 interaction_token：

```python
interaction_token = (msg.metadata or {}).get("interaction_token")
if interaction_token:
    await self._send_interaction_followup(msg, interaction_token)
    return
# ... 现有逻辑不变
```

**5b. 新增 `_send_interaction_followup` 方法**

```python
async def _send_interaction_followup(
    self, msg: OutboundMessage, token: str
) -> None:
    """通过 interaction webhook followup 发送。"""
    url = f"{DISCORD_API_BASE}/webhooks/{self._app_id}/{token}"
    headers = {"Authorization": f"Bot {self.config.token}"}
    
    # TTS 处理（复用现有逻辑）
    # 文件附件 followup
    # 文本分片 followup
    # 降级：token 过期时回退到 channel message
```

**注意**: followup 使用 `POST /webhooks/{app_id}/{token}`，不需要 `interaction_id`。TTS 逻辑从现有 `send()` 中提取复用。

**验证**: `/status` 返回正确内容；长消息正确分片；TTS 附件正常。

---

### Task 6: Deferred 响应辅助方法
**文件**: `nanobot/channels/discord.py`
**依赖**: 无
**改动量**: ~15 行

新增：

```python
async def _interaction_respond(
    self, interaction_id: str, interaction_token: str,
    type: int, content: str = "",
) -> bool:
    """发送 interaction callback 响应。返回是否成功。"""
    ...
```

被 Task 4d 的 `_handle_interaction` 调用。

**验证**: deferred ack 在 Discord UI 显示"正在思考"。

---

### Task 7: OutboundMessage metadata 透传
**文件**: `nanobot/agent/loop.py`
**依赖**: Task 1
**改动量**: ~8 行

确保 `_dispatch` 方法中构造 `OutboundMessage` 时，将 `InboundMessage.metadata` 中的 `interaction_id` 和 `interaction_token` 透传到 `OutboundMessage.metadata`。

检查点：
- `_dispatch` 中最终构造 OutboundMessage 的位置
- `cmd_*` handler 构造 OutboundMessage 的位置（builtin.py）

**当前状态**: `builtin.py` 中的 handler 直接构造 `OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=...)`，**不带 metadata**。

**修改方案**: 在 `CommandContext` 中添加一个 helper：

```python
def make_response(self, content: str, **kwargs) -> OutboundMessage:
    """构造带 interaction 透传的 OutboundMessage。"""
    metadata = {}
    if self.interaction_id:
        metadata["interaction_id"] = self.interaction_id
        metadata["interaction_token"] = self.interaction_token
    return OutboundMessage(
        channel=self.msg.channel,
        chat_id=self.msg.chat_id,
        content=content,
        metadata=metadata,
        **kwargs,
    )
```

**替代方案**: 也可以在 `builtin.py` 中逐个改 handler。但 `make_response` 更干净，消除重复。

**验证**: slash command 的响应通过 followup 发送而非 channel message。

---

### Task 8: Builtin handlers 适配
**文件**: `nanobot/command/builtin.py`
**依赖**: Task 7
**改动量**: ~12 行

将 5 个 handler 中的 `OutboundMessage(channel=..., chat_id=..., content=...)` 替换为 `ctx.make_response(content)`。

改动的 handler：
- `cmd_stop` (line ~24)
- `cmd_restart` (line ~37)
- `cmd_status` (line ~55)
- `cmd_new` (line ~73)
- `cmd_tts` (line ~87)
- `cmd_help` (line ~107)

**注意**: `cmd_status` 和 `cmd_help` 有额外的 `metadata={"render_as": "text"}`，需要在 `make_response` 中支持 metadata merge。

**验证**: 所有 builtin commands 通过文本和 slash command 两种方式都能正常工作。

---

### Phase 1 验证清单

| 测试项 | 方法 |
|--------|------|
| Bot 启动后 Discord 命令列表出现 | 输入 `/` 查看 |
| `/status` slash command 返回正确 | 点击执行 |
| `/new` 重置 session | 执行后发消息验证 |
| `/stop` 取消任务 | 启动长任务后执行 |
| `/tts on/off` 参数传递 | 选择参数执行 |
| 未授权用户被拒绝 | 用非 allow_from 账号测试 |
| 文本命令不受影响 | 直接输入 `/status` 文本 |
| 命令注册失败不阻塞启动 | 断网启动测试 |

---

## Phase 2: Skill Slash Commands

### Task 9: Skill metadata 扩展
**文件**: skill 的 `SKILL.md` frontmatter
**依赖**: Phase 1 完成
**改动量**: 约定变更，无代码改动

在 SKILL.md frontmatter 中新增可选字段：

```yaml
---
name: weather
description: Get weather forecast
command: true
command_name: weather  # 可选，默认用 name
---
```

---

### Task 10: Skill 命令构造
**文件**: `nanobot/command/discord_slash.py`
**依赖**: Task 3, Task 9
**改动量**: ~30 行

新增函数：

```python
def build_skill_commands(skills_loader: SkillsLoader) -> list[dict]:
    """扫描 skills，为 command=true 的构造 slash command payload。
    
    每个 skill command 带一个可选的 input 文本参数。
    """
```

修改 `register_all_commands`，合并 builtin + skill commands 后批量注册。

**验证**: 标记了 `command: true` 的 skill 出现在 Discord 命令列表。

---

### Task 11: Skill 命令路由
**文件**: `nanobot/agent/loop.py`
**依赖**: Task 10
**改动量**: ~15 行

当 `CommandRouter.dispatch()` 返回 None（不是 builtin command），且消息来自 slash command（metadata 有 interaction_token），将消息内容从 `/{skill_name} {input}` 格式转为对 agent 的自然语言指令：

```
"Use the {skill_name} skill: {input}"
```

然后走正常的 agent 处理流程。

**替代方案**: 也可以在 `_handle_interaction` 阶段就做转换。但在 loop 层做更灵活——保留了 CommandRouter 未来扩展的可能性。

**验证**: `/weather 北京` → agent 调用 weather skill → 返回结果。

---

### Task 12: 命令热注册
**文件**: `nanobot/command/discord_slash.py`
**依赖**: Task 10
**改动量**: ~10 行

在 `register_all_commands` 中保存已注册的命令列表。提供一个 `async reregister_if_changed()` 方法：

- 对比当前 skill 列表与上次注册的列表
- 有变化时重新 PUT

由 `/restart` 命令触发。不做真正的热更新（复杂度不值得）。

**验证**: 新增 skill 后 `/restart`，新命令出现。

---

## Phase 2 验证清单

| 测试项 | 方法 |
|--------|------|
| Skill 出现在命令列表 | 标记 command: true 后重启 |
| Skill command 带 input 参数 | `/weather input:北京` |
| Skill command 无参数 | `/weather` 直接执行 |
| 未标记的 skill 不出现 | 确认命令列表 |
| Skill 增减后重启同步 | 增删 skill 后 `/restart` |

---

## 执行顺序

```
Phase 1 (可并行的标为同一行):

  Task 1 (router.py)  ─┐
  Task 2 (config)      ├── 并行，无依赖
  Task 3 (注册模块)     ├──
  Task 6 (deferred)    ─┘
         │
         ▼
  Task 4 (接收层)  ── 依赖 1, 2
  Task 7 (透传)    ── 依赖 1
         │
         ▼
  Task 5 (响应层)  ── 依赖 1, 4
  Task 8 (handlers) ── 依赖 7
         │
         ▼
  Phase 1 集成测试

Phase 2:

  Task 9 (metadata 约定) ─┐
                           ├── 顺序
  Task 10 (命令构造)      ─┘
         │
         ▼
  Task 11 (路由)
  Task 12 (热注册)
         │
         ▼
  Phase 2 集成测试
```

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| Bot token 格式变化导致 app_id 提取失败 | 加 fallback：调 `/oauth2/applications/@me` API |
| Guild command 注册 rate limit | 启动时一次性 PUT，不频繁调用 |
| Interaction token 15分钟过期 | followup 失败时降级为 channel message |
| 文本命令和 slash command 重复触发 | slash command 走 INTERACTION_CREATE，文本走 MESSAGE_CREATE，天然隔离 |

---

## 不做的事

- ❌ Button / Select Menu / Modal 交互
- ❌ 全局命令注册（用 Guild 命令）
- ❌ 命令权限精细控制（沿用 allow_from）
- ❌ Autocomplete 交互（保持简单）
- ❌ Skill 结构化参数（统一用 input 文本）
