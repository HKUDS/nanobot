# 聊天内命令

这些命令可在聊天渠道和交互式代理会话中使用：

| 命令 | 描述 |
|---------|-------------|
| `/new` | 停止当前任务并开始新对话 |
| `/stop` | 停止当前任务 |
| `/restart` | 重启机器人 |
| `/status` | 显示机器人状态 |
| `/model` | 显示当前模型和可用模型预设 |
| `/model <preset>` | 为当前会话切换并持久化模型预设 |
| `/dream` | 立即运行 Dream 记忆整合 |
| `/dream-log` | 显示最新的 Dream 记忆变更 |
| `/dream-log <sha>` | 显示指定的 Dream 记忆变更 |
| `/dream-restore` | 列出最近的 Dream 记忆版本 |
| `/dream-restore <sha>` | 将记忆恢复到指定变更之前的状态 |
| `/dream-prompt` | 显示 Dream 如何被引导以处理记忆 |
| `/dream-prompt init` | 在 `prompts/dream.md` 创建可编辑的 Dream 记忆指南 |
| `/skill` | 列出已启用的技能及其描述 |
| `/trigger` | 显示本地触发器用法 |
| `/trigger <name>` | 为当前聊天/会话创建命名本地触发器 |
| `/pairing` | 列出待处理的配对请求 |
| `/pairing approve <code>` | 批准配对代码 |
| `/pairing deny <code>` | 拒绝待处理的配对请求 |
| `/pairing revoke <user_id>` | 在当前渠道撤销先前已批准的用户 |
| `/pairing revoke <channel> <user_id>` | 在指定渠道撤销先前已批准的用户 |
| `/help` | 显示可用的聊天内命令 |

## 配对

当有人向机器人发送私信但不在允许列表中时，无论是新用户，还是新渠道上的现有用户，nanobot 都会自动回复一个在 10 分钟后过期的**配对代码**（如 `ABCD-EFGH`）。要授予其访问权限：

```text
/pairing approve ABCD-EFGH
```

要查看谁正在等待，请使用 `/pairing`。要在之后移除某人，请使用 `/pairing revoke <user_id>`，你可以在 `/pairing list` 输出中找到用户 ID。

有关完整设置指南，请参阅[配置：配对](configuration-zh.md#pairing)。

## 模型预设

使用 `/model` 检查当前运行时模型：

```text
/model
```

响应会显示当前会话的模型和预设，以及可用的预设名称。命名预设来自顶层 `modelPresets` 配置，是配置模型选择的推荐方式。`default` 始终可用，并表示直接 `agents.defaults.*` 字段中的模型设置。

要为后续轮次切换预设：

```text
/model fast
/model deep
/model default
```

预设名称来自顶层 `modelPresets` 配置。切换仅影响当前会话，并会将选择持久化在该会话中，因此后续轮次会在进程重启后继续使用它。它不会重写 `config.json`，不会更改其他会话，也不会修改进行中轮次已捕获的模型。没有保存选择的会话会遵循 `agents.defaults.modelPreset`（若省略它，则使用隐式的 `default` 预设）。有关设置详情，请参阅[配置：模型预设](configuration-zh.md#model-presets)。

## 本地触发器

当本地脚本或其他服务需要在稍后向当前聊天/会话发送消息时，请使用 `/trigger <name>`。必须提供名称；单独使用
`/trigger` 只会显示用法提示。

在未来消息应到达的聊天中创建触发器：

```text
/trigger PR review
```

nanobot 会回复一个触发器 ID 以及如下形式的命令：

```bash
nanobot trigger trg_8K4P2Q9X "Review PR #4502"
```

将 `"Review PR #4502"` 替换为你希望 nanobot 接收的消息。该
触发器绑定到其创建时所在的会话，因此消息会返回到同一个聊天。请保持 `nanobot gateway` 运行，以便传递触发器消息。触发器消息会以你传递给 CLI 的消息启动记录在该
会话中的自动化轮次；它不会被视为普通用户消息。如果该会话已经在运行一个轮次，触发器会等待
会话空闲，而不会被注入到活动轮次中。

触发器传递会存储在工作区中，直到其关联的代理轮次
成功完成。如果网关在认领一次传递后但在
轮次完成前退出，则下次网关启动时会将该传递重新排队。这是一个
至少一次的本地队列：如果进程在不合适的时机
退出，一次传递可能会运行多次，因此外部脚本应确保重复的触发器
消息是安全的。如果传递到达代理且代理轮次失败，
该传递会在 Automations 中标记为失败，而不会无限重试。

对于较长或生成的内容，请省略消息参数并通过管道传入 stdin：

```bash
printf '%s\n' "Review the latest failed CI job" | nanobot trigger trg_8K4P2Q9X
```

如果外部 webhook 应唤醒 nanobot，请运行自己的小型 webhook
服务，并在其构建最终消息后调用触发器命令：

```bash
nanobot trigger <trigger-id> "<message>"
```

如果你运行多个 nanobot 实例，请传递网关使用的相同配置或工作区
选择器：

```bash
nanobot trigger --config ./bot-a/config.json trg_8K4P2Q9X "Nightly report"
nanobot trigger --workspace ./bot-a/workspace trg_8K4P2Q9X "Nightly report"
```

通过 WebUI 的 Automations 视图管理触发器。你可以在那里搜索、暂停/恢复、
重命名、删除以及复制触发器命令。一个会话可以有多个
触发器，正如它可以有多个计划自动化任务一样。

有关本地触发器如何与计划自动化任务、心跳和网关传递配合使用，请参阅
[Automations](automations-zh.md)。

## 周期性任务

周期性后台检查由工作区中的 `HEARTBEAT.md` 驱动（`~/.nanobot/workspace/HEARTBEAT.md`）。当 `nanobot gateway` 启动时，默认会注册一个受保护的心跳 cron 作业。每 30 分钟，该作业会检查该文件；如果在 `## Active Tasks` 下发现任务，代理便会执行它们，并且仅将通过通知门控的结果传递到你最近活跃的聊天渠道。如果没有活动任务，或者结果只是常规内容且没有有用信息可报告，则会静默跳过心跳。

将心跳用于通常应保持安静的重复检查。用户创建的 cron 作业有所不同：它们会作为计划轮次在其创建所在的聊天/会话中运行，并通常将结果传回该渠道。

**设置：**编辑 `~/.nanobot/workspace/HEARTBEAT.md`（由 `nanobot onboard` 自动创建）：

```markdown
## Active Tasks

- Check weather forecast and notify me only if storms are expected
- Scan inbox for urgent emails and notify me if any are found
```

代理也可以自行管理此文件，要求它“添加周期性后台检查”或“定期检查此项，但仅在有变化时通知我”，它会为你更新 `HEARTBEAT.md`。完成的任务应从文件中删除，而不是移到其他部分。

你可以在 `~/.nanobot/config.json` 中更改间隔或禁用内置心跳：

```json
{
  "gateway": {
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800
    }
  }
}
```

心跳作业在 `cron(action="list")` 中显示为 `heartbeat`，但它由系统管理，无法使用 `cron` 工具删除。要停止它，请将 `gateway.heartbeat.enabled` 设为 `false`，然后重启网关。

> **注意：**网关必须正在运行（`nanobot gateway`），并且你必须至少与机器人聊天一次，以便它知道应传递到哪个渠道。
