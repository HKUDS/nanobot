# 多个实例

同时运行多个 nanobot 实例，并为它们使用独立的配置和运行时数据。使用 `--config` 作为主要入口点。如果希望为特定实例初始化或更新已保存的 workspace，可以在 `onboard` 期间传入 `--workspace`。

## 快速开始

如果希望每个实例从一开始就拥有专用的 workspace，请在引导期间同时传入 `--config` 和 `--workspace`。

**初始化实例：**

```bash
# Create separate instance configs and workspaces
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace
nanobot onboard --config ~/.nanobot-discord/config.json --workspace ~/.nanobot-discord/workspace
nanobot onboard --config ~/.nanobot-feishu/config.json --workspace ~/.nanobot-feishu/workspace
```

**配置每个实例：**

编辑 `~/.nanobot-telegram/config.json`、`~/.nanobot-discord/config.json` 等文件，为它们设置不同的 channel 配置。在 `onboard` 期间传入的 workspace 会保存到每个 config 中，作为该实例的默认 workspace。

**运行实例：**

```bash
# Check one instance before starting it
nanobot status --config ~/.nanobot-telegram/config.json

# Instance A - Telegram bot
nanobot gateway --config ~/.nanobot-telegram/config.json

# Instance B - Discord bot
nanobot gateway --config ~/.nanobot-discord/config.json

# Instance C - Feishu bot with custom port
nanobot gateway --config ~/.nanobot-feishu/config.json --port 18792
```

## 路径解析

使用 `--config` 时，nanobot 会根据 config 文件的位置派生其运行时数据目录。workspace 仍然来自 `agents.defaults.workspace`，除非使用 `--workspace` 覆盖它。

要在本地针对其中一个实例打开 CLI session：

```bash
nanobot agent -c ~/.nanobot-telegram/config.json -m "Hello from Telegram instance"
nanobot agent -c ~/.nanobot-discord/config.json -m "Hello from Discord instance"

# Open the browser workbench for a specific instance
nanobot webui -c ~/.nanobot-telegram/config.json

# Optional one-off workspace override
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test
```

> `nanobot agent` 使用选定的 workspace/config 启动本地 CLI agent。它不会连接到已运行的 `nanobot gateway` 进程，也不会通过该进程进行代理。

| 组件 | 解析来源 | 示例 |
|-----------|---------------|---------|
| **Config** | `--config` 路径 | `~/.nanobot-A/config.json` |
| **Workspace** | `--workspace` 或 config | `~/.nanobot-A/workspace/` |
| **Cron Jobs** | workspace 目录 | `~/.nanobot-A/workspace/cron/` |
| **Media / runtime state** | config 目录 | `~/.nanobot-A/media/` |

## 工作原理

- `--config` 选择要加载的 config 文件
- 默认情况下，workspace 来自该 config 中的 `agents.defaults.workspace`
- 如果传入 `--workspace`，它会覆盖 config 文件中的 workspace

## 最小配置

1. 将基础 config 复制到新的实例目录中。
2. 为该实例设置不同的 `agents.defaults.workspace`。
3. 使用 `--config` 启动实例。

配置片段示例：

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot-telegram/workspace"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_BOT_TOKEN"
    }
  },
  "gateway": {
    "host": "127.0.0.1",
    "port": 18790
  }
}
```

复制的基础 config 可以继续使用相同的 `modelPresets` 和 `agents.defaults.modelPreset`。如果此实例需要使用不同的 model，请添加另一个 preset，并将 `agents.defaults.modelPreset` 设置为该 preset 的名称。

启动独立实例：

```bash
nanobot status --config ~/.nanobot-telegram/config.json
nanobot gateway --config ~/.nanobot-telegram/config.json
nanobot gateway --config ~/.nanobot-discord/config.json
```

每个 gateway 实例还会在 `gateway.host:gateway.port` 上提供一个轻量级 HTTP 健康检查端点。默认情况下，gateway 绑定到 `127.0.0.1`，因此除非明确将 `gateway.host` 设置为面向公共网络或 LAN 的地址，否则该端点仅限本地访问。

- `GET /health` 返回 `{"status":"ok"}`
- 其他路径返回 `404`

需要时，可以在一次性运行中覆盖 workspace：

```bash
nanobot gateway --config ~/.nanobot-telegram/config.json --workspace /tmp/nanobot-telegram-test
```

## 常见使用场景

- 为 Telegram、Discord、Feishu 和其他平台运行独立 bot
- 隔离测试实例和生产实例
- 为不同团队使用不同的 model 或 provider
- 使用独立的 config 和运行时数据为多个租户提供服务

## 注意事项

- 如果实例同时运行，每个实例必须使用不同的端口
- 如果希望隔离 memory、sessions 和 skills，请为每个实例使用不同的 workspace
- `--workspace` 会覆盖 config 文件中定义的 workspace
- Cron jobs 存储在活动 workspace 中；运行时 media/state 根据 config 目录派生
