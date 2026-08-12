# 部署

在本地成功运行 `nanobot agent -m "Hello!"` 后使用本页。部署可使长时间运行的表面保持在线：WebUI、聊天应用、heartbeat、Dream、cron jobs 和 channel 连接。

## 部署前准备

在使用 Render、Docker、systemd 或 LaunchAgent 前，逐项检查以下内容：

| 检查项 | 重要原因 |
|---|---|
| `nanobot status` 显示预期的 config 和 workspace | 确认进程将读取你打算运行的实例 |
| `nanobot agent -m "Hello!"` 能正常工作 | 在添加 service 层之前，验证安装、config、provider、model 以及 workspace 写入 |
| Secrets 位于环境变量或受保护的 config 文件中 | API keys、bot tokens、OAuth state 和聊天凭据不应对所有用户可读 |
| `~/.nanobot/` 或自定义 config/workspace 路径是持久化的 | Sessions、memory、channel 登录状态、生成的 artifacts 和 cron jobs 均存放于此 |
| Channel 访问控制经过明确规划 | 在暴露 bot 之前，使用 `allowFrom`、pairing、WebSocket `token`/`tokenIssueSecret` 或私有测试 channel |
| 已规划端口 | Gateway health 默认仅限本地 `127.0.0.1:18790`；WebUI/WebSocket 默认使用 `8765`；`nanobot serve` 默认使用 `8900` |
| Logs 易于访问 | 排查启动问题时，使用 `docker compose logs`、`journalctl`、LaunchAgent log 文件或 `nanobot gateway --verbose` |

编辑 `config.json` 后请重启已部署的进程。长时间运行的进程会在启动时读取 config。

## 选择运行环境

