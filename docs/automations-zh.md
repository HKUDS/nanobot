# 自动化

<!-- Meta description: 创建、运行和管理 nanobot 定时自动化、本地触发器以及由 heartbeat 支持的后台检查。 -->

自动化是在关联主题中稍后运行的智能体轮次。当 nanobot 应在无人主动输入时完成工作时使用它们：提醒、定期检查、夜间摘要、CI 跟进、本地脚本报告或 webhook 驱动的事件。

从结果应出现的聊天渠道或 WebUI 主题创建自动化。这样 nanobot 可以保留正确的会话历史、工作区和回复目标。

## 选择自动化类型

| 类型 | 启动来源 | 最适合 | 创建方式 |
|---|---|---|---|
| 定时自动化 | 时间、间隔或 cron 表达式 | 定期提醒、定时摘要、一次性的未来任务 | 在目标主题中请求 nanobot 使用 `cron` 工具进行安排 |
| 本地触发器 | 本地 `nanobot trigger ...` 命令 | CI 作业、webhook、shell 脚本、生成的报告 | 在目标主题中使用 `/trigger <name>` |
| Heartbeat | 受保护的系统计划 | 仅应报告有用结果的静默定期检查 | 编辑 `<workspace>/HEARTBEAT.md` |

两种由用户创建的自动化类型是定时自动化和本地触发器。Heartbeat 使用相同的后台服务，但由系统管理，且受到保护，无法通过常规自动化编辑进行更改。

## 创建之前

保持 `nanobot gateway` 运行。网关负责聊天应用、WebUI 主题、定时自动化、本地触发器、heartbeat 和 Dream 作业的后台投递。

网关与任何发送本地触发器消息的进程应使用相同的工作区和配置。若运行多个 nanobot 实例，请向 `nanobot trigger` 传递匹配的 `--config` 或 `--workspace` 选项。

请从目标主题创建每个自动化。未关联主题的自动化无法从 WebUI 启用或运行，因为 nanobot 无法确定将该轮次投递到何处。

## 定时自动化

定时自动化由智能体的 `cron` 工具创建。实际上，请在目标聊天渠道或 WebUI 主题中向 nanobot 提出请求：

```text
Every weekday at 9am, check open pull requests and summarize blockers here.
```

或：

```text
Tomorrow at 4pm, remind me to send the release notes.
```

cron 工具支持间隔计划、cron 表达式和一次性定时任务。Cron 表达式可以包含 IANA 时区，例如 `America/Vancouver`；否则 nanobot 使用运行时默认时区。

定时自动化通常将结果投递回其创建所在的会话。请将其用于应按可预测的计划运行并报告每次运行结果的工作。

对于除非存在有用信息才应报告的后台检查，请使用 heartbeat，而不是用户创建的定时自动化。

## 本地触发器

本地触发器允许本地脚本或外部服务稍后向特定的 nanobot 会话发送消息。

请从未来消息应到达的聊天渠道或 WebUI 主题创建触发器：

```text
/trigger PR review
```

nanobot 会回复一个触发器 ID 和类似以下形式的命令：

```bash
nanobot trigger trg_8K4P2Q9X "Review PR #4502"
```

将带引号的文本替换为 nanobot 应接收的消息。对于生成的或较长的内容，请通过 stdin 管道传入：

```bash
generate-report | nanobot trigger trg_8K4P2Q9X
```

对于多个实例，请使用与网关相同的配置或工作区选择器：

```bash
nanobot trigger --config ./bot-a/config.json trg_8K4P2Q9X "Nightly report"
nanobot trigger --workspace ./bot-a/workspace trg_8K4P2Q9X "Nightly report"
```

nanobot 不为本地触发器提供内置的公共 webhook 接收器。若 GitHub、CI 或其他外部系统应唤醒 nanobot，请运行您自己的小型 webhook 服务，并在其构建最终消息后调用 `nanobot trigger`。

## Heartbeat

Heartbeat 用于通常应保持静默的定期工作区检查。它会读取 `<workspace>/HEARTBEAT.md`，执行活跃任务，并且仅将有用或可操作的结果发送到最近活跃的聊天目标。

将 heartbeat 用于诸如“监视此仓库中的重要故障”或“定期检查此工作区，并且仅在需要采取行动时通知我”的检查。每次运行都应生成可见提醒或报告时，请改用定时自动化。

`nanobot gateway` 启动时默认启用 Heartbeat。请在 [`configuration.md#gateway-heartbeat`](configuration-zh.md#gateway-heartbeat) 中进行配置。

## 管理自动化

使用 WebUI 自动化视图可以：

- 按全部、活跃、已暂停、需要注意或系统作业筛选；
- 按任务名称、消息、触发器命令、关联主题、计划或状态搜索；
- 按下次运行、上次运行、更新时间或名称排序；
- 立即运行定时自动化；
- 暂停或恢复、重命名或删除用户创建的自动化；
- 复制本地触发器的 CLI 命令；
- 在不更改受保护系统自动化的情况下检查它们。

本地触发器没有 WebUI 的“立即运行”操作，因为每次运行都需要一条消息。从 WebUI 复制 `nanobot trigger ...` 命令，并将 `"message"` 替换为应投递的内容。

## 投递和可靠性

自动化投递是工作区本地的。定时作业和本地触发器投递使用与网关相同的工作区。

本地触发器消息会写入持久队列。若网关尚未运行，消息会在该工作区中等待。若关联主题已在运行一个轮次，触发器会等待会话变为空闲，而不会被注入当前活跃轮次。

本地触发器队列提供至少一次投递，而非恰好一次投递。若网关在认领投递后、关联轮次完成前退出，则下一次网关启动会将该投递重新入队。外部脚本应确保重复的触发器消息是安全的。若投递到达智能体但该轮次失败，则该投递会标记为失败，而不会无限重试。

每次本地触发器投递都会在 `<workspace>/triggers/runs` 下写入审计记录。每个工作区只运行一个网关消费者；本地队列不是分布式多消费者队列。

## 常见模式

对于夜间报告，请从目标主题提出请求：

```text
Every night at 9pm, review today's workspace changes and summarize anything I should handle tomorrow.
```

对于 CI 跟进，请创建一次触发器：

```text
/trigger CI follow-up
```

然后让您的 CI 或 webhook 适配器调用：

```bash
nanobot trigger <trigger-id> "Build failed on main. Inspect the logs and suggest the next fix."
```

对于本地报告脚本：

```bash
generate-report | nanobot trigger <trigger-id>
```

## 故障排除

若自动化未运行，请检查 `nanobot gateway` 是否正在运行、自动化是否已启用，以及它是否从关联主题创建。

若本地触发器一直等待，请确认该命令使用与网关相同的工作区或配置。

若重启后某条触发器消息出现两次，请将其视为预期的至少一次投递，并确保外部消息具有幂等性。

若需要编辑、暂停、恢复、重命名、删除或检查自动化，请使用 WebUI 自动化视图。

## 相关文档

- [`webui.md#automations`](webui-zh.md#automations)：浏览器管理视图
- [`chat-commands.md#local-triggers`](chat-commands-zh.md#local-triggers)：`/trigger`
- [`cli-reference.md#local-triggers`](cli-reference-zh.md#local-triggers)：`nanobot trigger`
- [`configuration.md#gateway-heartbeat`](configuration-zh.md#gateway-heartbeat)：heartbeat 设置
- [`guides/long-running-ai-agent.md`](guides/long-running-ai-agent-zh.md)：长期运行的智能体工作
