# nanobot 中文使用指南

> 面向新手的快速上手文档，涵盖 Docker 部署、浏览器自动化和安全配置。

---

## 目录

- [简介](#简介)
- [快速开始](#快速开始)
- [Docker Compose 部署](#docker-compose-部署)
  - [标准模式（无 Browser）](#标准模式无-browser)
  - [Browser 模式](#browser-模式)
  - [从标准模式升级到 Browser 模式](#从标准模式升级到-browser-模式)
  - [常用 Docker 命令](#常用-docker-命令)
- [配置文件说明](#配置文件说明)
- [浏览器自动化（Browser 工具）](#浏览器自动化browser-工具)
  - [启用方式](#启用方式)
  - [可用工具一览](#可用工具一览)
  - [使用示例](#使用示例)
  - [常见问题](#常见问题)
- [安全事项](#安全事项)
  - [必做清单](#必做清单)
  - [访问控制](#访问控制)
  - [文件权限](#文件权限)
  - [已知限制](#已知限制)
- [常用命令参考](#常用命令参考)

---

## 简介

**nanobot** 是一个超轻量级个人 AI 助手框架，支持接入 Telegram、Discord、微信、钉钉、飞书等 15 个聊天平台，内置文件操作、Shell 执行、Web 搜索、浏览器自动化等工具。

---

## 快速开始

**1. 安装**

```bash
# 从源码安装（推荐，获取最新功能）
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .

# 或从 PyPI 安装稳定版
pip install nanobot-ai
```

**2. 初始化**

```bash
nanobot onboard
```

**3. 填写 API Key**（编辑 `~/.nanobot/config.json`）

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

**4. 启动聊天**

```bash
nanobot agent
```

---

## Docker Compose 部署

nanobot 提供两种 Docker Compose 配置：

| | 标准模式 | Browser 模式 |
|---|---|---|
| 配置文件 | `docker-compose.yml` | `docker/docker-compose.browser.yml` |
| 容器名 | `nanobot-gateway` | `nanobot-browser` |
| 包含 Chromium | 否 | 是 |
| 内存限制 | 1 GB | 2 GB |
| 适用场景 | 日常对话、文件/Shell 操作 | 需要网页自动化 |

### 标准模式（无 Browser）

```bash
# 第一次使用：初始化配置
docker compose run --rm nanobot-cli onboard

# 编辑配置，填入 API Key
vim ~/.nanobot/config.json

# 启动网关
docker compose up -d nanobot-gateway

# 查看日志
docker compose logs -f nanobot-gateway

# 停止
docker compose down
```

### Browser 模式

```bash
# 第一次使用：构建镜像并启动（含 Playwright + Chromium）
docker compose -f docker/docker-compose.browser.yml up -d --build

# 查看日志
docker compose -f docker/docker-compose.browser.yml logs -f

# 停止
docker compose -f docker/docker-compose.browser.yml down
```

> **注意**：Browser 模式首次启动需要构建镜像（约 3~5 分钟，需下载 Playwright 和 Chromium）。后续重启不需要 `--build`。

### 从标准模式升级到 Browser 模式

如果你之前已经在用 `docker compose up -d nanobot-gateway`，按以下步骤切换：

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 停止当前容器
docker compose down nanobot-gateway

# 3. 构建新镜像并启动
docker compose -f docker/docker-compose.browser.yml up -d --build

# 4. 在配置文件中启用 browser（可选，Compose 文件已通过环境变量启用）
# 编辑 ~/.nanobot/config.json，添加：
# "tools": { "browser": { "enabled": true } }
```

> 你的原有配置（`~/.nanobot`）和对话记录会被新容器继续使用，不会丢失。

### 常用 Docker 命令

```bash
# 进入容器执行命令
docker exec -it nanobot-browser bash

# 发送单条消息测试
docker compose -f docker/docker-compose.browser.yml run --rm nanobot \
  nanobot agent -m "打开 https://example.com 并截图"

# 重建镜像（代码更新后）
docker compose -f docker/docker-compose.browser.yml up -d --build

# 查看资源占用
docker stats nanobot-browser
```

---

## 配置文件说明

配置文件路径：`~/.nanobot/config.json`

**最小配置示例**（只需填写 API Key 和模型）：

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

**完整结构说明**：

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",   // 使用的模型
      "provider": "auto",                       // auto = 自动匹配，或指定 "openrouter"
      "maxTokens": 8192,                        // 最大输出 token 数
      "temperature": 0.1,                       // 生成温度
      "maxToolIterations": 40                   // 最多工具调用轮次
    }
  },
  "providers": {
    "openrouter": { "apiKey": "sk-or-v1-xxx" },
    "anthropic":  { "apiKey": "sk-ant-xxx" },
    "openai":     { "apiKey": "sk-xxx" },
    "ollama":     { "apiBase": "http://localhost:11434" }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["你的 Telegram 用户 ID"]
    }
  },
  "tools": {
    "browser": {
      "enabled": false,         // 是否启用浏览器工具
      "headless": true          // 无头模式（服务器保持 true）
    },
    "web": {
      "search": {
        "provider": "duckduckgo" // 搜索引擎（duckduckgo 免费无需 key）
      }
    },
    "restrictToWorkspace": false  // true = 文件操作限制在 workspace 目录
  }
}
```

> 配置项使用 camelCase（如 `apiKey`、`maxTokens`），修改后无需重启即可对 CLI 模式生效；Docker 模式需要重启容器。

---

## 浏览器自动化（Browser 工具）

### 启用方式

**本地安装：**

```bash
pip install playwright
playwright install chromium
```

在 `~/.nanobot/config.json` 中添加：

```json
{
  "tools": {
    "browser": {
      "enabled": true,
      "headless": true
    }
  }
}
```

**Docker（Browser 模式）：**

Browser 模式的 Docker Compose 已自动安装 Chromium 并通过环境变量启用，无需额外操作。

---

### 可用工具一览

| 分类 | 工具名 | 功能 |
|------|--------|------|
| 导航 | `browser_navigate` | 打开 URL |
| 导航 | `browser_go_back` / `browser_go_forward` | 前进 / 后退 |
| 导航 | `browser_refresh` | 刷新页面 |
| 导航 | `browser_close` | 关闭浏览器 |
| 交互 | `browser_click` | 点击元素（支持 CSS 选择器或文本定位）|
| 交互 | `browser_type` | 在输入框中输入文字 |
| 交互 | `browser_scroll` | 滚动页面 |
| 交互 | `browser_wait` | 等待元素出现 / 消失 / 文本出现 |
| 提取 | `browser_get_text` | 提取页面或元素文本 |
| 截图 | `browser_screenshot` | 截图（支持全页面或指定元素）|
| 导出 | `browser_pdf` | 将页面导出为 PDF（仅 Chromium）|
| JS | `browser_evaluate` | 在页面中执行 JavaScript |
| JS | `browser_add_script` | 注入外部脚本或内联 JS |

---

### 使用示例

直接用自然语言告诉 Agent 要做的事，它会自动选择合适的工具：

**截图：**
```
打开 https://github.com 并截取全页面截图
```

**填写表单并提交：**
```
打开 https://example.com/login，输入用户名 admin 和密码 123456，点击登录按钮
```

**提取数据：**
```
打开 https://news.ycombinator.com，获取前 10 条新闻的标题和链接
```

**导出 PDF：**
```
把当前页面保存为 A4 格式的 PDF，文件名为 report
```

**执行 JS：**
```
在当前页面执行 JavaScript：return document.title
```

---

### 常见问题

| 问题 | 解决方法 |
|------|----------|
| "Browser automation tools are not available" | 检查 `tools.browser.enabled: true`，重启 nanobot |
| 元素点击失败 / 找不到元素 | 在 `browser_click` 前先用 `browser_wait` 等待元素出现 |
| 页面加载超时 | 将 `waitUntil` 改为 `"domcontentloaded"`，或增大 `defaultTimeout` |
| Docker 中浏览器启动失败 | 确认使用了 Browser 模式镜像，容器内存 ≥ 2 GB |
| 网站拒绝自动化访问 | 在配置中设置 `userAgent` 为真实浏览器 UA |

---

## 安全事项

### 必做清单

在正式使用前，请逐项确认：

- [ ] **API Key 不要提交到 Git**（config.json 已在 .gitignore 中）
- [ ] **设置配置文件权限**：`chmod 600 ~/.nanobot/config.json`
- [ ] **为每个渠道配置 `allowFrom`**，只允许自己的账号
- [ ] **不要用 root 账户运行 nanobot**
- [ ] **定期更新**：`pip install -U nanobot-ai`

### 访问控制

每个渠道都有 `allowFrom` 白名单，**留空表示拒绝所有人**（v0.1.4.post4 起）：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["123456789"]    // 填你的 Telegram 用户 ID
    },
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["987654321098765432"]  // Discord 用户 ID
    }
  }
}
```

> 临时允许所有人：`"allowFrom": ["*"]`（仅限测试，**生产环境不要这样做**）

### 文件权限

```bash
# 保护配置目录
chmod 700 ~/.nanobot

# 保护配置文件（仅当前用户可读写）
chmod 600 ~/.nanobot/config.json

# 保护 WhatsApp 认证数据
chmod 700 ~/.nanobot/whatsapp-auth
```

### 沙箱模式

如果担心 Agent 误操作文件系统，可以开启沙箱，限制文件操作仅在 workspace 目录内：

```json
{
  "tools": {
    "restrictToWorkspace": true
  }
}
```

### 浏览器安全注意事项

- 浏览器工具可以访问任意网站，请确保只在受信任的环境中启用
- 不要让 Agent 访问包含你个人账号 Cookie 的网站（浏览器上下文是独立的，但仍需注意）
- Docker Browser 模式已自动禁用沙箱（`--no-sandbox`），这是 Docker 容器内运行 Chromium 的必要配置，不影响宿主机安全

### 已知限制

| 限制项 | 说明 | 建议 |
|--------|------|------|
| 无速率限制 | 用户可无限发消息 | 在 API 提供商处设置用量上限 |
| 配置文件明文存储 | API Key 以明文保存 | 设置文件权限 600，生产环境考虑环境变量 |
| Shell 命令过滤有限 | 仅拦截明显危险命令 | 开启 `restrictToWorkspace`，以低权限用户运行 |
| 无会话过期机制 | 对话历史永久保留 | 定期用 `/new` 开启新会话 |

---

## 常用命令参考

```bash
# 初始化
nanobot onboard

# 对话
nanobot agent                    # 交互模式
nanobot agent -m "你好"          # 单条消息
nanobot agent --logs             # 显示运行日志

# 网关（用于接入 Telegram / Discord 等）
nanobot gateway

# 状态查看
nanobot status

# 斜杠命令（对话中使用）
/new       # 开启新会话（清空历史）
/stop      # 停止当前任务
/restart   # 重启 bot
/help      # 查看可用命令

# Docker（标准模式）
docker compose up -d nanobot-gateway
docker compose logs -f nanobot-gateway
docker compose down

# Docker（Browser 模式）
docker compose -f docker/docker-compose.browser.yml up -d --build
docker compose -f docker/docker-compose.browser.yml logs -f
docker compose -f docker/docker-compose.browser.yml down
```

---

> 更多详细文档：
> - 完整英文 README：[README.md](./README.md)
> - 浏览器工具详细说明：[docs/BROWSER_TOOLS.md](./docs/BROWSER_TOOLS.md)
> - 安全策略：[SECURITY.md](./SECURITY.md)
> - 渠道插件开发：[docs/CHANNEL_PLUGIN_GUIDE.md](./docs/CHANNEL_PLUGIN_GUIDE.md)