| 运行环境 | 适用场景 | 状态位置 | 有用的首个命令 |
|---|---|---|---|
| Render | 一键托管的 gateway 和 WebUI | `/home/nanobot/.nanobot` 上的持久磁盘 | [部署到 Render](#render) |
| Docker Compose | Linux 服务器或工作站上的可重复 container 运行 | 将 `~/.nanobot` bind-mount 到 `/home/nanobot/.nanobot` | `docker compose run --rm nanobot-cli agent -m "Hello!"` |
| Docker CLI | 手动 container 测试或小型一次性主机 | 将 `~/.nanobot` bind-mount 到 `/home/nanobot/.nanobot` | `docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot status` |
| systemd user service | 自动重启的 Linux 用户级 gateway | 除非传递显式路径，否则使用主机用户的 `~/.nanobot` | `systemctl --user status nanobot-gateway` |
| macOS LaunchAgent | 登录后启动的 macOS gateway | 除非 plist 传递显式路径，否则使用主机用户的 `~/.nanobot` | `launchctl list | grep ai.nanobot.gateway` |

## Render

无需管理服务器即可让 nanobot 在线运行。蓝图会一同部署 gateway 和内置 WebUI，并提供持久磁盘，使 sessions、memory 和聊天历史记录在重启后仍能保留。

> [!IMPORTANT]
> 此设置需要付费的 Render service，因为免费套餐不提供持久磁盘。设置期间，请提供 `ANTHROPIC_API_KEY`，并将 `NANOBOT_WEB_TOKEN` 设为高强度私密密码（例如使用 `openssl rand -hex 32` 生成）。

[![部署到 Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/HKUDS/nanobot)

[查看部署蓝图](../render.yaml)

### 首次部署

1. 点击**部署到 Render**，登录并查看 Blueprint。它会创建一个 Starter web service 和一个 1 GB 持久磁盘。
2. 输入你的 `ANTHROPIC_API_KEY`。将 `NANOBOT_WEB_TOKEN` 设为新的随机值，并保存到密码管理器中；这是公开 WebUI 的密码。
3. 创建 Blueprint，并等待 service 状态变为 **Live**。首次构建可能需要几分钟。
4. 打开生成的 `onrender.com` URL。出现**需要身份验证**页面表示 gateway 正在运行：输入相同的 `NANOBOT_WEB_TOKEN` 值以打开 WebUI。

model API key 由 nanobot 用于调用 Anthropic。Web token 仅保护对此部署的访问；请勿在 issues、截图或聊天中分享它。

### 更新和数据

Blueprint 禁用了自动部署，因此上游仓库变更不会意外重启你的 agent。要更新，请在 Render Dashboard 中打开该 service，然后选择**手动部署 → 部署最新 commit**。

持久磁盘会在重启和更新期间保留 `config.json`、sessions、memory、WebUI 历史记录、cron 状态、媒体和 logs。该部署仅在 `config.json` 尚不存在时初始化它，因此之后在 WebUI 中更改的设置不会在每次启动时被替换。

如果部署失败，请先打开 service 的 **Logs** 页面。缺少 model key 会在启动后导致 provider 请求失败，而不正确的 Web token 会使你停留在身份验证页面。

## Docker

> [!TIP]
> `-v ~/.nanobot:/home/nanobot/.nanobot` 标志会将本地 config 目录挂载到 container 中，因此你的 config 和 workspace 会在 container 重启后保持不变。
> container 以非 root 用户 `nanobot`（UID 1000）运行，并从 `/home/nanobot/.nanobot` 读取 config。请始终将主机 config 目录挂载到 `/home/nanobot/.nanobot`，而非 `/root/.nanobot`。
> 如果收到**Permission denied**，请先在主机上修复所有权：`sudo chown -R 1000:1000 ~/.nanobot`，或传递 `--user $(id -u):$(id -g)` 以匹配主机 UID。Podman 用户可改用 `--userns=keep-id`。
>
> [!IMPORTANT]
> 官方 Docker 用法目前是使用附带的 `Dockerfile` 从此仓库构建。第三方 namespace 下的 Docker Hub images 并非由 HKUDS/nanobot 维护或验证；除非信任发布者，否则不要向其中挂载 API keys 或 bot tokens。

> [!IMPORTANT]
> gateway 和 WebSocket channel 在 `config.json` 中默认使用 `host: "127.0.0.1"`（在 `nanobot/config/schema.py` 中设置）。Docker `-p` 端口转发无法访问 container 的 loopback interface，因此若要让主机或 LAN 访问暴露的端口，必须在启动 container 前将 `~/.nanobot/config.json` 中的两个 bind 都设为 `0.0.0.0`。若要从 Docker 提供内置 WebUI，请将 WebSocket channel 外部 bind，并使用 `tokenIssueSecret` 保护 bootstrap：
>
> ```json
> {
>   "gateway": { "host": "0.0.0.0" },
>   "channels": {
>     "websocket": {
>       "host": "0.0.0.0",
>       "port": 8765,
>       "tokenIssueSecret": "your-secret-here"
>     }
>   }
> }
> ```
>
> 当 WebSocket `host` 为 `0.0.0.0` 时，除非同时配置 `token`、`tokenIssueSecret` 或完整配置的 `trustedProxyAuth`，否则 channel 将拒绝启动。详见 [`webui.md#lan-access`](webui-zh.md#lan-access)。
> gateway health route 本身经过有意设计，保持最小化且无需身份验证。当
> container 将其 bind 到 `0.0.0.0` 时，仅将端口 `18790` 发布到主机 loopback；
> 将任何远程监控的 health endpoint 置于 firewall 或 reverse proxy 后方。如果其他主机
> 必须直接探测它，请在端口映射中将 `127.0.0.1` 替换为受信任的主机
> interface，并将入站流量限制为监控系统。

### Cloudflare Tunnel + Cloudflare Access

对于位于 nanobot 前方的本地 `cloudflared` 进程，Cloudflare Access 可以
在转发请求前对用户进行身份验证，并添加
`Cf-Access-Jwt-Assertion`。仅当
直接 TCP peer 为 tunnel 进程且 assertion 非空时，才选择启用 trusted-proxy 无 token 模式：

```json
{
  "gateway": { "host": "127.0.0.1" },
  "channels": {
    "websocket": {
      "host": "127.0.0.1",
      "port": 8765,
      "publicWsUrl": "wss://nanobot.example.com/",
      "trustedProxyAuth": {
        "trustedPeerCidrs": ["127.0.0.1/32", "::1/128"],
        "assertionHeader": "Cf-Access-Jwt-Assertion"
      }
    }
  }
}
```

这是两部分授权：受信任的直接 loopback peer **以及**
非空的 Cloudflare Access assertion。仅有受信任 CIDR 并不是绕过机制。
对于此流程，`/webui/bootstrap` 会返回连接 metadata，但不返回
bootstrap token 或 REST API token；proxy assertion 会直接授权 WebSocket
handshake 和 REST requests。

当 tunnel 发送 origin host header（例如 `127.0.0.1:8765`）时，
请将 `publicWsUrl` 设为面向浏览器的 `wss://` endpoint；否则 WebUI 可能会
尝试直接针对 loopback 地址打开其 WebSocket。
assertion header 必须在身份验证后由 Cloudflare Access 生成；诸如
`Host`、`Forwarded`、`X-Forwarded-*`、`X-Real-IP` 和 `CF-Connecting-IP`
等路由/client metadata headers 会被拒绝作为 `assertionHeader` 值。Nanobot 信任该 assertion，但
不会对 JWT 进行加密验证，因此请谨慎配置 tunnel 和 Access
policy，并且不要将 nanobot listener 直接暴露给不受信任的
clients。转发的 client headers 不会建立 proxy 信任。

### Docker Compose

默认 image 预安装了 WhatsApp dependencies。要将其他已启用的
channels 烘焙进 image（建议用于无法访问 PyPI 的部署），请传递以逗号分隔的
`NANOBOT_CHANNELS` build argument：

```bash
NANOBOT_CHANNELS=telegram,slack docker compose build
```

image 将 nanobot 保留在由其内置非 root
runtime 用户（UID 1000）拥有的 virtual environment 中。因此，如果已启用的 channel 未预安装，gateway
启动时可以安装其 manifest 声明的 dependencies。使用 `NANOBOT_CHANNELS` 重新构建
可使该安装保持可复现，而不是依赖 container 的可写 layer。若使用
其他 `--user` 覆盖 container，请将每个已启用的 channel 烘焙到 image 中，因为无法保证该 UID
具有对 virtual environment 的写入权限。

```bash
docker compose run --rm nanobot-cli onboard   # first-time setup
vim ~/.nanobot/config.json                     # add API keys
docker compose up -d nanobot-gateway           # start gateway
```

```bash
docker compose run --rm nanobot-cli agent -m "Hello!"   # run CLI
docker compose logs -f nanobot-gateway                   # view logs
docker compose down                                      # stop
```

默认 Compose 文件移除了所有 Linux capabilities，并保持启用 Docker 默认的
AppArmor/seccomp profiles。若你在 `~/.nanobot/config.json` 中显式设置
`"tools.exec.sandbox": "bwrap"`，请在启动 containers 时添加 bwrap
override 文件：

```bash
docker compose -f docker-compose.yml -f docker-compose.bwrap.yml up -d nanobot-gateway
docker compose -f docker-compose.yml -f docker-compose.bwrap.yml run --rm nanobot-cli agent -m "Hello!"
```

该 override 会授予 `CAP_SYS_ADMIN`，并为
container 禁用 AppArmor/seccomp confinement，以便 bubblewrap 能够创建其嵌套 namespaces。
仅在启用 bwrap sandbox 时使用它。

### Docker

```bash
# Build the image
docker build -t nanobot .

# Or preinstall a regular Python extra such as Bedrock support
docker build --build-arg NANOBOT_EXTRAS=bedrock -t nanobot .

# Or preinstall dependencies for a specific set of channels
docker build --build-arg NANOBOT_CHANNELS=telegram,slack -t nanobot .

# Initialize config (first time only)
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot onboard

# Edit config on host to add API keys
vim ~/.nanobot/config.json

# Run gateway (connects to enabled channels, e.g. Telegram/Discord/Mochat).
# `-p 8765:8765` exposes the WebSocket channel / WebUI alongside the gateway
# health endpoint on 18790.
docker run \
  --cap-drop ALL \
  -v ~/.nanobot:/home/nanobot/.nanobot \
  -p 18790:18790 -p 8765:8765 \
  nanobot gateway

# If `tools.exec.sandbox: "bwrap"` is enabled, run with the extra permissions
# bubblewrap needs for nested namespaces. Without them, `bwrap` may exit with
# `clone3: Operation not permitted`.
docker run \
  --cap-drop ALL --cap-add SYS_ADMIN \
  --security-opt apparmor=unconfined \
  --security-opt seccomp=unconfined \
  -v ~/.nanobot:/home/nanobot/.nanobot \
  -p 127.0.0.1:18790:18790 -p 8765:8765 \
  nanobot gateway

# Or run a single command
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot status
```
## Linux 服务

将 gateway 作为 systemd 用户服务运行，使其自动启动并在失败时重启。

先预览生成的单元：

```bash
nanobot gateway install-service --manager systemd --dry-run
```

安装、启用并启动：

```bash
nanobot gateway install-service --manager systemd
```

对于自定义实例，传入运行 gateway 时使用的相同 config/workspace 选择器：

```bash
nanobot gateway install-service \
  --manager systemd \
  --name nanobot-telegram \
  --config ~/.nanobot-telegram/config.json \
  --workspace ~/.nanobot-telegram/workspace
```

常用操作：

```bash
systemctl --user status nanobot-gateway        # check status
systemctl --user restart nanobot-gateway       # restart after config changes
journalctl --user -u nanobot-gateway -f        # follow logs
nanobot gateway uninstall-service --manager systemd
```

安装程序会写入 `~/.config/systemd/user/nanobot-gateway.service`，运行
`systemctl --user daemon-reload`，启用该单元并重启它。它使用当前的 Python
可执行文件和 `python -m nanobot gateway --foreground`，因此该服务会运行在安装 nanobot 时所使用的相同环境中。

> **注意：** 用户服务仅会在你登录期间运行。若要让 gateway 在注销后继续运行，请启用 lingering：
>
> ```bash
> loginctl enable-linger $USER
> ```

## macOS LaunchAgent

如果你希望 `nanobot gateway` 在登录后保持在线，而无需一直打开终端，请使用 LaunchAgent。

先预览生成的 plist：

```bash
nanobot gateway install-service --manager launchd --dry-run
```

安装、加载、启用并启动：

```bash
nanobot gateway install-service --manager launchd
```

对于自定义实例：

```bash
nanobot gateway install-service \
  --manager launchd \
  --name nanobot-telegram \
  --config ~/.nanobot-telegram/config.json \
  --workspace ~/.nanobot-telegram/workspace
```

常用操作：

```bash
launchctl list | grep ai.nanobot.gateway
launchctl kickstart -k gui/$(id -u)/ai.nanobot.gateway
nanobot gateway uninstall-service --manager launchd
```

安装程序会写入 `~/Library/LaunchAgents/ai.nanobot.gateway.plist`，使用当前的
Python 可执行文件和 `python -m nanobot gateway --foreground`，并将
LaunchAgent 日志写入 `~/.nanobot/logs/`。

> **注意：** 如果启动失败并显示“address already in use”，请先停止手动启动的 `nanobot gateway` 进程。
