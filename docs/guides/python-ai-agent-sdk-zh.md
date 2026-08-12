# Nanobot Python SDK：从 Python 运行 AI 智能体

本指南介绍何时应使用 Nanobot Python SDK，而不是直接调用 model。该 SDK 运行 CLI 使用的相同智能体运行时：model 路由、tool、workspace 访问、session 历史记录、memory、流式事件以及运行时辅助工具。

## 你将构建的内容

- 一个创建 `Nanobot` 的 Python 脚本
- 一次通过代码运行智能体
- 一次可选的流式运行，并显示 tool

## 适用场景

在 notebook、评估、产品后端、本地脚本、工作流运行器以及需要直接访问智能体 session、memory、钩子、运行时状态或结构化运行结果的集成中，使用 Python SDK。

当其他语言或进程应通过 HTTP 调用 nanobot 时，改用 OpenAI 兼容 API。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

## 最小可运行示例

```python
import asyncio

from nanobot import Nanobot


async def main() -> None:
    async with Nanobot.from_config() as bot:
        result = await bot.run("List the top-level files in this workspace.")
    print(result.content)


asyncio.run(main())
```

## 生产环境注意事项

- 对于相关工作，复用同一个 `Nanobot` 实例。
- 当用户、作业或评估用例需要持久化历史记录时，传入 `session_key`。
- 当调用方需要实时文本、tool 或失败事件时，使用 `bot.stream(...)`。
- 使用钩子记录审计日志或实现自定义可观测性。

## 安全注意事项

- SDK 使用与 CLI 相同的配置、workspace、tool 和密钥。
- 不要在具有广泛文件或 shell 访问权限的情况下运行不受信任的提示词。
- 为不同产品或租户使用独立的配置和 workspace 路径。

## 故障排除

- 如果 SDK 代码失败，首先在相同环境中运行 `nanobot agent -m "Hello!"`。
- 打印 `bot.runtime.workspace` 和 `bot.runtime.model`，确认加载了预期的配置。
- 当脚本从服务中运行时，使用显式的 `config_path` 和 `workspace`。

## 相关 nanobot 文档

- [Nanobot Python SDK](../python-sdk-zh.md)
- [OpenAI 兼容 API](../openai-api-zh.md)
- [配置](../configuration-zh.md)
- [概念](../concepts-zh.md)
