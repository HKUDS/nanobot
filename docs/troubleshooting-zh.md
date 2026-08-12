# 故障排除

使用此页面定位故障所在。先从能证明最多问题的最小范围开始：先本地 CLI，然后 gateway，最后是 WebUI 或聊天应用。

## 快速诊断顺序

按以下顺序运行：

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

然后，仅当 CLI 可用时：

```bash
nanobot gateway
```

这会将故障分离到不同层级：

| 层级 | 它证明什么 |
|---|---|
| `nanobot --version` | 安装与 shell 命令发现 |
| `nanobot status` | 配置路径、workspace、环境引用，以及当前 provider/model 配置 |
| `nanobot agent -m "Hello!"` | 配置加载、provider/model 访问、workspace 写入和 agent 循环 |
| `nanobot gateway` | channel 启动、cron 系统任务、heartbeat、WebUI/WebSocket 和健康检查端点 |

如果 `nanobot agent -m "Hello!"` 失败，请先修复它，再调试 WebUI、Telegram、Discord、Docker、systemd 或任何聊天应用。

`nanobot status` 不会调用 model。如果 provider/model 设置不完整，它会指向
WebUI **Settings → Models** 或 CLI 设置向导，然后打印再次检查所需的命令。

## 如何读取 `nanobot status`

`nanobot status` 不会调用 model。它会检查选定的配置和 workspace，
解析环境引用，并验证当前 provider/model 所需的本地设置，
但不会构造 provider client。

输出形式如下：

```text
nanobot Status

Config: /path/to/config.json ✓
Workspace: /path/to/workspace ✓
Model: provider/model-name (preset: primary)
Agent: ✓ provider/model configuration is ready
Provider A: not set
Provider B: ✓
Local Provider: ✓ http://localhost:11434/v1
OAuth Provider: ✓ (OAuth)
```

可按如下方式解读：

| 行 | 正常迹象 | 如果看起来不对该怎么做 |
|---|---|---|
| `Config` | 它指向你要使用的配置文件，并显示 `✓`。 | 运行 `nanobot onboard`，或者在测试非默认实例时向 `nanobot agent`、`gateway` 或 `serve` 传递 `--config`。 |
| `Workspace` | 它指向你要使用的 workspace，并显示 `✓`。 | 运行 `nanobot onboard`、创建文件夹、修复权限，或者在支持它的命令中传递 `--workspace`。 |
| `Model` | 它显示当前 model 或你预期的 preset 名称。 | 将 `agents.defaults.modelPreset` 设置为目标 preset，或者如果你在聊天 session 中切换过 model，请检查 `/model`。 |
| `Agent` | 它显示 `provider/model configuration is ready`。 | 按照打印出的 WebUI 或 CLI 设置路径操作，然后再次运行 `nanobot status`。 |
| Provider 行 | 当前 preset 使用的 provider 显示 `✓`、OAuth 标记或本地 URL。 | 先只配置当前 provider。未使用的 provider 显示 `not set` 是正常的。 |

