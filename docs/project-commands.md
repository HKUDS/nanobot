# 项目命令

这份文档只记录仓库里真实可见、或在仓库文档/CI 中明确出现的命令。

## 安装依赖

- `git clone https://github.com/HKUDS/nanobot.git && cd nanobot`：从源码开始安装
- `pip install -e .`：源码可编辑安装，README 的推荐源码安装方式
- `pip install .[dev]`：安装开发/测试依赖，CI 里就是这么装的
- `pip install nanobot-ai`：从 PyPI 安装正式版
- `uv tool install nanobot-ai`：使用 `uv` 安装正式版
- `conda create -n nanobot python=3.11 pip -y`：本地创建 Python 3.11 环境；这是我在当前工作区实际使用的方式，不是仓库专属命令

## 启动命令

- `nanobot onboard`：初始化配置和工作区
- `nanobot onboard --wizard`：交互式初始化向导
- `nanobot agent`：启动本地 CLI 对话
- `nanobot agent -m "Hello!"`：一次性发送消息并退出
- `nanobot gateway`：启动网关，接入外部聊天渠道
- `nanobot status`：查看当前配置、工作区和模型状态
- `nanobot provider login openai-codex`：Codex OAuth 登录
- `nanobot channels login`：链接 WhatsApp bridge

## 开发模式命令

- `pip install -e .`：开发时最常用的可编辑安装
- `nanobot agent --logs`：在聊天时显示运行日志
- `nanobot gateway --verbose`：网关调试输出
- `nanobot agent -c <config> -w <workspace>`：针对指定配置和工作区运行
- `nanobot gateway -c <config> -w <workspace>`：针对指定配置和工作区运行
- `nanobot onboard -c <config> -w <workspace>`：为多实例初始化独立配置和工作区
- `nanobot onboard --wizard`：需要人工确认时用向导模式

> 说明：仓库里没有看到单独的 `dev-server` 或前端热更新命令，开发时通常直接用上面的 CLI 入口。

## 测试命令

- `python -m pytest tests/ -v`：CI 中实际使用的测试命令
- `pytest tests/ -v`：本地等价写法，功能上与 CI 一致

## 构建命令

- `docker build -t nanobot .`：README 中明确提供的镜像构建命令
- `docker compose up -d nanobot-gateway`：Compose 方式启动网关，适合搭配容器环境

> 说明：仓库里没有看到单独的 Python 打包/发布脚本命令；`pyproject.toml` 使用 `hatchling` 作为 build backend，但 README 没有另外列出 `python -m build` 或 `hatch build`。

## lint / format 命令

- lint：未发现仓库内定义的专用 lint 命令；`pyproject.toml` 只配置了 `ruff` 规则
- format：未发现仓库内定义的专用 format 命令；仓库里没有看到 `black` 或 `ruff format` 的固定脚本

> 如果你想本地做临时检查，可以手动运行 `ruff check .`；但这不是仓库里显式定义的脚本命令。

---

## 对话中的 Slash 命令

在对话过程中（`nanobot agent` 或网关模式）可以使用的命令：

| 命令 | 作用 | 优先级 |
|------|------|--------|
| `/help` | 显示可用命令列表 | exact |
| `/new` | 开始新对话（清空当前会话历史） | exact |
| `/stop` | 停止当前任务（取消活跃的任务和子代理） | priority |
| `/restart` | 重启 bot（延迟1秒后执行） | priority |
| `/status` | 显示 bot 状态（版本、模型、运行时间、上下文使用量等） | priority |

> 命令优先级说明：
> - **priority**: 在锁之前处理，用于需要立即响应的命令（如停止、重启）
> - **exact**: 精确匹配，在锁内处理
> - **prefix**: 前缀匹配，用于带参数的命令
> - **interceptors**: 拦截器，用于动态检查（如 team 模式激活）
>
> 源码位置： `nanobot/command/builtin.py`