如果 `nanobot status` 看起来正确，但 `nanobot agent -m "Hello!"` 失败，则安装和配置路径大概率没有问题。继续查看[Provider 和 Model 问题](#provider-and-model-problems)。

## 安装问题

安装检查和模块备用命令应使用同一个 Python 命令。在 macOS/Linux 上可能是 `python3`；在 Windows 上可能是 `python` 或 `py`。

| 症状 | 检查项 |
|---|---|
| `python: command not found` | 在 macOS/Linux 上尝试 `python3 --version`，或在 Windows 上尝试 `py --version`。然后将文档命令中的 `python` 替换为可用的命令。 |
| `curl: command not found` | macOS/Linux 单命令安装程序无法下载脚本。安装 curl，或使用手动隔离安装方式，例如 `uv tool install nanobot-ai` 或 `pipx install nanobot-ai`。 |
| 无法识别 `irm` | PowerShell 无法运行下载辅助命令。使用手动安装：`uv tool install nanobot-ai`、`pipx install nanobot-ai`，或在你控制的环境中执行 `py -m pip install nanobot-ai`。 |
| 无法下载 `raw.githubusercontent.com` | 你的网络、proxy 或 firewall 阻止了安装程序脚本下载。使用来自 PyPI 的手动安装，或者配置 proxy 后重新运行命令。 |
| `nanobot: command not found` | 使用模块形式，例如 `python -m nanobot ...`、`python3 -m nanobot ...` 或 `py -m nanobot ...`。使用相同的 Python 命令重新安装，或将该 Python 的 scripts 目录添加到 `PATH`。 |
| `No module named nanobot` | 你正在运行的 Python 与安装时使用的 Python 不同。运行 `python -m pip show nanobot-ai`、`python3 -m pip show nanobot-ai` 或 `py -m pip show nanobot-ai`，并与安装 nanobot 时使用的命令保持一致。 |
| `pip is not available` | 当安装程序使用虚拟环境时，它会尝试执行 `python -m ensurepip --upgrade`。如果失败，请为该 Python 安装 pip，或使用包含 pip 的 Python 安装程序/发行版。 |
| `externally-managed-environment` | 你的系统 Python 阻止全局 pip 安装。使用单命令安装程序、`uv tool install nanobot-ai`、`pipx install nanobot-ai`，或创建虚拟环境；不要为 nanobot 添加 `--break-system-packages`。 |
| 安装程序选择了错误的 Python | 在运行安装程序前设置 `PYTHON`，例如 `curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | PYTHON=python3 sh`，或在 PowerShell 命令前执行 `$env:PYTHON="py"`。 |
| 可编辑源码安装未更新 | 在仓库根目录中，使用开发时的 Python 命令再次运行 `python -m pip install -e .`，然后检查 `python -m nanobot --version` 或 `nanobot --version`。 |
| 缺少 WebUI 构建工具 | 它们仅用于 WebUI 开发。打包安装已包含 WebUI bundle。 |

## 配置问题

默认配置路径：

```text
~/.nanobot/config.json
```

默认 workspace 路径：

```text
~/.nanobot/workspace/
```

除非传递显式路径，否则 `nanobot status` 会读取默认配置。调试多个实例时，请在状态检查和运行时命令中使用相同的 `--config` 和 `--workspace`：

```bash
nanobot status --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot agent --config ./bot-a/config.json --workspace ./bot-a/workspace -m "Hello"
nanobot gateway --config ./bot-a/config.json --workspace ./bot-a/workspace
```

常见配置错误：

| 症状 | 检查项 |
|---|---|
| JSON 解析错误 | 验证逗号、花括号和引号。大多数文档示例都是需要合并的局部片段。 |
| 未知或缺少 provider | 使用 provider registry 名称，例如 `openrouter`、`anthropic`、`openai`、`ollama`、`vllm`、`lm_studio`；或在 `providers` 下定义自定义 OpenAI-compatible provider key，并从当前 preset 中引用完全相同的 key。 |
| snake_case 与 camelCase 混淆 | 两者都可接受，但文档使用 camelCase，因为 nanobot 使用 `apiKey`、`modelPresets`、`intervalS` 等别名写入配置。 |
| 环境变量错误 | `${VAR_NAME}` 引用会在启动时解析。请在运行 nanobot 前设置该变量。 |
| 已编辑配置但行为未改变 | 重启 `nanobot gateway`；长时间运行的进程会在启动时读取配置。 |

编辑配置后，检查获得 Agent 回复的最短路径：

```bash
nanobot status
```

要在不覆盖现有设置的情况下补全缺失默认值，请运行：

```bash
nanobot onboard --refresh
```

若要在重置和刷新之间进行交互式选择，请运行 `nanobot onboard`，并选择保留当前值且合并缺失默认值的选项。

## Provider 和 Model 问题

先在 CLI 中验证 provider：

```bash
nanobot agent -m "Hello!"
```

然后将你的配置与 [`providers.md`](providers-zh.md) 对比。

如果你需要已知可用的片段而不是诊断，请使用 [`provider-cookbook.md`](provider-cookbook-zh.md)。

| 症状 | 可能原因 |
|---|---|
| 401、unauthorized、invalid API key | key 缺失、已过期、粘贴时带有空白字符，或位于错误的 provider key 下。 |
| 找不到 Model | model ID 属于其他 provider 或 gateway。 |
| 无法推断 Provider | 在当前 preset 中固定 `modelPresets.<name>.provider`，不要使用 `"auto"`。对于旧版直接配置，请固定 `agents.defaults.provider`。 |
| 本地 model 连接被拒绝 | Ollama、vLLM、LM Studio 或其他本地 server 未运行，或者 `apiBase` 指向了错误端口。 |
| Bedrock 验证错误 | 检查 AWS region、凭据、model 访问权限、model ID，以及该 model 是否支持 Converse。 |
| OAuth provider 失败 | 运行对应的登录命令：`openai-codex`、`xai-grok` 或 `github-copilot`，通常附带 `--set-main`。 |
| Codex OAuth 需要 proxy | 在运行登录命令前设置 `providers.openaiCodex.proxy`。该 proxy 适用于登录、token 刷新和 Codex API 请求。 |
| Codex 登录在远程/headless 机器上运行 | 在 WebUI 中，在本地浏览器打开 ChatGPT；当 localhost callback 页面无法加载时，从地址栏复制完整的 `http://localhost:1455/auth/callback?...` URL，并粘贴到 WebUI 对话框中。通过 CLI 时，在本地打开打印出的 URL，并将相同的 callback URL 粘贴回 terminal。 |
| Codex 登录在 Docker 中运行 | 使用 `docker run -it` 启动 container，以便 OAuth 流程拥有交互式 terminal。 |
| Codex 表示某个 model 不受 ChatGPT account 支持 | 使用 provider `openai_codex` 和 Codex model，例如 `openai-codex/gpt-5.6-sol`。不要将 direct-API `openai/...` 前缀与 Codex OAuth 一起使用。 |
| Config 表示 `providers.openai_codex` 与内置 provider 冲突 | 在 `providers` 下仅保留规范的 `openaiCodex` settings key，并移除重复的 `openai_codex` key。model preset 的 `provider` 值仍为 `openai_codex`。 |
| xAI OAuth 需要 proxy | 在登录前设置 `providers.xaiGrok.proxy`。它适用于 OAuth 发现、token 交换/刷新和 Grok subscription 请求。 |
| xAI 登录在远程/headless 机器上运行 | 在 WebUI 中，在本地浏览器完成登录；如果 loopback redirect 无法到达 server，请将地址栏中的最终 URL 复制到 WebUI 对话框中。通过 CLI 时，以交互方式运行 `nanobot provider login xai-grok`，在其他位置打开打印出的 URL，并在提示时粘贴最终 callback URL 或 authorization code。 |
| xAI 返回 403 或 subscription access denied | 确认登录的 account 拥有符合条件的 X Premium / Grok subscription，然后再次运行 `nanobot provider login xai-grok`。此 provider 不使用 xAI API key 或 X Developer OAuth。 |
| xAI 返回 400 `invalid-argument` | 阅读附加在 provider 错误后的有界 `Response body`。仅当 xAI 的 model catalog 声明 `supportsBackendSearch` 时才会发送托管的 `x_search`；model ID `grok-4.5` 本身有效。 |
| 上游发布后 xAI model 或 X Search 停止工作 | 该集成遵循 Grok Build 的公开 OAuth/proxy client contract。如果 xAI 更改该 contract，请更新 nanobot。 |

## Langfuse 问题

Langfuse tracing 是可选的，并由环境变量控制。

| 症状 | 检查项 |
|---|---|
| `LANGFUSE_SECRET_KEY is set but langfuse is not installed` | 在运行 nanobot 的同一 Python 环境中安装 `langfuse`，然后重启进程。 |
| 未出现 traces | 在启动 nanobot 前设置 `LANGFUSE_SECRET_KEY`、`LANGFUSE_PUBLIC_KEY` 和 `LANGFUSE_BASE_URL`。 |
| Langfuse project 或 region 错误 | 检查 key pair 和 `LANGFUSE_BASE_URL` 是否来自同一个 Langfuse project/region。 |
| 仅部分 providers 有 trace | Langfuse tracing 适用于 OpenAI-compatible provider 调用；原生 providers 可能不会使用该 client 路径。 |

有关设置命令，请参阅 [`configuration.md#langfuse-observability`](configuration-zh.md#langfuse-observability)。
## Gateway 问题

WebUI、聊天应用、heartbeat、Dream 和长时间运行的 channel 连接需要 `nanobot gateway`。

默认端口：

| 界面 | 默认值 |
|---|---|
| Gateway 健康检查端点 | `http://127.0.0.1:18790/health` |
| WebUI/WebSocket channel | `http://127.0.0.1:8765` |
| OpenAI 兼容 API（`nanobot serve`） | `http://127.0.0.1:8900` |

常见 gateway 检查：

```bash
nanobot gateway --verbose
```

| 症状 | 检查项 |
|---|---|
| 端口已被占用 | 为相关命令更改 `gateway.port`、`channels.websocket.port` 或 `--port` CLI 标志。 |
| WebUI 在 `18790` 打开但未显示有用内容 | 打开 `8765`；`18790` 是健康检查端点。 |
| 配置更改被忽略 | 重启 gateway。 |
| 启动停在 `Installing optional feature` | 已启用的 channel 缺少其 Python 依赖项。参见[可选 Channel 依赖安装缓慢](#slow-optional-channel-dependency-installation)。 |
| Heartbeat 从不运行 | 保持 gateway 运行，在 `<workspace>/HEARTBEAT.md` -> `## Active Tasks` 下添加任务，并确保 `gateway.heartbeat.enabled` 为 true。 |
| 切换 workspace 后 Cron 作业消失 | Cron 作业按 workspace 作用域存储在 `<workspace>/cron/jobs.json`；请检查是否正在使用预期的 workspace。 |

### 可选 Channel 依赖安装缓慢

在加载已启用的 channel 之前，gateway 会检查其 channel 清单所声明的依赖项。通常在启用 channel 时，CLI 和 WebUI 会安装这些依赖项。启动期间的安装是一种恢复路径，用于处理已启用配置的 Python 环境不再具有所需软件包的情况，例如手动编辑配置、升级 nanobot，或重新创建隔离的 `uv tool`/`pipx` 环境之后。gateway 会等待安装完成，以免静默跳过已启用的 channel；一旦依赖项存在，后续启动将跳过安装。

如果你所在地区访问 PyPI 很慢，请将 pip 配置为使用受信任的软件包索引。安装程序遵循标准 `PIP_INDEX_URL` 环境变量，即使 nanobot 本身是使用 `uv tool` 安装的：

```bash
PIP_INDEX_URL=https://your-trusted-mirror.example/simple nanobot gateway
```

对于由 `nanobot gateway install-service` 创建的 systemd 用户服务，添加一个 drop-in：

```bash
systemctl --user edit nanobot-gateway.service
```

```ini
[Service]
Environment="PIP_INDEX_URL=https://your-trusted-mirror.example/simple"
```

然后重新加载并重启服务：

```bash
systemctl --user daemon-reload
systemctl --user restart nanobot-gateway.service
```

对于系统级或自定义服务，请改用 `sudo systemctl edit <unit>`。优先使用由你信任的组织运营的 HTTPS 索引，并且不要将索引凭据放入命令或日志中。

## WebUI 问题

打包的 WebUI 由 WebSocket channel 提供服务。

最小配置：

```json
{
  "channels": {
    "websocket": {
      "enabled": true
    }
  }
}
```

然后运行：

```bash
nanobot gateway
```

打开：

```text
http://127.0.0.1:8765
```

如果从其他设备访问，请将 WebSocket channel 绑定到 `0.0.0.0`，并设置 `token` 或 `tokenIssueSecret`。WebSocket channel 会拒绝没有 token 或 token issue secret 的公共绑定。

有关 LAN 设置，请参阅 [`webui.md#lan-access`](webui-zh.md#lan-access)；有关前端开发，请参阅 [`../webui/README.md`](../webui/README.md)。

## 聊天应用问题

在调试聊天应用之前：

```bash
nanobot agent -m "Hello!"
nanobot channels status
nanobot gateway
```

然后检查：

| 症状 | 检查项 |
|---|---|
| Bot 从不回复 | Gateway 未运行、channel 未启用，或者 bot/app token 错误。 |
| 未知发送者被忽略 | 配置 `allowFrom`、配对或 channel 特定的允许列表。 |
| Telegram 显示已保存的配置但无法完成实时检查 | token 已保存。确认 gateway 可以访问 `api.telegram.org`，或打开 **设置 → Channels → Telegram → 高级 → 网络代理** 并输入 HTTP 或 SOCKS 代理。 |
| Telegram 拒绝 token | 从 BotFather 复制当前 token 或重新生成。 |
| Telegram 未收到消息 | 确认 channel 已启用、gateway 正在运行，并且发送者已配对或列在 `allowFrom` 中。 |
| Discord 回复缺失 | 启用 Message Content intent，并使用所需权限邀请 bot。 |
| WhatsApp 或 WeChat 登录已过期 | 重新运行 `nanobot channels login whatsapp` 或 `nanobot channels login weixin`。 |
| 聊天应用正常但 WebUI 不工作 | provider 和 gateway 很可能正常；请单独调试 WebSocket channel。 |

有关 channel 特定设置，请参阅 [`chat-apps.md`](chat-apps-zh.md)。

## Tool 和 Workspace 问题

| 症状 | 检查项 |
|---|---|
| 文件访问被拒绝 | 检查 `tools.restrictToWorkspace`，以及目标路径是否位于活动 workspace 内。 |
| Shell 命令在 Docker 中失败 | Sandbox 设置可能需要 Linux capabilities；请参阅 [`deployment.md`](deployment-zh.md)。 |
| Web fetch 被阻止 | SSRF 防护会阻止不安全的目标；仅对受信任的私有网络使用 `tools.ssrfWhitelist`。 |
| MCP tool 缺失 | 检查 `tools.mcpServers`、server 启动命令、环境变量和 tool 允许列表。 |
| 生成的产物缺失 | 检查活动 workspace 和 channel 媒体目录。 |

## Memory 和 Session 问题

| 症状 | 检查项 |
|---|---|
| 对话上下文似乎不正确 | 确认活动 workspace 和 session。WebUI 聊天和聊天应用线程可能使用不同的 session。 |
| Memory 不会立即更新 | Dream consolidation 是定期执行的；最近的轮次仍保留在 session 历史记录中。 |
| 移动配置后出现旧 session | Session 文件存储在 `<workspace>/sessions/` 下；请验证 workspace 路径。 |
| 希望在设备之间使用一个共享 session | 有意设置 `agents.defaults.unifiedSession`；否则请保持独立 session。 |

## 收集有用证据

在提交 issue 或寻求帮助时，请包含：

- 安装方式和 `nanobot --version`；
- 操作系统和 Python 版本；
- 运行的命令；
- 相关的 `nanobot status` 输出；
- 已脱敏的配置片段，尤其是 provider、model、channel 和 tool 设置；
- 来自 `nanobot gateway --verbose` 的 gateway 日志；
- `nanobot agent -m "Hello!"` 是否正常工作。

切勿在公开 issue 中粘贴真实 API key、bot token、OAuth token 或私有聊天 ID。

如果发现文档错误、命令过时或步骤令人困惑，请提交 issue：<https://github.com/HKUDS/nanobot/issues>。
